"""Human-in-the-loop (HITL) sidecar pipeline for contract findings (parallel to UI checkbox HITL).

Stages:

1. **deterministic_pass** — Regex / structure over primary text (section headings).
2. **llm_suggest_pass** — Optional Ollama JSON labels when ``enable_llm_suggestions`` is true
   and ``ENABLE_HITL_PIPELINE_LLM`` is set in config (checked by caller).
3. **verify_pass** — Dedupe and cap findings (no ML).
4. **build_comment_specs** — Map findings to Word-style comment dicts (paragraph index is best-effort).

This does **not** train the model: accept/reject in the product is **not** written back into
weights, RLHF, or automatic rule mutation. See project docs for export-level HITL (session
``redline_accepted_clause_ids``).

This module avoids importing ``chat_agent`` at import time to limit circular imports.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Mapping, MutableMapping, Sequence

logger = logging.getLogger(__name__)


def deterministic_pass(document_context: Mapping[str, Any] | None = None) -> List[MutableMapping[str, Any]]:
    """Stage 1: fast structure signals over contract text."""
    ctx = dict(document_context or {})
    text = str(ctx.get("primary_text") or ctx.get("full_text") or "")[:200_000]
    findings: List[MutableMapping[str, Any]] = []
    if not text.strip():
        return findings
    for m in re.finditer(
        r"(?m)^(?:Article|Section|Clause)\s+[\w.\-]+[^\n]{0,160}",
        text,
    ):
        findings.append(
            {
                "kind": "section_heading",
                "text": m.group(0).strip(),
                "start": m.start(),
                "end": m.end(),
                "source": "deterministic_pass",
            }
        )
    return findings[:200]


def _parse_llm_suggestion_json(raw: str) -> List[MutableMapping[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("suggestions") or data.get("rows") or []
    if not isinstance(items, list):
        return []
    out: List[MutableMapping[str, Any]] = []
    for item in items[:12]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("title") or "").strip()
        detail = str(item.get("detail") or item.get("description") or "").strip()
        if not label and not detail:
            continue
        out.append(
            {
                "kind": "llm_suggestion",
                "label": label or "Suggestion",
                "detail": detail or label,
                "source": "llm_suggest_pass",
            }
        )
    return out


def llm_suggest_pass(document_context: Mapping[str, Any] | None = None) -> List[MutableMapping[str, Any]]:
    """Stage 2: optional JSON suggestions from local LLM (bounded snippet)."""
    ctx = dict(document_context or {})
    if not ctx.get("enable_llm_suggestions"):
        return []
    snippet = str(ctx.get("primary_text") or ctx.get("full_text") or "")[:8000]
    if not snippet.strip():
        return []
    try:
        from . import config as agent_config
        from .local_llm import call_local_chat
    except Exception as exc:  # pragma: no cover - import surface
        logger.debug("llm_suggest_pass import failed: %s", exc)
        return []
    system = (
        "Return ONLY valid JSON with this shape: "
        '{"suggestions":[{"label":"short label","detail":"one sentence"}]} — no markdown fences.'
    )
    user = (
        "From this contract excerpt, emit up to 5 short risk or review labels useful for Legal triage.\n\n"
        + snippet
    )
    try:
        raw = call_local_chat(
            user,
            system_message=system,
            model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CLASSIFY", None)
            or getattr(agent_config, "LOCAL_LLM_MODEL", ""),
            temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CLASSIFY", 0.0),
            max_tokens=min(1024, getattr(agent_config, "LOCAL_LLM_MAX_TOKENS", 2048)),
        )
    except Exception as exc:
        logger.info("llm_suggest_pass LLM call skipped/failed: %s", exc)
        return []
    return _parse_llm_suggestion_json(raw)


def verify_pass(findings: Sequence[Any]) -> List[MutableMapping[str, Any]]:
    """Stage 3: deterministic dedupe and cap."""
    seen: set[tuple[str, str]] = set()
    out: List[MutableMapping[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind") or "unknown")
        key_text = str(f.get("text") or f.get("label") or f.get("detail") or "")[:240]
        key = (kind, key_text)
        if not key_text or key in seen:
            continue
        seen.add(key)
        out.append(dict(f))
    return out[:120]


def build_comment_specs(verified_findings: Sequence[Any]) -> List[MutableMapping[str, Any]]:
    """Stage 4: map findings to Word-style comment dicts (best-effort paragraph index)."""
    specs: List[MutableMapping[str, Any]] = []
    for i, f in enumerate(verified_findings):
        if not isinstance(f, dict):
            continue
        body = str(f.get("detail") or f.get("text") or f.get("label") or "").strip()
        if not body:
            continue
        quote = str(f.get("text") or f.get("label") or "")[:400]
        specs.append(
            {
                "paragraph_index": min(i, 5000),
                "body_text": body[:3500],
                "quote": quote,
                "finding_kind": str(f.get("kind") or ""),
            }
        )
    return specs[:80]
