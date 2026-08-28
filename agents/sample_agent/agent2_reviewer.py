# agent2_reviewer.py
# Purpose: Build Risk Analysis & Details (RAG table) from Agent 1 output only.

import os
import re
import json
import time
from functools import lru_cache
from pathlib import Path
import boto3
from typing import List, Dict, Any
from botocore.exceptions import ClientError

# ------------------------------
# Output contract
# ------------------------------
HEADER = "## Risk Analysis and Details"
TABLE_HEADER = "| Clause | Risk | RAG | Rationale | Mitigation | Evidence/Location |"

# ------------------------------
# Size guards
# ------------------------------
MAX_TOKENS = 1200
MAX_FIELD = 500
# Structured clause table: allow longer legal text per cell (Agent 1 already concise).
MAX_FIELD_STRUCTURED = 1400
MAX_ROWS = 40

CLAUSE_ALIASES = {
    "cancellation clause early termination fee": "cancellation termination",
    "po amendment": "po amendments",
}

CLAUSE_HEADER_RE = re.compile(r"^##\s*Clause\s*\d+\s*:\s*(.+)$", re.MULTILINE)
REQ_RE = re.compile(r"\*\*Requirement:\*\*\s*(.+?)(?=\n\*\*Rationale:\*\*|\Z)", re.DOTALL)
RAT_RE = re.compile(r"\*\*Rationale:\*\*\s*(.+?)(?=\n\*\*Mitigation Strategy:\*\*|\Z)", re.DOTALL)
MIT_RE = re.compile(r"\*\*Mitigation Strategy:\*\*\s*(.+?)(?=\n---|\Z)", re.DOTALL)

def _resolve_rationale_mitigation_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "rationale_mitigation.txt",
        Path.cwd() / "geg_guru" / "agents" / "ped" / "rationale_mitigation.txt",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return here / "rationale_mitigation.txt"

RATIONALE_MITIGATION_PATH = _resolve_rationale_mitigation_path()

aws_region = os.getenv("AWS_REGION", "ap-south-1")
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
bedrock_model_id = os.getenv("BEDROCK_MODEL_ID", "")



bedrock = None
if bedrock_model_id:
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=aws_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

# ------------------------------
# Bedrock helpers
# ------------------------------
def _parse_converse_text(resp: dict) -> str:
    try:
        parts = resp["output"]["message"]["content"]
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        return "".join(texts).strip()
    except Exception:
        return ""

def call_bedrock_chat(user_prompt: str, system_message: str | None = None) -> str:
    if bedrock is None or not bedrock_model_id:
        try:
            from . import config as agent_config
            from .local_llm import call_local_chat

            return call_local_chat(
                user_prompt,
                system_message=system_message,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CHAT", None),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CHAT", agent_config.LOCAL_LLM_TEMPERATURE),
            )
        except Exception:
            return ""
    content = f"[System]\n{system_message}\n\n[User]\n{user_prompt}" if system_message else user_prompt
    try:
        resp = bedrock.converse(
            modelId=bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": content}]}],
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.2, "topP": 0.9},
        )
        text = _parse_converse_text(resp)
        if text:
            return text
    except Exception:
        pass
    # Fallback: use Anthropic schema for inference profiles / Sonnet; keep legacy body for older models.
    is_inference_profile = "inference-profile" in bedrock_model_id or "sonnet-4-5" in bedrock_model_id
    is_anthropic = "anthropic" in bedrock_model_id
    if is_inference_profile or is_anthropic:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": [{"role": "user", "content": [{"type": "text", "text": content}]}],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.2,
        }
        if system_message:
            body["system"] = system_message
        resp = bedrock.invoke_model(
            modelId=bedrock_model_id, contentType="application/json", accept="application/json", body=json.dumps(body)
        )
        data = json.loads(resp["body"].read().decode("utf-8"))
        blocks = data.get("content") or []
        texts = [b.get("text", "") for b in blocks if isinstance(b, dict)]
        return "".join(texts).strip() or str(data)
    body = {"inputText": content, "textGenerationConfig": {"maxTokenCount": MAX_TOKENS, "temperature": 0.2, "topP": 0.9}}
    resp = bedrock.invoke_model(
        modelId=bedrock_model_id, contentType="application/json", accept="application/json", body=json.dumps(body)
    )
    data = json.loads(resp["body"].read().decode("utf-8"))
    results = data.get("results") or []
    return (results[0].get("outputText", "") if results else "") or str(data.get("outputText") or "").strip()

# ------------------------------
# Utilities
# ------------------------------
def _clean(s: str, max_len: int = MAX_FIELD) -> str:
    s = (s or "").strip()
    return (s[:max_len] + "…") if len(s) > max_len else s


def _format_cell_long(s: str) -> str:
    cleaned = (s or "").strip()
    if not cleaned:
        return "-"
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    limit = MAX_FIELD_STRUCTURED
    return (cleaned[:limit] + "…") if len(cleaned) > limit else cleaned

def _rag_from_status(met_text: str) -> str:
    t = (met_text or "").lower()
    if t.startswith("no"):
        return "🟥"
    if t.startswith("partial") or t.startswith("na"):
        return "🟧"
    return "🟩"

def _normalize_clause_key(text: str) -> str:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("&", "and")
    cleaned = cleaned.replace("â€™", "'").replace("’", "'").replace("‘", "'")
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = []
    for tok in cleaned.split():
        if len(tok) > 3 and tok.endswith("s"):
            tok = tok[:-1]
        tokens.append(tok)
    return " ".join(tokens)

def _clause_name_from_label(label: str) -> str:
    if not label:
        return ""
    match = re.match(r"\s*\d+\.\s*(.+)", label)
    return match.group(1).strip() if match else label.strip()

def _extract_block(section: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(section or "")
    if not match:
        return ""
    block = match.group(1).strip()
    block = re.sub(r"\s*\n\s*", " ", block)
    return re.sub(r"\s+", " ", block).strip()

@lru_cache(maxsize=1)
def _load_rationale_mitigation_map() -> dict[str, dict[str, str]]:
    if not RATIONALE_MITIGATION_PATH.exists():
        return {}
    try:
        text = RATIONALE_MITIGATION_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    matches = list(CLAUSE_HEADER_RE.finditer(text))
    if not matches:
        return {}
    mapping: dict[str, dict[str, str]] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[start:end]
        clause_name = match.group(1).strip()
        rationale = _extract_block(section, RAT_RE)
        mitigation = _extract_block(section, MIT_RE)
        mapping[_normalize_clause_key(clause_name)] = {
            "rationale": rationale,
            "mitigation": mitigation,
        }
    return mapping

def _lookup_rationale_mitigation(clause_label: str, requirement: str) -> tuple[str, str]:
    mapping = _load_rationale_mitigation_map()
    if not mapping:
        return "", ""
    clause_name = _clause_name_from_label(clause_label)
    clause_key = _normalize_clause_key(clause_name)
    req_key = _normalize_clause_key(requirement)

    if "governing law" in clause_key and "arbitration" in clause_key:
        law_key = _normalize_clause_key("Governing Law")
        arb_key = _normalize_clause_key("Arbitration")
        if req_key.startswith("law") and law_key in mapping:
            hit = mapping[law_key]
            return hit.get("rationale", ""), hit.get("mitigation", "")
        if req_key.startswith("arbitration") and arb_key in mapping:
            hit = mapping[arb_key]
            return hit.get("rationale", ""), hit.get("mitigation", "")
        hits = [mapping[k] for k in (law_key, arb_key) if k in mapping]
        if hits:
            rationale = "\n".join([h.get("rationale", "") for h in hits if h.get("rationale")])
            mitigation = "\n".join([h.get("mitigation", "") for h in hits if h.get("mitigation")])
            return rationale, mitigation

    clause_key = CLAUSE_ALIASES.get(clause_key, clause_key)
    hit = mapping.get(clause_key)
    if hit:
        return hit.get("rationale", ""), hit.get("mitigation", "")

    clause_tokens = set(clause_key.split())
    best_key = ""
    best_score = 0
    for key in mapping:
        score = len(clause_tokens & set(key.split()))
        if score > best_score:
            best_score = score
            best_key = key
    if best_key:
        hit = mapping[best_key]
        return hit.get("rationale", ""), hit.get("mitigation", "")
    return "", ""

def _format_cell(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "-"
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return _clean(cleaned)

def _contextualize_text(clause: str, requirement: str, text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    req = (requirement or "").strip()
    if not req:
        return cleaned
    if req.lower() in cleaned.lower():
        return cleaned
    clause_label = (clause or "").strip()
    prefix = f"For {clause_label} - {req}, " if clause_label else f"For {req}, "
    if cleaned and cleaned[0].isupper():
        cleaned = cleaned[0].lower() + cleaned[1:]
    return f"{prefix}{cleaned}"

def _parse_summary_table(agent1_md: str) -> List[Dict[str, str]]:
    """
    Extract rows from the first markdown table in Agent 1 output.
    Returns list of dicts: {clause, requirement, met, references}
    """
    lines = (agent1_md or "").splitlines()
    # find header + sep lines
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and "Clause" in ln and "Requirement" in ln and "Met" in ln:
            header_idx = i
            break
    if header_idx is None or header_idx + 1 >= len(lines):
        return []
    data = []
    for ln in lines[header_idx+2:]:
        if not ln.strip().startswith("|"):
            break
        parts = [p.strip() for p in ln.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue
        if len(parts) >= 4:
            clause, requirement, met, references = parts[:4]
        else:
            clause, requirement, met = parts[:3]
            references = ""
        data.append(
            {
                "clause": clause,
                "requirement": requirement,
                "met": met,
                "references": references,
            }
        )
    return data

def _risky_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    risky = []
    for r in rows:
        met = (r.get("met") or "").strip()
        low = met.lower()
        if low.startswith("yes") and "partial" not in low and "na" not in low:
            continue
        # Evidence extraction: prefer explicit Ref:, fallback to bracket tags
        ev = (r.get("references") or "").strip()
        if not ev:
            ref_match = re.search(r"\bRef:\s*([^)]+)\)?", met)
            if ref_match:
                ev = ref_match.group(1).strip()
            else:
                ev_match = re.findall(r"\[[^\]]+\]", met)
                if ev_match:
                    ev = " ".join(ev_match)
        # Rationale: text after dash, strip trailing Ref: citation
        rationale = ""
        if "–" in met:
            rationale = met.split("–", 1)[1].strip()
        elif "-" in met:
            rationale = met.split("-", 1)[1].strip()
        if rationale:
            rationale = re.sub(r"\(Ref:\s*[^)]+\)", "", rationale).strip()
        risky.append({
            "clause": _clean(r.get("clause")),
            "risk": _clean(r.get("requirement")),
            "status": _clean(met.split("–",1)[0].split("-",1)[0].strip()),
            "evidence": _clean(ev),
            "rationale_seed": _clean(rationale),
            "rag": _rag_from_status(met),
        })
    return risky[:MAX_ROWS]

def _sanitize_table_cell(val: str) -> str:
    """Avoid breaking markdown pipes inside table cells."""
    sm = MAX_FIELD_STRUCTURED
    s = _clean(val or "", max_len=sm).replace("|", "∣")
    return s


def _risky_clause_table_rows(clause_table: List[Dict[str, str]]) -> List[tuple[int, Dict[str, str]]]:
    """Same risk rule as mitigation checklist: drop only Green + Yes aligned."""
    out: List[tuple[int, Dict[str, str]]] = []
    for idx, row in enumerate(clause_table or [], start=1):
        risk_level = (row.get("risk_level") or "").strip()
        detected = (row.get("detected") or "").strip()
        if risk_level == "Green" and detected == "Yes":
            continue
        out.append((idx, row))
    return out


def _rag_indicator_from_levels(risk_level: str, detected: str) -> str:
    rl = (risk_level or "").strip()
    dc = (detected or "").strip()
    if rl == "Green" and dc == "Yes":
        return "🟩"
    if rl == "Red":
        return "🟥"
    return "🟧"


def generate_risk_mitigation_from_clause_table(
    clause_table: List[Dict[str, str]],
    *,
    agent1_output: str = "",
    po_text: str = "",
    terms_text: str = "",
) -> str:
    """
    Build the Agent 2 RAG table directly from Agent 1 structured rows.

    This is the primary path: no fragile markdown round-trip, full use of
    risk_rationale, mitigation_recommendation, and evidence_snippet from Agent 1.
    Optional rationale_mitigation.txt entries fill gaps when a field is empty.
    """
    risky = _risky_clause_table_rows(clause_table)[:MAX_ROWS]
    if not risky:
        return f"""{HEADER}

{TABLE_HEADER}
|--------|------|-----|-----------|------------|-------------------|
| No risks identified | - | 🟩 | All reviewed items compliant | - | - |
"""

    lines = [HEADER, "", TABLE_HEADER, "|--------|------|-----|-----------|------------|-------------------|"]
    for idx, row in risky:
        clause_name = (row.get("clause_name") or "").strip()
        clause_label = f"{idx}. {clause_name}".strip() or str(idx)
        requirement = (row.get("gb_ideal_position") or "").strip()

        rationale = (row.get("risk_rationale") or "").strip()
        mitigation = (row.get("mitigation_recommendation") or "").strip()
        if not rationale or not mitigation:
            lr, lm = _lookup_rationale_mitigation(clause_label, requirement)
            if not rationale:
                rationale = lr
            if not mitigation:
                mitigation = lm

        risk_level = (row.get("risk_level") or "Amber").strip()
        detected = (row.get("detected") or "Unclear").strip()
        rag = _rag_indicator_from_levels(risk_level, detected)

        evidence = (
            (row.get("evidence_snippet") or "").strip()
            or (row.get("uploaded_position") or "").strip()
            or (row.get("knowledge_reference") or "").strip()
        )

        rationale = _contextualize_text(clause_label, requirement, rationale)
        mitigation = _contextualize_text(clause_label, requirement, mitigation)

        lines.append(
            "| {clause} | {risk} | {rag} | {rationale} | {mitigation} | {evidence} |".format(
                clause=_sanitize_table_cell(clause_label),
                risk=_sanitize_table_cell(requirement),
                rag=rag,
                rationale=_sanitize_table_cell(_format_cell_long(rationale)),
                mitigation=_sanitize_table_cell(_format_cell_long(mitigation)),
                evidence=_sanitize_table_cell(_format_cell_long(evidence)),
            )
        )
    return "\n".join(lines)


# ------------------------------
# Main
# ------------------------------
def generate_risk_mitigation(
    agent1_output: str,
    po_text: str,
    terms_text: str,
    *,
    clause_table: List[Dict[str, str]] | None = None,
) -> str:
    """
    Build a single RAG table based on Agent 1 output.

    Prefer passing ``clause_table`` (structured); otherwise falls back to parsing
    Agent 1 markdown (legacy, more fragile).
    """
    if clause_table:
        return generate_risk_mitigation_from_clause_table(
            clause_table,
            agent1_output=agent1_output,
            po_text=po_text,
            terms_text=terms_text,
        )

    rows = _parse_summary_table(agent1_output)
    risky = _risky_rows(rows)

    if not risky:
        return f"""{HEADER}

{TABLE_HEADER}
|--------|------|-----|-----------|------------|-------------------|
| No risks identified | - | 🟩 | All reviewed items compliant | - | - |
"""

    lines = [HEADER, "", TABLE_HEADER, "|--------|------|-----|-----------|------------|-------------------|"]
    for r in risky:
        clause_label = r.get("clause", "")
        requirement = r.get("risk", "")
        rationale, mitigation = _lookup_rationale_mitigation(clause_label, requirement)
        if not rationale:
            rationale = r.get("rationale_seed", "") or ""
        rationale = _contextualize_text(clause_label, requirement, rationale)
        mitigation = _contextualize_text(clause_label, requirement, mitigation)
        lines.append(
            "| {clause} | {risk} | {rag} | {rationale} | {mitigation} | {evidence} |".format(
                clause=clause_label,
                risk=requirement,
                rag=r.get("rag", ""),
                rationale=_format_cell(rationale),
                mitigation=_format_cell(mitigation),
                evidence=_format_cell(r.get("evidence", "")),
            )
        )
    return "\n".join(lines)
