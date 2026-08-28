"""Orchestrator for contract analysis pipeline and parallel redline flow.

Coordinates Agent1 -> Agent2 -> Agent3 analysis and parallel redline phases
(Phase 1: match, Phase 2: resolve, Phase 3: edit, Phase 4: apply).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_WORKERS = 4


def run_analysis_pipeline(
    uploaded_full_text: str,
    knowledge_payload: dict,
    *,
    supporting_doc_texts: Optional[Dict[str, str]] = None,
    uploaded_filenames: Optional[List[str]] = None,
    rag_session_id: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], str, str]:
    """Run Agent1 -> Agent2 -> Agent3 in sequence.

    Returns:
        (clause_table, agent2_output, agent3_output)
    """
    try:
        from agents.sample_agent import agent1_clause_analyzer as agent1  # type: ignore
        from agents.sample_agent import agent2_reviewer as agent2  # type: ignore
        from agents.sample_agent import agent3_mitigation_checklist as agent3  # type: ignore
    except ImportError:  # pragma: no cover - legacy path
        import agent1_clause_analyzer as agent1  # type: ignore
        import agent2_reviewer as agent2  # type: ignore
        import agent3_mitigation_checklist as agent3  # type: ignore

    clause_table = agent1.run_aerospace_clause_extraction(
        contract_text=uploaded_full_text,
        knowledge_payload=knowledge_payload,
        supporting_doc_texts=supporting_doc_texts,
        uploaded_filenames=uploaded_filenames,
        rag_session_id=rag_session_id,
    )
    if not clause_table:
        return [], "", ""

    def _to_agent1_markdown(rows: List[Dict[str, str]]) -> str:
        lines = [
            "| Clause | Requirement | Met/Gap | References |",
            "|--------|-------------|---------|------------|",
        ]
        for idx, row in enumerate(rows, start=1):
            clause = row.get("clause_name", "")
            requirement = row.get("gb_ideal_position", "")
            risk = row.get("risk_level", "Amber")
            status = row.get("detected", "Unclear")
            rationale = row.get("risk_rationale", "")
            references = row.get("knowledge_reference", "")
            met_gap = f"{status} ({risk}) - {rationale}"
            lines.append(f"| {idx}. {clause} | {requirement} | {met_gap} | {references} |")
        return "\n".join(lines)

    agent1_output = _to_agent1_markdown(clause_table)
    knowledge_text = _knowledge_as_text(knowledge_payload)
    try:
        from . import config as agent_config
    except ImportError:  # pragma: no cover
        import config as agent_config  # type: ignore

    po_for_agent2 = uploaded_full_text
    if getattr(agent_config, "ENABLE_GRAPHRAG", False):
        try:
            from .graphrag_lite import compute_graphrag_context

            gr_ctx = compute_graphrag_context(
                primary_name="",
                primary_text=uploaded_full_text,
                supporting_doc_texts=supporting_doc_texts,
                clause_table=clause_table,
                max_chars=int(getattr(agent_config, "GRAPHRAG_MAX_CHARS", 3500) or 3500),
            )
            if gr_ctx.strip():
                po_for_agent2 = f"{uploaded_full_text}\n\n### Cross-document context (GraphRAG-lite)\n{gr_ctx.strip()}"
        except Exception as exc:
            if getattr(agent_config, "DEBUG_AGENT", False):
                logger.warning("GraphRAG-lite enrichment skipped: %s", exc)

    agent2_output = agent2.generate_risk_mitigation(
        agent1_output=agent1_output,
        po_text=po_for_agent2,
        terms_text=knowledge_text,
        clause_table=clause_table,
    )
    if hasattr(agent3, "generate_mitigation_checklist_from_table"):
        agent3_output = agent3.generate_mitigation_checklist_from_table(clause_table)
    else:
        agent3_output = agent3.generate_mitigation_checklist(agent2_output)
    return clause_table, agent2_output, agent3_output


def _knowledge_as_text(payload: dict) -> str:
    if not payload:
        return ""
    if payload.get("raw_text"):
        return str(payload.get("raw_text"))
    from .knowledge_loader import payload_to_text
    return payload_to_text(payload)


def run_redline_phase1_match(
    instructions: List[Dict[str, str]],
    doc,
    *,
    flat_paragraphs: Optional[List] = None,
    source_contract_text: str = "",
) -> List[Optional[Tuple[int, int, float]]]:
    """Parallel evidence validation + paragraph matching per clause.

    For each clause, validates evidence and finds best matching paragraph.
    Uses empty used_indexes (no conflict resolution yet).

    Returns:
        List of (clause_idx, para_idx, score) or None per instruction.
        clause_idx is 0-based; para_idx indexes the flat paragraph list (body + tables).
    """
    from .redline_docx import (
        _align_evidence_snippet_to_document,
        _find_best_matching_paragraph_index_with_score,
        _first_evidence,
        _flatten_doc_paragraphs,
        _normalize_instruction,
    )
    from .semantic_edit_generator import validate_evidence_for_clause

    paras = flat_paragraphs if flat_paragraphs is not None else (
        _flatten_doc_paragraphs(doc) or list(doc.paragraphs)
    )

    def _match_one(args: Tuple[int, Dict[str, str]]) -> Optional[Tuple[int, int, float]]:
        clause_idx, raw = args
        row = _normalize_instruction(raw, clause_idx + 1)
        if row.get("risk_level") == "Green":
            return None
        if row.get("detected") in {"No", "Unclear"}:
            return None
        evidence = _first_evidence(row.get("evidence_text") or "")
        evidence = _align_evidence_snippet_to_document(
            evidence, paras, source_contract_text=source_contract_text or ""
        )
        if not evidence or evidence.lower().startswith("no direct matching"):
            return None
        if not validate_evidence_for_clause(evidence, row.get("clause_name", "")):
            return None
        result = _find_best_matching_paragraph_index_with_score(
            doc,
            evidence,
            used_indexes=set(),
            uploaded_position=(row.get("uploaded_position") or "").strip(),
            clause_name=(row.get("clause_name") or "").strip(),
            flat_paragraphs=paras,
        )
        if result is None:
            return None
        para_idx, score = result
        return (clause_idx, para_idx, score)

    indexed = [(i, inst) for i, inst in enumerate(instructions)]
    results: List[Optional[Tuple[int, int, float]]] = [None] * len(instructions)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_match_one, item) for item in indexed]
        for i, fut in enumerate(futures):
            try:
                results[indexed[i][0]] = fut.result()
            except Exception as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Phase1 match failed for clause %d: %s", indexed[i][0], exc)
    return results


def run_redline_phase2_resolve(
    assignments: List[Optional[Tuple[int, int, float]]],
    instructions: Optional[List[Dict[str, str]]] = None,
) -> Dict[int, int]:
    """Resolve paragraph conflicts: greedy by score, prefer higher risk.

    When multiple clauses map to the same para_idx, keep the one with
    higher score; on tie, prefer higher risk (Red > Amber > Green).

    Returns:
        Dict clause_idx -> para_idx (0-based).
    """
    risk_rank = {"Red": 3, "Amber": 2, "Green": 1}

    # Group by para_idx: para_idx -> [(clause_idx, score, rank), ...]
    by_para: Dict[int, List[Tuple[int, float, int]]] = {}
    for i, item in enumerate(assignments):
        if item is None:
            continue
        clause_idx, para_idx, score = item
        risk = "Amber"
        if instructions and clause_idx < len(instructions):
            inst = instructions[clause_idx]
            risk = (inst.get("risk_level") or "Amber").strip()
        rank = risk_rank.get(risk, 2)
        by_para.setdefault(para_idx, []).append((clause_idx, score, rank))

    # For each para, pick best clause (highest score, then rank)
    resolved: Dict[int, int] = {}
    for para_idx, clause_list in by_para.items():
        best = max(clause_list, key=lambda x: (x[1], x[2]))
        resolved[best[0]] = para_idx
    return resolved


def run_redline_phase3_edit(
    instructions: List[Dict[str, str]],
    doc,
    assignments: Dict[int, int],
    *,
    flat_paragraphs: Optional[List] = None,
) -> List[Tuple[int, int, str, str, Dict[str, str], bool, Dict[str, str]]]:
    """Parallel semantic edit + Agent4 per assigned clause.

    For each (clause_idx, para_idx) in assignments, computes edited text
    (rule-based then semantic) and runs Agent4 verification.

    Returns:
        List of (clause_idx, para_idx, original_text, edited_text, row, agent4_flagged, agent4_result).
        agent4_result: {"reason": "", "suggestion": ""} when flagged, else empty dict.
    """
    from . import config as agent_config
    from .redline_docx import (
        _flatten_doc_paragraphs,
        _is_valid_edit,
        _is_valid_semantic_edit,
        _matches_original_hint,
        _normalize_for_edit,
        _normalize_instruction,
    )
    from .semantic_edit_generator import generate_semantic_edit

    paras = flat_paragraphs if flat_paragraphs is not None else (
        _flatten_doc_paragraphs(doc) or list(doc.paragraphs)
    )
    n_paras = len(paras)

    def _edit_one(args: Tuple[int, int]) -> Optional[Tuple[int, int, str, str, Dict[str, str], bool, Dict[str, str]]]:
        clause_idx, para_idx = args
        if clause_idx >= len(instructions):
            return None
        row = _normalize_instruction(instructions[clause_idx], clause_idx + 1)
        if para_idx < 0 or para_idx >= n_paras:
            return None
        target_para = paras[para_idx]
        original_text = (target_para.text or "").strip()
        evidence = (row.get("evidence_text") or "").strip()
        if not original_text and evidence:
            original_text = evidence.split(" | ")[0].strip()
        if not _matches_original_hint(original_text, row.get("original_text", "")):
            return None
        rule_snapshot = _normalize_for_edit(original_text, row)
        edited_text = rule_snapshot

        if getattr(agent_config, "ENABLE_SEMANTIC_EDIT_GENERATION", False):
            import re
            orig_norm = re.sub(r"\s+", " ", (original_text or "").strip())
            edit_norm = re.sub(r"\s+", " ", (edited_text or "").strip())
            if not edit_norm or edit_norm == orig_norm:
                surrounding_parts: List[str] = []
                if para_idx > 0:
                    prev = (paras[para_idx - 1].text or "").strip()
                    if prev:
                        surrounding_parts.append(prev)
                if para_idx + 1 < n_paras:
                    nxt = (paras[para_idx + 1].text or "").strip()
                    if nxt:
                        surrounding_parts.append(nxt)
                surrounding_context = "\n".join(surrounding_parts)
                semantic_edited = generate_semantic_edit(
                    original_text=original_text,
                    clause_name=row.get("clause_name", ""),
                    gb_ideal=(row.get("gb_ideal_position") or row.get("suggested_text", "") or ""),
                    surrounding_context=surrounding_context,
                    risk_rationale=(row.get("risk_rationale") or row.get("reason", "") or ""),
                    mitigation_recommendation=(row.get("mitigation_recommendation") or ""),
                )
                if semantic_edited and _is_valid_semantic_edit(
                    original_text, semantic_edited, row.get("clause_name", "")
                ):
                    edited_text = semantic_edited

        if not _is_valid_edit(original_text, edited_text, allow_minimal_replacements=True):
            if getattr(agent_config, "ENABLE_SEMANTIC_FALLBACK_TO_RULE", True) and _is_valid_edit(
                original_text, rule_snapshot, allow_minimal_replacements=True
            ):
                edited_text = rule_snapshot
            if not _is_valid_edit(original_text, edited_text, allow_minimal_replacements=True):
                return None

        agent4_flagged = False
        agent4_result: Dict[str, str] = {}
        if getattr(agent_config, "ENABLE_AGENT4_VERIFICATION", False):
            from .agent4_verifier import verify_redline_edit
            surrounding_parts = []
            if para_idx > 0:
                prev = (paras[para_idx - 1].text or "").strip()
                if prev:
                    surrounding_parts.append(f"[Before] {prev}")
            if para_idx + 1 < n_paras:
                nxt = (paras[para_idx + 1].text or "").strip()
                if nxt:
                    surrounding_parts.append(f"[After] {nxt}")
            surrounding_context = "\n".join(surrounding_parts) if surrounding_parts else "(no surrounding context)"
            result = verify_redline_edit(
                original_text=original_text,
                edited_text=edited_text,
                clause_name=row.get("clause_name", ""),
                surrounding_context=surrounding_context,
                gb_ideal=(row.get("gb_ideal_position") or row.get("suggested_text", "") or ""),
            )
            if result.get("verdict") == "flag":
                agent4_flagged = getattr(agent_config, "SKIP_REDLINE_WHEN_AGENT4_FLAGS", True)
                agent4_result = {
                    "reason": result.get("reason", ""),
                    "suggestion": result.get("suggestion", ""),
                }
        return (clause_idx, para_idx, original_text, edited_text, row, agent4_flagged, agent4_result)

    items = list(assignments.items())
    results: List[Tuple[int, int, str, str, Dict[str, str], bool, Dict[str, str]]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_edit_one, item) for item in items]
        for fut in futures:
            try:
                r = fut.result()
                if r is not None:
                    results.append(r)
            except Exception as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Phase3 edit failed: %s", exc)
    return results
