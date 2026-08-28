"""Semantic edit generator.

Produces context-aware, meaning-preserving edits using the LLM.
Understands the original text's semantics and surrounding context to propose
edits that align with GB ideal positions while reading naturally in place.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from . import config as agent_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a legal contract drafting assistant. Your task is to EDIT the original paragraph "
    "IN-PLACE to align with the company's ideal position.\n\n"
    "CRITICAL - In-place editing only:\n"
    "- Change ONLY the specific phrases, numbers, or clauses that deviate from the ideal — smallest span first.\n"
    "- REPLACE phrases; do NOT concatenate (e.g. 'French law' -> 'English law', NOT 'French English law').\n"
    "- Do NOT insert words into the middle of existing phrases (e.g. 'horizon of the' -> 'lead time of the' or rephrase, NOT 'horizon lead time of the').\n"
    "- Keep the rest of the sentence structure, register, and tone of the original.\n"
    "- Do NOT replace the entire paragraph with the ideal text. The ideal is a target, not a template.\n"
    "- Output the FULL edited paragraph (same approximate length as original), with minimal targeted changes.\n\n"
    "TOPIC FIT - If the original paragraph discusses a DIFFERENT topic than the clause (e.g. manufacturing "
    "location vs inventory requirements, dispute escalation vs liquidated damages), do NOT add clause-specific "
    "language. Return the original unchanged or make only the most minimal change that fits thematically.\n\n"
    "Examples of good in-place edits:\n"
    "- '200%' -> '100%' (liability cap)\n"
    "- 'French law' -> 'English law' or 'laws of [•]' (governing law - REPLACE, not concatenate)\n"
    "- 'before going to court' -> 'by arbitration in accordance with [rules]' (dispute - REPLACE phrase)\n"
    "- '1.5% per week of total order value' -> '0.5% per week of delayed value' (LD)\n"
    "- 'economic hardship, and cash-flow disruptions' -> 'economic hardship and cash-flow disruptions are excluded' (FM)\n\n"
    "Rules:\n"
    "- Preserve the clause's legal intent. Do not change meaning beyond what is needed.\n"
    "- Use the SAME sentence structure as the original where possible.\n"
    "- Do not insert boilerplate or generic language. Do not over-expand.\n"
    "- Output ONLY valid JSON: {\"edited_text\": \"...\", \"confidence\": \"high\"|\"medium\"|\"low\"}."
)

EVIDENCE_VALIDATION_SYSTEM = (
    "You are a legal contract analyst. Determine whether a given text snippet (evidence) "
    "actually describes or belongs to a specific contract clause. Consider the semantic "
    "meaning: does the snippet discuss the topic of the clause, or is it from a different "
    "section?\n\n"
    "Examples of belongs_to_clause=FALSE (cross-clause pollution):\n"
    "- '15 days of receipt' / 'within 15 days' for Liquidated Damages (dispute escalation)\n"
    "- 'Supplier will defend, hold harmless and indemnify' for Liquidated Damages (indemnification clause)\n"
    "- '180 days prior to the proposed change' for Force Majeure (design-change clause)\n"
    "- 'loss of business which is incapable of accurate estimation' for Limitation of Liability (consequential carve-out)\n"
    "- 'manufacturing location' for Inventory Requirements (manufacturing clause)\n"
    "- 'partial termination of this agreement' for Orders Extending (termination procedure)\n"
    "- 'schedule and/or quantity changes are not eligible for equitable adjustment' for Quantity Protection (change-order clause)\n"
    "- 'export license be withdrawn' / 'claim compensation for damage sustained by this breach' for Liquidated Damages (export control, not delivery LD)\n"
    "- 'penalty per overdue calendar day' / '0,5% of the Order Line' for Limitation of Liability (LD clause, not LoL)\n\n"
    "Only set belongs_to_clause=false when confidence is HIGH. When uncertain, set true.\n"
    "Output ONLY valid JSON: {\"belongs_to_clause\": true or false, \"confidence\": \"high\"|\"medium\"|\"low\", \"reason\": \"...\"}."
)


def _build_user_prompt(
    original_text: str,
    clause_name: str,
    gb_ideal: str,
    surrounding_context: str,
    risk_rationale: str = "",
    mitigation_recommendation: str = "",
) -> str:
    parts = [
        f"Clause type: {clause_name}",
        f"Company ideal position: {gb_ideal}",
        "",
        "Original paragraph to edit:",
        original_text,
        "",
        "Surrounding context (paragraphs before/after):",
        surrounding_context or "(none provided)",
    ]
    if risk_rationale:
        parts.extend(["", "Risk rationale (what is wrong with current text):", risk_rationale])
    if mitigation_recommendation:
        parts.extend(["", "Mitigation guidance:", mitigation_recommendation])
    parts.extend(
        [
            "",
            "EDIT the original paragraph IN-PLACE. Change only what deviates from the ideal. "
            "Keep the sentence structure. Output the full edited paragraph as JSON.",
        ]
    )
    return "\n".join(parts)


def _extract_edited_text(text: str) -> tuple[str | None, str]:
    if not text or not text.strip():
        return None, "low"
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and "edited_text" in obj:
            edited = str(obj.get("edited_text", "")).strip()
            conf = str(obj.get("confidence", "medium")).lower()
            if conf not in ("high", "medium", "low"):
                conf = "medium"
            return edited if edited else None, conf
    except json.JSONDecodeError:
        pass
    code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_block:
        try:
            obj = json.loads(code_block.group(1).strip())
            if isinstance(obj, dict) and "edited_text" in obj:
                edited = str(obj.get("edited_text", "")).strip()
                return edited if edited else None, str(obj.get("confidence", "medium")).lower()
        except json.JSONDecodeError:
            pass
    for match in re.finditer(r"\{[^{}]*\"edited_text\"[^{}]*\}", text):
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict) and "edited_text" in obj:
                edited = str(obj.get("edited_text", "")).strip()
                return edited if edited else None, "medium"
        except json.JSONDecodeError:
            continue
    return None, "low"


def generate_semantic_edit(
    original_text: str,
    clause_name: str,
    gb_ideal: str,
    surrounding_context: str = "",
    risk_rationale: str = "",
    mitigation_recommendation: str = "",
) -> Optional[str]:
    """Use the LLM to generate a context-aware edit. Returns edited text or None."""
    if not (original_text or "").strip() or not (gb_ideal or "").strip():
        return None
    try:
        user_prompt = _build_user_prompt(
            original_text=original_text.strip(),
            clause_name=clause_name or "",
            gb_ideal=gb_ideal.strip(),
            surrounding_context=(surrounding_context or "").strip(),
            risk_rationale=(risk_rationale or "").strip(),
            mitigation_recommendation=(mitigation_recommendation or "").strip(),
        )
        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat
            raw_response = call_bedrock_chat(prompt=user_prompt, system_message=SYSTEM_PROMPT)
        else:
            from .local_llm import call_local_chat
            raw_response = call_local_chat(
                prompt=user_prompt,
                system_message=SYSTEM_PROMPT,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_EDITING", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_EDITING", 0.05),
            )
        edited, confidence = _extract_edited_text(raw_response)
        if edited is None:
            return None
        orig_norm = re.sub(r"\s+", " ", original_text.strip())
        edited_norm = re.sub(r"\s+", " ", edited.strip())
        if not edited_norm or edited_norm == orig_norm:
            return None
        if agent_config.DEBUG_AGENT:
            logger.info("Semantic edit: clause=%s confidence=%s", clause_name, confidence)
        return edited.strip()
    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Semantic edit failed: %s", exc)
        return None


EDIT_SEMANTIC_VALIDATOR_SYSTEM = (
    "You are a legal contract reviewer. Determine whether a proposed edit preserves the clause's "
    "legal intent and aligns with the stated policy ideal. Consider: does the edit change only "
    "what is needed, or does it alter meaning incorrectly? "
    "Output ONLY valid JSON: {\"valid\": true or false, \"reason\": \"...\"}."
)


def validate_edit_semantics(
    original_text: str,
    edited_text: str,
    clause_name: str,
    gb_ideal: str,
) -> bool:
    """LLM checks that the edit preserves legal intent and aligns with policy. Returns True if valid."""
    if not getattr(agent_config, "ENABLE_EDIT_SEMANTIC_VALIDATION", False):
        return True
    original_text = (original_text or "").strip()
    edited_text = (edited_text or "").strip()
    if not original_text or not edited_text or original_text == edited_text:
        return True
    try:
        prompt = (
            f"Clause: {clause_name or 'Unnamed'}\n"
            f"Policy ideal: {(gb_ideal or '')[:200]}\n\n"
            f"Original: {original_text[:400]}\n\n"
            f"Edited: {edited_text[:400]}\n\n"
            "Does this edit preserve legal intent and align with the policy? Output JSON only."
        )
        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat
            raw = call_bedrock_chat(prompt=prompt, system_message=EDIT_SEMANTIC_VALIDATOR_SYSTEM)
        else:
            from .local_llm import call_local_chat
            raw = call_local_chat(
                prompt=prompt,
                system_message=EDIT_SEMANTIC_VALIDATOR_SYSTEM,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CLASSIFY", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CLASSIFY", 0.0),
            )
        text = (raw or "").strip()
        obj = None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*\"valid\"[^{}]*\}", text)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        if isinstance(obj, dict) and "valid" in obj:
            result = bool(obj.get("valid", True))
            if agent_config.DEBUG_AGENT:
                logger.info("Edit semantic validation: clause=%s valid=%s", clause_name[:40], result)
            return result
        return True
    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Edit semantic validation failed: %s", exc)
        return True


def validate_evidence_for_clause(evidence_snippet: str, clause_name: str) -> bool:
    """LLM confirms evidence belongs to the clause. Returns True if valid; on error returns True (permissive).
    When confidence is 'low' or 'medium' and belongs_to_clause is false, we allow through (soften strict reject)."""
    if not getattr(agent_config, "ENABLE_EVIDENCE_CLAUSE_VALIDATION", False):
        return True
    evidence = (evidence_snippet or "").strip()
    clause = (clause_name or "").strip()
    if not evidence or not clause or len(evidence) < 20:
        return True
    prompt = (
        f"Clause: {clause}\n\nEvidence snippet: {evidence}\n\n"
        "Does this evidence actually describe or discuss the clause above? "
        "Common mismatches: '15 days of receipt' often appears in dispute escalation, not liquidated damages; "
        "'180 days prior' often in design-change clauses, not force majeure. Output JSON only."
    )
    try:
        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat
            raw = call_bedrock_chat(prompt=prompt, system_message=EVIDENCE_VALIDATION_SYSTEM)
        else:
            from .local_llm import call_local_chat
            raw = call_local_chat(
                prompt=prompt,
                system_message=EVIDENCE_VALIDATION_SYSTEM,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CLASSIFY", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CLASSIFY", 0.0),
            )
        text = (raw or "").strip()
        obj = None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*\"belongs_to_clause\"[^{}]*\}", text)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        if isinstance(obj, dict) and "belongs_to_clause" in obj:
            belongs = bool(obj.get("belongs_to_clause", True))
            confidence = str(obj.get("confidence", "medium")).lower()
            # Soften: only reject when we're confident it's wrong
            if belongs:
                if agent_config.DEBUG_AGENT:
                    logger.info("Evidence validation: clause=%s belongs=True conf=%s", clause[:40], confidence)
                return True
            if confidence == "high":
                if agent_config.DEBUG_AGENT:
                    logger.info("Evidence validation: clause=%s belongs=False conf=high -> REJECT", clause[:40])
                return False
            # low/medium confidence + belongs=False -> allow through (uncertain, don't block)
            if agent_config.DEBUG_AGENT:
                logger.info("Evidence validation: clause=%s belongs=False conf=%s -> ALLOW (uncertain)", clause[:40], confidence)
            return True
        return True
    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Evidence validation failed: %s", exc)
        return True


COMMENT_GENERATION_SYSTEM_PROMPT = (
    "You are a legal review assistant. Generate a concise Word margin comment (max 150 chars) "
    "that explains the specific deviation and why the edit aligns with company policy."
)


def generate_comment_for_edit(
    original_text: str,
    edited_text: str,
    clause_name: str,
    risk_level: str,
    gb_ideal: str,
) -> str:
    """Use the LLM to generate a short, specific margin comment for an edit.

    Format: 'Current: [1-line summary]. Change: [what was changed]. Reason: [why it aligns with policy].'
    Returns empty string on failure; caller will fall back to generic comment.
    """
    original_text = (original_text or "").strip()
    edited_text = (edited_text or "").strip()
    if not original_text or not edited_text or original_text == edited_text:
        return ""
    if not (gb_ideal or "").strip():
        return ""
    try:
        user_prompt = (
            f"Clause: {clause_name or 'Unnamed'}\n"
            f"Risk level: {risk_level or 'Unknown'}\n"
            f"Company ideal: {gb_ideal.strip()}\n\n"
            f"Original: {original_text[:300]}{'...' if len(original_text) > 300 else ''}\n\n"
            f"Edited: {edited_text[:300]}{'...' if len(edited_text) > 300 else ''}\n\n"
            "Generate a comment in this format: "
            "Current: [1-line summary]. Change: [what was changed]. Reason: [why it aligns with policy]. "
            "Max 150 characters total."
        )
        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat
            raw = call_bedrock_chat(
                prompt=user_prompt,
                system_message=COMMENT_GENERATION_SYSTEM_PROMPT,
            )
        else:
            from .local_llm import call_local_chat
            raw = call_local_chat(
                prompt=user_prompt,
                system_message=COMMENT_GENERATION_SYSTEM_PROMPT,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_EDITING", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_COMMENTS", 0.1),
            )
        text = (raw or "").strip()
        if not text or len(text) > 200:
            return ""
        return text[:150] if len(text) > 150 else text
    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Comment generation failed: %s", exc)
        return ""
