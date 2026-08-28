"""Load POC knowledge from DOCX or JSON. DOCX is the primary source; JSON is fallback."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None  # type: ignore


def _cell_text(cell: Any) -> str:
    """Extract full text from cell, including nested tables."""
    parts = [(getattr(cell, "text") or "").strip()]
    for nested in getattr(cell, "tables", []) or []:
        for row in getattr(nested, "rows", []):
            for c in getattr(row, "cells", []):
                parts.append((getattr(c, "text") or "").strip())
    return "\n".join(p for p in parts if p)


def _find_header_indices(header_cells: list[str]) -> dict[str, int]:
    """Map column names to 0-based indices."""
    out: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        n = (cell or "").strip().lower()
        if "sr" in n and ("no" in n or "s.no" in n):
            out["sr_no"] = idx
        elif "clause" in n:
            out["clause"] = idx
        elif "explanation" in n or "remark" in n:
            out["explanation"] = idx
        elif "standard" in n or "position" in n or "ideal" in n:
            out["standard_positions"] = idx
        elif "approval" in n or "deviation" in n:
            out["approval"] = idx
    return out


def _split_positions(text: str) -> list[tuple[str, str]]:
    """Split Standard Positions cell by Position 1/2/3."""
    if not (text or "").strip():
        return []
    pattern = re.compile(r"(?mi)^Position\s+(\d+)\s*[:\-]?\s*", re.MULTILINE)
    parts: list[tuple[str, str]] = []
    last_end = 0
    for m in pattern.finditer(text):
        if m.start() > last_end:
            chunk = text[last_end : m.start()].strip()
            if chunk and parts:
                prev_label, prev_text = parts[-1]
                parts[-1] = (prev_label, prev_text + "\n\n" + chunk)
            elif chunk and not parts:
                parts.append(("Position 0 (preamble)", chunk))
        label = f"Position {m.group(1)}"
        rest_start = m.end()
        next_m = pattern.search(text, rest_start)
        chunk = text[rest_start : next_m.start() if next_m else None].strip()
        parts.append((label, chunk))
        last_end = next_m.start() if next_m else len(text)
    if not parts and text.strip():
        parts.append(("Full text", text.strip()))
    return parts


def _extract_gb_ideal_from_cell(text: str) -> tuple[str, str]:
    """For rows 7-10: extract GB's Ideal Position section."""
    if not (text or "").strip():
        return ("", "")
    pattern = re.compile(
        r"(?mi)^(?:GB'?s?\s+)?Ideal\s+Position\s*[:\-]?\s*(.*?)(?=^(?:Original|Remarks|$)|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        return (m.group(1).strip(), text[: m.start()] + text[m.end() :])
    return (text.strip(), "")


def _derive_keywords(explanation: str, ideal: str, existing: list[str]) -> list[str]:
    """Derive keywords from explanation + ideal text."""
    combined = f"{explanation or ''} {ideal or ''}".lower()
    candidates = set(existing) if existing else set()
    for m in re.finditer(r"\d+\.?\d*%?", combined):
        candidates.add(m.group(0))
    stop = {"the", "and", "for", "with", "not", "any", "all", "may", "shall", "this", "that"}
    for w in re.findall(r"\b[a-z]{3,}\b", combined):
        if w not in stop:
            candidates.add(w)
    legal_terms = [
        "liability", "cap", "consequential", "indirect", "damages", "notwithstanding",
        "governing", "law", "jurisdiction", "arbitration", "mediation", "siac", "lcia", "icc",
        "firm", "price", "escalation", "force", "majeure", "liquidated", "termination",
        "forecast", "deviation", "inventory", "change", "order", "equitable", "sow",
    ]
    result = list(existing)
    for t in legal_terms:
        if t in combined and t not in result:
            result.append(t)
    for c in sorted(candidates):
        if c not in result and len(result) < 20:
            result.append(c)
    return result[:20]


def _safe_cell(cells: list[str], col_map: dict[str, int], key: str, default_idx: int) -> str:
    """Safely get cell value; handles merged cells (fewer cells than expected)."""
    idx = col_map.get(key)
    if idx is None:
        idx = default_idx
    if idx >= len(cells):
        return ""
    return (cells[idx] or "").strip()


def parse_contract_positions_docx(docx_path: str | Path) -> dict:
    """
    Parse DOCX and return { meta, clauses } payload.
    Same structure as JSON loader for backward compatibility.
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX not found: {path}")

    if DocxDocument is None:
        raise RuntimeError("python-docx required for DOCX knowledge: pip install python-docx")

    doc = DocxDocument(str(path))

    target_table = None
    for table in doc.tables:
        if table.rows and len(table.rows[0].cells) >= 4:
            target_table = table
            break

    if not target_table:
        return {"meta": {"error": "No suitable table found"}, "clauses": []}

    rows = list(target_table.rows)
    if len(rows) < 2:
        return {"meta": {"error": "Table has no data rows"}, "clauses": []}

    header_cells = [_cell_text(c) for c in rows[0].cells]
    col_map = _find_header_indices(header_cells)
    if "clause" not in col_map:
        logger.warning("DOCX knowledge: Could not find Clause column. Headers: %s", header_cells)

    clauses: list[dict] = []
    for ri, row in enumerate(rows[1:], start=1):
        cells = [_cell_text(c) for c in row.cells]
        if len(cells) < 2:
            continue

        sr_no = _safe_cell(cells, col_map, "sr_no", 0)
        clause_name = _safe_cell(cells, col_map, "clause", 1)
        explanation = _safe_cell(cells, col_map, "explanation", 2)
        standard_pos = _safe_cell(cells, col_map, "standard_positions", 3)
        approval = _safe_cell(cells, col_map, "approval", 4)

        if not clause_name and not standard_pos:
            continue

        # Skip separator rows: rows where all non-empty cells have identical text
        # (e.g. the "Aerospace Business Critical Terms" section-header row)
        non_empty = [c.strip() for c in cells if c.strip()]
        if len(non_empty) >= 2 and len(set(non_empty)) == 1:
            logger.debug("DOCX knowledge: skipping separator row %d: %r", ri, non_empty[0][:60])
            continue
        # Also skip rows that have no numeric sr_no and whose clause name repeats in explanation
        if not sr_no.strip().isdigit() and clause_name and clause_name == explanation:
            logger.debug("DOCX knowledge: skipping section-header row %d: %r", ri, clause_name[:60])
            continue

        clause_id = ri
        try:
            if sr_no and sr_no.isdigit():
                clause_id = int(sr_no)
        except ValueError:
            pass

        is_aerospace_critical = clause_id >= 7

        if is_aerospace_critical:
            ideal_text, _ = _extract_gb_ideal_from_cell(standard_pos)
            if not ideal_text:
                ideal_text = standard_pos
            standard_positions = [{"label": "GB's Ideal Position", "text": ideal_text}] if ideal_text else []
        else:
            positions = _split_positions(standard_pos)
            if len(positions) > 1:
                ideal_text = next((p[1] for p in positions if p[0] == "Position 1"), positions[0][1] if positions else "")
                standard_positions = [{"label": lbl, "text": txt} for lbl, txt in positions if txt]
            else:
                ideal_text = standard_pos
                standard_positions = [{"label": "Full text", "text": standard_pos}] if standard_pos else []

        keywords = _derive_keywords(explanation, ideal_text or standard_pos, [])

        clauses.append({
            "id": clause_id,
            "name": clause_name or f"Clause {clause_id}",
            "explanation": explanation,
            "ideal_position": ideal_text or standard_pos or "",
            "standard_positions": standard_positions,
            "approval_path": approval or "",
            "keywords": keywords,
        })

    meta = {
        "title": "GB Aerospace Critical Positions for POC",
        "source": path.name,
        "scope": "Supply contracts where Aerospace is supplying goods",
        "out_of_scope": [
            "purchase/procurement contracts",
            "sub-contracting",
            "strategic alliances",
            "consortium agreements",
            "NDA/confidentiality agreements",
        ],
    }

    if len(clauses) not in {10, 11}:
        logger.warning("DOCX knowledge: Expected ~10 clauses, got %d", len(clauses))

    return {"meta": meta, "clauses": clauses}


def payload_to_text(payload: dict) -> str:
    """Build searchable text from knowledge payload for RAG indexing.
    Includes explanation and standard_positions for full context.
    """
    if not payload:
        return ""
    if payload.get("raw_text"):
        return str(payload.get("raw_text"))
    clauses = payload.get("clauses") or []
    chunks: list[str] = []
    for c in clauses:
        if not isinstance(c, dict):
            continue
        name = c.get("name", "")
        ideal = c.get("ideal_position", "")
        approval = c.get("approval_path", "")
        explanation = c.get("explanation", "")
        standard_positions = c.get("standard_positions") or []
        keywords = c.get("keywords") or []
        parts = [f"Clause: {name}", f"Ideal: {ideal}", f"Approval: {approval}"]
        if explanation:
            parts.append(f"Explanation: {explanation}")
        for sp in standard_positions:
            if isinstance(sp, dict) and sp.get("text"):
                parts.append(f"Position ({sp.get('label','')}): {sp['text']}")
            elif isinstance(sp, str):
                parts.append(f"Position: {sp}")
        if keywords:
            parts.append(f"Keywords: {', '.join(str(k) for k in keywords[:15])}")
        chunks.append("\n".join(parts))
    return "\n\n".join(chunks)


def load_knowledge_payload(path: str | Path) -> dict:
    """
    Load knowledge from JSON or DOCX. Returns { meta, clauses }.
    """
    p = Path(path)
    if not p.exists():
        return {}

    if p.suffix.lower() == ".json":
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
        except Exception as e:
            logger.warning("Failed to load JSON knowledge %s: %s", p, e)
            return {}

    if p.suffix.lower() == ".docx":
        try:
            return parse_contract_positions_docx(p)
        except Exception as e:
            logger.warning("Failed to parse DOCX knowledge %s: %s", p, e)
            return {}

    return {}
