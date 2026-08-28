"""Agent 4: Post-redline verification.

Verifies that redline edits (original_text → edited_text) are semantically and
contextually appropriate. Non-blocking: always returns a result; on error defaults
to verdict "pass".
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import config as agent_config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a legal contract review assistant. Assess whether a proposed edit to "
    "contract text fits semantically and contextually.\n\n"
    "FLAG only when there is a CLEAR problem:\n"
    "- The edit introduces a completely different topic or clause (e.g. LD language in a dispute paragraph).\n"
    "- The edit fundamentally changes the paragraph's meaning in a dangerous way.\n"
    "- The edit is grammatically broken or incoherent.\n\n"
    "PASS (do NOT flag) when:\n"
    "- The edit is imperfect but acceptable (minor style, flow, or wording choices).\n"
    "- The edit aligns the paragraph with the clause topic even if not perfect.\n"
    "- You are uncertain; default to pass.\n\n"
    "Output ONLY valid JSON: {\"verdict\":\"pass\" or \"flag\", "
    "\"reason\":\"...\", \"suggestion\":\"...\"}."
)


def _build_user_prompt(
    original_text: str,
    edited_text: str,
    clause_name: str,
    surrounding_context: str,
    gb_ideal: str,
) -> str:
    return f"""
Clause: {clause_name}
GB ideal: {gb_ideal}

Original paragraph: {original_text}
Edited paragraph: {edited_text}

Surrounding context (before/after): {surrounding_context}

Assess the edit. Output JSON only.
""".strip()


def _extract_json_from_response(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response. Tries json.loads first, then regex."""
    if not text or not text.strip():
        return None

    # Try parsing the whole response as JSON
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and "verdict" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # Extract content from ```json ... ``` code block if present
    code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_block:
        try:
            obj = json.loads(code_block.group(1).strip())
            if isinstance(obj, dict) and "verdict" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    # Find the first {...} with verdict (brace-balanced)
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 1
            start = i
            found = False
            for j in range(i + 1, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        snippet = text[start : j + 1]
                        try:
                            obj = json.loads(snippet)
                            if isinstance(obj, dict) and "verdict" in obj:
                                return obj
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        found = True
                        break
            if not found:
                i += 1
        else:
            i += 1

    return None


def _normalize_verdict(obj: dict[str, Any]) -> dict[str, str]:
    """Extract and normalize verdict, reason, suggestion. Default to pass."""
    verdict = str(obj.get("verdict", "pass")).strip().lower()
    if verdict not in ("pass", "flag"):
        verdict = "pass"
    reason = str(obj.get("reason", "")).strip()
    suggestion = str(obj.get("suggestion", "")).strip()
    return {"verdict": verdict, "reason": reason, "suggestion": suggestion}


def verify_redline_edit(
    original_text: str,
    edited_text: str,
    clause_name: str,
    surrounding_context: str,
    gb_ideal: str = "",
) -> dict[str, str]:
    """
    Verify that a redline edit is semantically and contextually appropriate.

    Returns:
        dict with keys: "verdict" ("pass" | "flag"), "reason" (str), "suggestion" (str)

    Non-blocking: on any failure (LLM error, parse error), returns {"verdict": "pass", "reason": "", "suggestion": ""}.
    """
    default_pass = {"verdict": "pass", "reason": "", "suggestion": ""}

    try:
        user_prompt = _build_user_prompt(
            original_text=original_text,
            edited_text=edited_text,
            clause_name=clause_name,
            surrounding_context=surrounding_context,
            gb_ideal=gb_ideal or "",
        )

        raw_response: str

        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat

            raw_response = call_bedrock_chat(
                prompt=user_prompt,
                system_message=SYSTEM_PROMPT,
            )
        else:
            from .local_llm import call_local_chat

            raw_response = call_local_chat(
                prompt=user_prompt,
                system_message=SYSTEM_PROMPT,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CLASSIFY", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CLASSIFY", 0.0),
            )

        parsed = _extract_json_from_response(raw_response)
        if parsed is None:
            if agent_config.DEBUG_AGENT:
                logger.warning("Agent4: could not parse JSON from response: %s", raw_response[:300])
            return default_pass

        return _normalize_verdict(parsed)

    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Agent4 verify_redline_edit failed (defaulting to pass): %s", exc)
        return default_pass
