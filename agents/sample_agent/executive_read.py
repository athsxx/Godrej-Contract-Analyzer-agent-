"""Bounded executive-read JSON: risk vs ideal, gap, proposal, clearance, anchored to paragraph ids."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from . import config as agent_config
from .local_llm import call_local_chat
from .paragraph_index import (
    build_paragraph_index,
    paragraph_catalog_for_prompt,
    primary_text_fingerprint,
)

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _match_paragraph_ids(evidence: str, paragraphs: List[Dict[str, Any]], *, limit: int = 4) -> List[str]:
    needle = (evidence or "").lower().strip()
    if not needle or not paragraphs:
        return [paragraphs[0]["paragraph_id"]] if paragraphs else []
    # Prefer longest substring match against paragraph bodies.
    hits: List[str] = []
    for p in paragraphs:
        body = str(p.get("text") or "").lower()
        if len(needle) >= 12 and needle[:120] in body:
            hits.append(str(p["paragraph_id"]))
        elif len(needle) >= 6 and needle[:40] in body:
            hits.append(str(p["paragraph_id"]))
    if hits:
        return hits[:limit]
    return [paragraphs[0]["paragraph_id"]]


def _deterministic_executive_read(
    clause_table: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
    *,
    fingerprint: str,
) -> Dict[str, Any]:
    """No-LLM synthesis from clause rows (used on failure or when LLM disabled)."""
    items: List[Dict[str, Any]] = []
    for row in clause_table or []:
        name = str(row.get("clause_name") or "").strip() or "Clause"
        ev = str(row.get("evidence_snippet") or "").strip()
        cited = _match_paragraph_ids(ev, paragraphs)
        items.append(
            {
                "clause_name": name,
                "risk_overview": f"Risk {row.get('risk_level', '')}: {str(row.get('risk_rationale') or '')[:400]}".strip(),
                "gap_vs_ideal_position": (
                    f"Uploaded position vs GB ideal: compare '{str(row.get('uploaded_position') or '')[:200]}' "
                    f"with ideal '{str(row.get('gb_ideal_position') or '')[:200]}'."
                ),
                "proposal_direction": str(row.get("mitigation_recommendation") or "")[:500],
                "clearance_path": str(row.get("approval_path") or "Legal review."),
                "cited_paragraph_ids": cited,
            }
        )
    n_red = sum(1 for r in clause_table or [] if str(r.get("risk_level") or "").strip().lower() == "red")
    crux = (
        f"POC clause scan: {len(clause_table or [])} positions; "
        f"{n_red} high-severity (Red) rows require Legal clearance before commitment."
    )
    return {
        "contract_crux": crux,
        "executive_items": items,
        "paragraph_index_fingerprint": fingerprint,
        "source": "deterministic_fallback",
    }


def generate_executive_read_bundle(
    *,
    clause_table: List[Dict[str, Any]],
    primary_text: str,
    supporting_summary: str = "",
    knowledge_excerpt: str = "",
) -> Dict[str, Any]:
    """Return ``{"executive_read": dict, "paragraph_index": list}``."""
    text_body = (primary_text or "").strip()
    paragraphs = build_paragraph_index(text_body)
    fingerprint = primary_text_fingerprint(text_body)
    valid_ids = {str(p["paragraph_id"]) for p in paragraphs}

    max_rows = max(1, int(getattr(agent_config, "EXECUTIVE_READ_MAX_CLAUSES", 10)))
    rows_slice = list(clause_table or [])[:max_rows]

    if not rows_slice:
        return {
            "executive_read": {
                "contract_crux": "No clause rows to summarize.",
                "executive_items": [],
                "paragraph_index_fingerprint": fingerprint,
                "source": "empty",
            },
            "paragraph_index": paragraphs[:200],
        }

    use_llm = getattr(agent_config, "ENABLE_EXECUTIVE_READ", True) and getattr(
        agent_config, "ENABLE_EXECUTIVE_READ_LLM", True
    )

    if not use_llm:
        return {
            "executive_read": _deterministic_executive_read(rows_slice, paragraphs, fingerprint=fingerprint),
            "paragraph_index": paragraphs[:200],
        }

    compact_rows: List[str] = []
    for row in rows_slice:
        compact_rows.append(
            json.dumps(
                {
                    "clause_name": row.get("clause_name"),
                    "detected": row.get("detected"),
                    "risk_level": row.get("risk_level"),
                    "uploaded_position": (str(row.get("uploaded_position") or "")[:400]),
                    "gb_ideal_position": (str(row.get("gb_ideal_position") or "")[:400]),
                    "evidence_snippet": (str(row.get("evidence_snippet") or "")[:320]),
                    "mitigation_recommendation": (str(row.get("mitigation_recommendation") or "")[:320]),
                    "approval_path": (str(row.get("approval_path") or "")[:200]),
                },
                ensure_ascii=False,
            )
        )

    catalog = paragraph_catalog_for_prompt(paragraphs, max_blocks=40)
    allowed_sample = ", ".join(sorted(valid_ids)[:60])

    prompt = f"""You produce a tight executive legal read for internal stakeholders.

Primary contract paragraph index fingerprint: {fingerprint}
You may cite ONLY paragraph_id values that exist in the catalog below. Use 0–4 ids per item.

Paragraph catalog (id: preview):
{catalog}

Clause rows (JSON lines, one object per line):
{chr(10).join(compact_rows)}

Supporting-doc hints (may be empty):
{(supporting_summary or '')[:3500]}

POC knowledge excerpt (reference only, do not quote verbatim as contract text):
{(knowledge_excerpt or '')[:4500]}

Return STRICT JSON only, with this shape:
{{
  "contract_crux": "2–4 sentences on overall posture and top risks",
  "executive_items": [
    {{
      "clause_name": "exact clause_name from input rows",
      "risk_overview": "short",
      "gap_vs_ideal_position": "short",
      "proposal_direction": "negotiation / drafting direction",
      "clearance_path": "who approves / what evidence is needed",
      "cited_paragraph_ids": ["p-0"]
    }}
  ]
}}

Rules:
- At most {len(rows_slice)} items; one row may be skipped if duplicate.
- cited_paragraph_ids must be a subset of known ids; allowed sample: {allowed_sample}
- JSON only, no markdown fences.
""".strip()

    system_message = (
        "You are a senior aerospace supply-chain counsel assistant. "
        "Be precise, conservative, and JSON-only."
    )

    data: Optional[dict] = None
    try:
        raw = call_local_chat(
            prompt,
            system_message=system_message,
            model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CHAT", None) or agent_config.LOCAL_LLM_MODEL,
            temperature=min(float(agent_config.LOCAL_LLM_TEMPERATURE), 0.15),
            top_p=min(float(agent_config.LOCAL_LLM_TOP_P), 0.35),
            max_tokens=min(int(agent_config.LOCAL_LLM_MAX_TOKENS), 1800),
        )
        data = _extract_json_object(raw)
    except Exception as exc:
        if agent_config.DEBUG_AGENT:
            logger.warning("Executive read LLM failed: %s", exc)

    if not isinstance(data, dict):
        data = _deterministic_executive_read(rows_slice, paragraphs, fingerprint=fingerprint)
    else:
        items = data.get("executive_items")
        if not isinstance(items, list):
            items = []
        cleaned: List[Dict[str, Any]] = []
        for it in items[:max_rows]:
            if not isinstance(it, dict):
                continue
            cited_raw = it.get("cited_paragraph_ids") or []
            if isinstance(cited_raw, str):
                cited_raw = [cited_raw]
            cited = [str(x) for x in cited_raw if str(x) in valid_ids][:5]
            if not cited and paragraphs:
                cited = _match_paragraph_ids(str(it.get("clause_name") or ""), paragraphs, limit=2)
            cleaned.append(
                {
                    "clause_name": str(it.get("clause_name") or "").strip(),
                    "risk_overview": str(it.get("risk_overview") or "")[:1200],
                    "gap_vs_ideal_position": str(it.get("gap_vs_ideal_position") or "")[:1200],
                    "proposal_direction": str(it.get("proposal_direction") or "")[:1200],
                    "clearance_path": str(it.get("clearance_path") or "")[:800],
                    "cited_paragraph_ids": cited,
                }
            )
        data = {
            "contract_crux": str(data.get("contract_crux") or "")[:2000],
            "executive_items": cleaned,
            "paragraph_index_fingerprint": fingerprint,
            "source": "llm",
        }
        if not cleaned:
            data = _deterministic_executive_read(rows_slice, paragraphs, fingerprint=fingerprint)

    return {"executive_read": data, "paragraph_index": paragraphs[:200]}
