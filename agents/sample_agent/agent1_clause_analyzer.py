# agent1_clause_analyzer.py

from __future__ import annotations

import os
import re
import time
import json
import math
import base64
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence, Tuple

from django.conf import settings
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

aws_region = os.getenv("AWS_REGION", "ap-south-1")
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
bedrock_model_id = os.getenv("BEDROCK_MODEL_ID", "")

try:
    from .utils_doc_loader import render_pdf_images
except Exception:  # pragma: no cover - optional import
    try:
        from utils_doc_loader import render_pdf_images  # type: ignore
    except Exception:  # pragma: no cover - optional import
        render_pdf_images = None

# ---------------------------------
# Validation patterns
# ---------------------------------
TABLE_HEADER_PATTERN = r"\|\s*Clause\s*\|"
CLAUSE_ROW_PATTERN = r"\|\s*\d+\.\s+"
RISKS_SECTION_HEADER_PATTERN = r"⚠️\s*Risks Identified"

# Fixed 14 clauses in order for sanity
CLAUSE_NAMES = [
    "Payment Terms",
    "Bank Guarantees",
    "Liquidated Damages (LD)",
    "Guarantee",
    "Force Majeure",
    "Storage",
    "Defect Liability",
    "Cancellation Clause",
    "Suspension",
    "PO Amendment",
    "Governing Law & Arbitration",
    "Insurance",
    "Limitation of Liability",
    "Consequential Damages",
]

DOC_SECTIONS = [
    ("PO", "Purchase Order (primary reference)"),
    ("SPC", "Special Purchase Conditions (secondary fallback)"),
    ("GPC", "General Purchase Conditions (tertiary fallback)"),
    ("TERMS", "Terms & Conditions / other attachments (lowest priority)"),
]
DOC_PRIORITY = {label: idx for idx, (label, _) in enumerate(DOC_SECTIONS)}

SECTION_HINT_RE = re.compile(r"(?:section|clause)\s*([0-9]+(?:[.\-][0-9]+)*)", re.IGNORECASE)
PAGE_HINT_RE = re.compile(r"(?:page|p\.|pg)\s*([0-9]+)", re.IGNORECASE)
PAGE_MARKER_RE = re.compile(r"\bPAGE\s+([0-9]+)\b", re.IGNORECASE)



bedrock = None
if bedrock_model_id:
    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=aws_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

# ---------------------------------
# Model helpers
# ---------------------------------
def _is_anthropic(model_id: str) -> bool:
    return "anthropic" in model_id

def _is_llama_like(model_id: str) -> bool:
    return any(x in model_id for x in ("meta.llama", "llama"))

def _is_nova(model_id: str) -> bool:
    return "amazon.nova" in model_id

def _parse_converse_text(resp: dict) -> str:
    try:
        parts = resp["output"]["message"]["content"]
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        return "".join(texts).strip()
    except Exception:
        return ""

def _invoke_anthropic(content: str, system_message: str | None, image_blocks: list[dict] | None = None) -> str:
    blocks = [{"type": "text", "text": content}]
    if image_blocks:
        blocks.extend(image_blocks)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "messages": [{"role": "user", "content": blocks}],
        "max_tokens": 5000,
        "temperature": 0.2,
    }
    # Newer Anthropic inference profiles reject both temperature and top_p together; keep top_p only for older models.
    is_inference_profile = "inference-profile" in bedrock_model_id or "sonnet-4-5" in bedrock_model_id
    if not is_inference_profile:
        body["top_p"] = 0.9  # old model config
    if system_message:
        body["system"] = system_message
    resp = bedrock.invoke_model(
        modelId=bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    data = json.loads(resp["body"].read().decode("utf-8"))
    blocks = data.get("content") or []
    texts = [b.get("text", "") for b in blocks if isinstance(b, dict)]
    return "".join(texts).strip() or str(data)

def _invoke_llama_like(content: str) -> str:
    body = {"prompt": content, "max_gen_len": 2048, "temperature": 0.2, "top_p": 0.9}
    resp = bedrock.invoke_model(
        modelId=bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    data = json.loads(resp["body"].read().decode("utf-8"))
    if isinstance(data, dict) and "generation" in data:
        return str(data["generation"]).strip()
    if "outputs" in data and data["outputs"]:
        return str(data["outputs"][0].get("text", "")).strip()
    return str(data.get("output_text") or "").strip()

def _invoke_nova(content: str) -> str:
    body = {"inputText": content, "textGenerationConfig": {"maxTokenCount": 2048, "temperature": 0.2, "topP": 0.9}}
    resp = bedrock.invoke_model(
        modelId=bedrock_model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    data = json.loads(resp["body"].read().decode("utf-8"))
    results = data.get("results") or []
    return (results[0].get("outputText", "") if results else "") or str(data.get("outputText") or "").strip()

def _invoke_fallback(content: str, system_message: str | None, image_blocks: list[dict] | None = None) -> str:
    if _is_anthropic(bedrock_model_id):
        return _invoke_anthropic(content, system_message, image_blocks)
    if _is_nova(bedrock_model_id):
        return _invoke_nova(content)
    return _invoke_llama_like(content)

def call_bedrock_chat(
    user_prompt: str,
    system_message: str | None = None,
    *,
    image_blocks: list[dict] | None = None,
) -> str:
    if bedrock is None or not bedrock_model_id:
        try:
            from agents.sample_agent import config as agent_config
            from agents.sample_agent.local_llm import call_local_chat

            return call_local_chat(
                user_prompt,
                system_message=system_message,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_EXTRACTION", os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")),
                temperature=getattr(agent_config, "LOCAL_LLM_TEMPERATURE_EXTRACTION", 0.0),
                image_bytes=None,
            )
        except Exception as e:
            logger.error("Agent1 local fallback failed: %s", e)
            return ""
    content = f"[System]\n{system_message}\n\n[User]\n{user_prompt}" if system_message else user_prompt
    if image_blocks:
        return _invoke_fallback(content, system_message, image_blocks)
    try:
        start_time = time.time()
        converse_resp = bedrock.converse(
            modelId=bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": content}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.2, "topP": 0.9},
        )
        elapsed = time.time() - start_time
        text = _parse_converse_text(converse_resp)
        if text:
            logger.info("Agent1 call_bedrock_chat: converse OK (%.1fs, %d chars)", elapsed, len(text))
            return text
    except Exception as e:
        logger.warning("Agent1 call_bedrock_chat: exception %s", e)
        pass
    return _invoke_fallback(content, system_message)

# ---------------------------------
# Contract spec (one row per sub-item)
# ---------------------------------
CLAUSE_SPEC = {
    1: ("Payment Terms", [
        "45% Minimum Advance",
        "All payments Net 30 days from invoice",
        "Partial delivery/invoicing allowed",
    ]),
    2: ("Bank Guarantees", [
        "Performance Bonds/Guarantee not to exceed 10%",
    ]),
    3: ("Liquidated Damages (LD)", [
        "Documentation: LD not applicable",
        "Equipment Delivery: 0.5% of undelivered part/week, max 5%",
        "Remedial Work: LD not applicable",
        "Aggregate LD: Max 5% of PO value",
    ]),
    4: ("Guarantee", [
        "Standard: 2 months from commissioning or 18 months from dispatch",
        "Remedial: 12 months from repair/replacement or 18 months from dispatch",
    ]),
    5: ("Force Majeure", [
        "Includes: Act of God, expropriation, law changes, war, sabotage, floods, severe weather, fires, strikes, Pandemic",
        "Applicable to sub-suppliers/sub-contractors",
    ]),
    6: ("Storage", [
        "7 days free",
        "Afterwards: 1% of PO value per equipment/week",
    ]),
    7: ("Defect Liability", [
        "10% of PO value",
    ]),
    8: ("Cancellation Clause (Early Termination Fee)", [
        "0-30 Days: 7.5%",
        "31-60 Days: 25%",
        "61-90 Days: 40%",
        "91-120 Days: 55%",
        "121-150 Days: 70%",
        "151-180 Days: 85%",
        "181+ Days: 100% of Order Value",
    ]),
    9: ("Suspension", [
        "Max 2 suspensions, aggregate max 30 days",
        "Exceeding treated as termination for convenience",
    ]),
    10: ("PO Amendment", [
        "Within 10 days of agreed change order",
    ]),
    11: ("Governing Law & Arbitration", [
        "Law: England & Wales / India / Texas",
        "Arbitration: London / Singapore",
    ]),
    12: ("Insurance", [
        "Covers equipment damage while in Godrej’s premises",
    ]),
    13: ("Limitation of Liability", [
        "Limited to PO value",
    ]),
    14: ("Consequential Damages", [
        "Neither Party liable for loss of revenue, profit, use, production, downtime, business opportunity, or indirect/consequential damages",
    ]),
}

# ---------------------------------
# Chunking guards
# ---------------------------------
HARD_INPUT_CHAR_LIMIT = 90000
CHUNK_SIZE = 12000
CHUNK_OVERLAP = 3000

def _split(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not text:
        return [""]
    out, i, n = [], 0, len(text)
    while i < n:
        end = min(n, i + size)
        out.append(text[i:end])
        if end == n:
            break
        i = max(0, end - overlap)
    return out


def _score_segment(text: str) -> int:
    """Score a segment based on presence of critical contract keywords."""
    if not text:
        return 0
    # Keywords for the 14 clauses to guide the sampler
    keywords = [
        r"payment", r"advance", r"milestone", r"invoice", r"bond", r"guarantee", r"warranty",
        r"liquidated", r"damage", r"penalty", r"delay", r"defect", r"liability",
        r"cancellation", r"termination", r"7\.5%", r"0-30", r"31-60", r"61-90", r"10\.1", r"10\.2",
        r"convenience", r"notification", r"suspension", r"suspend", r"amendment", r"change order",
        r"governing law", r"arbitration", r"insurance", r"limitation of liability", r"consequential", r"indirect"
    ]
    score = 0
    text_lower = text.lower()
    for kw in keywords:
        if re.search(kw, text_lower):
            score += 1
    return score

def _sample_segments(segments: list[str], cap: int) -> list[str]:
    """
    Smart Sampling: Always keep start/end chunk, then fill remaining quota 
    with chunks having highest keyword density (likely to contain clauses).
    """
    n = len(segments)
    if cap <= 0 or n <= cap:
        return segments
    if cap == 1:
        return [segments[0]]
    if cap == 2:
        return [segments[0], segments[-1]]

    # 1. Mandatory segments (Start and End)
    head_count = 1
    tail_count = 1
    
    # 2. Score all segments NOT already in head/tail
    scored = []
    for i, seg in enumerate(segments):
        if i < head_count or i >= (n - tail_count):
            continue
        scored.append((_score_segment(seg), i, seg))
    
    # Sort by score (descending), then by index (to keep order stable)
    scored.sort(key=lambda x: (-x[0], x[1]))
    
    # Pick the top segments to fill the quota
    needed = cap - (head_count + tail_count)
    picked_indices = [0, n-1]
    for _, idx, _ in scored[:needed]:
        picked_indices.append(idx)
    
    # Sort indices so we process the document in chronological order
    picked_indices.sort()
    
    return [segments[i] for i in picked_indices]

def _doc_search_roots() -> list[Path]:
    env = (os.getenv("PED_DOC_ROOTS") or "").strip()
    if env:
        return [Path(p.strip()) for p in env.split(",") if p.strip()]
    cwd = Path.cwd()
    return [
        cwd / "geg_guru" / "media",
        cwd / "geg_guru" / "media" / "uploads",
    ]

def _resolve_doc_path(name: str, roots: list[Path]) -> Path | None:
    if not name:
        return None
    candidate = Path(name)
    if candidate.is_file():
        return candidate
    for root in roots:
        cand = root / name
        if cand.is_file():
            return cand
    return None

def _build_image_blocks(doc_names: dict[str, str]) -> list[dict]:
    if render_pdf_images is None:
        return []
    max_pages = int(os.getenv("PED_IMAGE_PAGES_PER_DOC", "3"))
    max_total = int(os.getenv("PED_IMAGE_MAX_TOTAL", "8"))
    if max_pages <= 0 or max_total <= 0:
        return []
    blocks: list[dict] = []
    roots = _doc_search_roots()
    total_images = 0
    for label, _ in DOC_SECTIONS:
        name = (doc_names.get(label) or "").strip()
        path = _resolve_doc_path(name, roots)
        if not path or path.suffix.lower() != ".pdf":
            continue
        
        try:
            images = render_pdf_images(str(path), max_pages=max_pages)
        except Exception:
            logger.exception("Agent1 _build_image_blocks: Failed to render PDF images for %s", name)
            continue
            
        for page_num, image_bytes in images:
            if total_images >= max_total:
                break
            blocks.append({"type": "text", "text": f"FILE: {path.name} [{label}] PAGE {page_num}"})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                }
            )
            total_images += 1
        if total_images >= max_total:
            break
    return blocks

UNREADABLE_TOKENS = {"na", "n/a", "n.a", "n.a.", "nil", "none", "notapplicable"}

def _looks_like_placeholder(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    # If document is substantial (e.g. > 2500 chars), it's not a placeholder.
    # This prevents drafts with many [to be completed] tags from being flagged.
    if len(cleaned) > 2500:
        return False
    if len(cleaned) < 60:
        tokens = re.findall(r"[a-z0-9/]+", cleaned)
        if tokens and all(tok in UNREADABLE_TOKENS for tok in tokens):
            return True
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    if lines:
        na_lines = sum(1 for ln in lines if ln.replace(" ", "") in UNREADABLE_TOKENS)
        if na_lines / len(lines) >= 0.5:
            return True
    tokens = re.findall(r"[a-z0-9/]+", cleaned)
    if tokens:
        na_tokens = sum(1 for tok in tokens if tok in UNREADABLE_TOKENS)
        if na_tokens >= 3 and na_tokens / len(tokens) >= 0.3:
            return True
    letters = sum(1 for ch in cleaned if ch.isalpha())
    if len(cleaned) > 120 and letters / len(cleaned) < 0.15:
        return True
    return False

def _quality_note(text: str) -> str:
    if not text or not text.strip():
        return ""
    if _looks_like_placeholder(text):
        return "Text unreadable/NA in source; refer to file"
    return ""

def _assess_doc_quality(section_texts: dict[str, str]) -> tuple[dict[str, str], bool]:
    notes: dict[str, str] = {}
    first_label_with_text = ""
    logger.info("Agent1 _assess_doc_quality: assessing %d sections", len(DOC_SECTIONS))
    for label, _ in DOC_SECTIONS:
        text = (section_texts.get(label) or "").strip()
        text_size = len(text)
        logger.debug("Agent1 _assess_doc_quality: [%s] %d chars", label, text_size)
        if not text:
            logger.debug("Agent1 _assess_doc_quality: [%s] empty/missing", label)
            continue
        if not first_label_with_text:
            first_label_with_text = label
            logger.debug("Agent1 _assess_doc_quality: [%s] set as primary", label)
        note = _quality_note(text)
        if note:
            notes[label] = note
            logger.warning("Agent1 _assess_doc_quality: [%s] quality issue: %s", label, note)
    
    # Robust readability: true if ANY of the main contract documents are readable
    readable_count = 0
    total_with_text = 0
    for label in ["PO", "SPC", "GPC"]:
        if (section_texts.get(label) or "").strip():
            total_with_text += 1
            if label not in notes:
                readable_count += 1
    
    # If we have text but NONE of it is readable, then we flag it.
    # Otherwise, if we have at least one good source, we trust the agent to report findngs.
    primary_readable = bool(readable_count > 0 or total_with_text == 0)
    
    logger.info("Agent1 _assess_doc_quality: primary_readable=%s, quality_issues=%d", primary_readable, len(notes))
    return notes, primary_readable


def _normalize_location(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    tokens = raw.upper()
    mapped: list[str] = []
    for label, _ in DOC_SECTIONS:
        needle = label.upper()
        if needle in tokens or f"[{needle}]" in tokens:
            mapped.append(f"[{needle}]")
    if "[PO]" not in mapped and ("[1]" in tokens or " PO" in tokens):
        mapped.insert(0, "[PO]")
    if "[TERMS]" not in mapped and ("[2]" in tokens or "TERMS" in tokens):
        mapped.append("[TERMS]")
    return "".join(mapped) if mapped else raw


def _location_priority(raw: str) -> int:
    normalized = _normalize_location(raw)
    for label, _ in DOC_SECTIONS:
        tag = f"[{label}]"
        if tag in normalized:
            return DOC_PRIORITY[label]
    return len(DOC_SECTIONS) + 5


def _find_section_hint(text: str) -> str:
    if not text:
        return ""
    match = SECTION_HINT_RE.search(text)
    return match.group(1) if match else ""


def _find_page_hint(text: str) -> str:
    if not text:
        return ""
    match = PAGE_HINT_RE.search(text)
    if match:
        return match.group(1)
    match = PAGE_MARKER_RE.search(text)
    return match.group(1) if match else ""


def _file_from_location(loc: str, doc_names: dict[str, str]) -> str:
    normalized = _normalize_location(loc)
    for label, _ in DOC_SECTIONS:
        if f"[{label}]" in normalized:
            return doc_names.get(label) or label
    return ""


def _looks_like_citation(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if text.count(",") >= 2:
        return True
    return "section" in lowered and "page" in lowered


def _normalize_citation(raw: str, loc: str, doc_names: dict[str, str], evidence: str) -> str:
    cleaned = (raw or "").strip().strip(";")
    if cleaned and _looks_like_citation(cleaned):
        return cleaned
    if not cleaned and not loc:
        return ""
    section_hint = _find_section_hint(cleaned) or _find_section_hint(evidence)
    page_hint = _find_page_hint(cleaned) or _find_page_hint(evidence)
    section_label = f"Section {section_hint}" if section_hint else "Section not specified"
    page_label = f"page {page_hint}" if page_hint else "page n/a"
    file_name = _file_from_location(loc, doc_names) or "file unknown"
    return f"{file_name}, {section_label}, {page_label}"


def _compose_met(status: str, evidence: str) -> str:
    status_label = status or "NA"
    detail = evidence.strip() if evidence else ""
    return f"{status_label} – {detail}".strip(" –") if detail else status_label

def _compose_reference(citation: str, fallback: str = "") -> str:
    ref = (citation or "").strip()
    if ref:
        return ref
    fallback = (fallback or "").strip()
    return fallback if fallback else "-"



# ---------------------------------
# JSON-first extraction per chunk
# ---------------------------------
def _parse_json_list(raw: str) -> list[dict]:
    """Parse JSON list from LLM response using robust scanning."""
    if not raw or not raw.strip():
        logger.warning("Agent1 _parse_json_list: received empty response")
        return []

    cleaned = raw.strip()
    logger.debug("Agent1 _parse_json_list: input=%d chars", len(raw))

    # 1. Attempt direct parse (fastest)
    try:
        # Strip markdown code blocks if present
        if "```" in cleaned:
            pattern = r"```(?:json)?\s*(\[.*?\])\s*```"
            match = re.search(pattern, cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)
        
        data = json.loads(cleaned)
        if isinstance(data, list):
            logger.info("Agent1 _parse_json_list: ✓ parsed %d items (direct/cleaned)", len(data))
            return data
    except Exception:
        pass

    # 2. Robust object scanning using raw_decode
    # This handles preamble, postamble, and braces inside strings correctly.
    logger.debug("Agent1 _parse_json_list: attempting robust object scanning")
    
    objects = []
    decoder = json.JSONDecoder()
    
    # Find the first '[' to start scanning
    idx = cleaned.find('[')
    if idx == -1:
        # No list start found? Try finding first '{'
        idx = cleaned.find('{')
    
    if idx == -1:
         logger.error("Agent1 _parse_json_list: no JSON start markers found")
         return []

    failures = 0
    while idx < len(cleaned):
        # Skip optional whitespace and commas/brackets between objects
        while idx < len(cleaned) and cleaned[idx] in " \t\n\r,[]":
            idx += 1
        
        if idx >= len(cleaned):
            break
            
        try:
            obj, end_idx = decoder.raw_decode(cleaned, idx)
            if isinstance(obj, dict):
                objects.append(obj)
            idx = end_idx
            failures = 0 # Reset failure count on success
        except json.JSONDecodeError:
            # If we can't decode at this position, skip one char and try again
            # This is slow but resilient to garbage between objects
            idx += 1
            failures += 1
            if failures > 500: # optimization: give up if too much garbage
                break

    if objects:
        logger.info("Agent1 _parse_json_list: ✓ scanned %d items", len(objects))
        return objects

    logger.error("Agent1 _parse_json_list: ✗ all parsing methods failed")
    return []

def _compress_chunk(
    section_chunks: dict[str, str],
    doc_names: dict[str, str],
    quality_notes: dict[str, str] | None = None,
) -> list[dict]:
    """
    Return ONLY JSON list of findings:
    [{"clause_id":1,"clause":"Payment Terms","subitem":"45% Minimum Advance","status":"Yes|No|NA|Partial","evidence":"...", "citation":"file, section, page", "location":"PO|Terms|Both (optional)"}]
    """
    checklist = []
    for cid, (cname, items) in CLAUSE_SPEC.items():
        for si in items:
            checklist.append({"clause_id": cid, "clause": cname, "subitem": si})

    doc_overview_lines = []
    doc_payload_lines = []
    for label, desc in DOC_SECTIONS:
        text = section_chunks.get(label, "").strip()
        file_name = doc_names.get(label) or ""
        file_hint = f" | File: {file_name}" if file_name else ""
        doc_overview_lines.append(f"- [{label}] {desc}{file_hint}")
        if text:
            header = f"FILE: {file_name}\n" if file_name else ""
            doc_payload_lines.append(f"[{label}]\n{header}{text}\n")
    docs_blob = "\n".join(doc_payload_lines).strip()
    docs_blob = docs_blob or "[PO]\n"
    quality_lines = []
    if quality_notes:
        for label, _ in DOC_SECTIONS:
            note = quality_notes.get(label)
            if not note:
                continue
            file_name = doc_names.get(label) or label
            quality_lines.append(f"- [{label}] {file_name}: {note}")
    quality_block = ""
    if quality_lines:
        quality_block = "\nPotential quality issues detected:\n" + "\n".join(quality_lines) + "\n"

    system = (
        "Extract precise, clause-wise findings as strict JSON. No preamble. "
        "Honor document priority exactly as described. "
        "Scope: GB Aerospace supply contracts only (supplier supplying goods); not procurement/purchase, "
        "NDAs as primary, consortiums, or other agreement types unless user context says otherwise. "
        "POC outputs are for validation only — not commercial practice without Legal approval. "
        "Every non-omitted finding must include evidence that is a verbatim extract copy-pasteable from the excerpt."
    )
    prompt = f"""
You are given up to four contract documents. ALWAYS consult them in this hierarchy (high → low authority):
{chr(10).join(doc_overview_lines)}
{quality_block}

Return ONLY a JSON array (no markdown). Each element must be:
{{"clause_id": <int>, "clause": "<name>", "subitem": "<verbatim from checklist>", "status": "Yes|No|NA|Partial", "evidence": "<short quote>", "citation": "<file, section, page>", "location": "one of [PO], [SPC], [GPC], [TERMS]"}}

Rules:
- Scan for each checklist sub-item **in priority order**: rely on PO first; only if PO is silent use SPC; only if both are silent use GPC; use Terms/others last.
- If two sources conflict, keep the higher-priority source and ignore the rest.
- **CRITICAL OMIT RULE**: If the excerpt provides NO EXPLICIT information for a sub-item, **YOU MUST COMPLETELY OMIT** that sub-item from the JSON. 
- DO NOT return a skeletal object with just the "clause_id" and "clause" name if you found no evidence. 
- **Status "No"**: Use ONLY if there is explicit evidence that the requirement is NOT met (e.g., "45% advance is not allowed").
- **Status "Partial"**: Use ONLY if the requirement is partially met (e.g., "10% advance found" instead of 45%). 
- **CRITICAL**: If you found NO mentions of the sub-item, **YOU MUST OMIT** the sub-item. DO NOT use "Partial" or "No" for missing info.
- **Status "NA"**: Use ONLY if explicitly stated as "Not Applicable", "N/A", or if text is garbled/NA placeholders.
- **Flexible Matching**: The sub-items in the checklist are summary labels. Match them semantically even if the wording differs (e.g., match "0-30 Days" to "within 1 month" or "181+ Days" to "after 6 months").
- Keep evidence short; quote the exact clause wording when possible (substring of the excerpt; no paraphrase as evidence).
- Use the FILE and PAGE markers from the excerpt for citation. Format citation exactly as: "file name, Section <number or heading>, page <number>".
- If section/page are not explicit, write "Section not specified" and "page n/a". If unsure, leave "location" blank (but prefer tagging the actual source, e.g., "[PO]" or "[SPC]").
- If a section appears to contain only placeholders (like "[to be completed]"), favor higher-authority documents or report what you find verbatim.
Checklist (verbatim subitems):
{json.dumps(checklist, ensure_ascii=False, indent=2)}

--- Excerpt Start ---
{docs_blob}
--- Excerpt End ---
"""
    # DEBUG: Log the input text to the debug file
    try:
        with open("/Users/amethyst_local/Downloads/amethyst-main/dev/ped_llm_debug.txt", "a") as f:
            f.write(f"\n\n--- CHUNK INPUT (length {len(docs_blob)}) ---\n{docs_blob[:2000]}... [truncated]\n")
    except:
        pass

    raw = call_bedrock_chat(prompt, system)
    # Deep logging of response
    logger.info("Agent1 _compress_chunk: bedrock response length=%d", len(raw))
    
    # DEBUG: Write raw response to a file
    try:
        with open("/Users/amethyst_local/Downloads/amethyst-main/dev/ped_llm_debug.txt", "a") as f:
            f.write(f"\n\n--- CHUNK RESPONSE ---\n{raw}\n")
    except:
        pass

    if len(raw) < 2000:
        logger.info("Agent1 _compress_chunk: full response: %r", raw)
    else:
        logger.info("Agent1 _compress_chunk: response start: %r", raw[:1000])
        logger.info("Agent1 _compress_chunk: response end: %r", raw[-1000:])
        
    logger.debug("Agent1 _compress_chunk: bedrock response=%d chars, first 80: %.80s", len(raw), raw)
    result = _parse_json_list(raw)
    
    if not result:
        logger.error("Agent1 _compress_chunk: Bedrock returned text but JSON parse failed. First 300 chars: %.300s", raw)
    else:
        logger.info("Agent1 _compress_chunk: extracted %d findings", len(result))
    return result

def _compress_with_images(doc_names: dict[str, str], image_blocks: list[dict]) -> list[dict]:
    checklist = []
    for cid, (cname, items) in CLAUSE_SPEC.items():
        for si in items:
            checklist.append({"clause_id": cid, "clause": cname, "subitem": si})
    doc_overview_lines = []
    for label, desc in DOC_SECTIONS:
        file_name = doc_names.get(label) or ""
        file_hint = f" | File: {file_name}" if file_name else ""
        doc_overview_lines.append(f"- [{label}] {desc}{file_hint}")
    system = (
        "Extract precise, clause-wise findings as strict JSON. No preamble. "
        "Honor document priority exactly as described. "
        "Scope: GB Aerospace supply contracts only (supplier supplying goods); not procurement/purchase, "
        "NDAs as primary, consortiums, or other agreement types unless user context says otherwise. "
        "POC outputs are for validation only — not commercial practice without Legal approval. "
        "Every non-omitted finding must include evidence that is a verbatim extract copy-pasteable from the excerpt."
    )
    prompt = f"""
You are given page snapshots from contract documents. ALWAYS consult them in this hierarchy (high -> low authority):
{chr(10).join(doc_overview_lines)}

Return ONLY a JSON array (no markdown). Each element must be:
{{"clause_id": <int>, "clause": "<name>", "subitem": "<verbatim from checklist>", "status": "Yes|No|NA|Partial", "evidence": "<short quote>", "citation": "<file, section, page>", "location": "one of [PO], [SPC], [GPC], [TERMS]"}}

Rules:
- Use the page snapshots to read the clauses directly.
- If two sources conflict, keep the higher-priority source and ignore the rest.
- If you cannot find a sub-item, omit it from the JSON.
- Keep evidence short; quote the exact clause wording when possible (substring of the excerpt; no paraphrase as evidence).
- Use the FILE and PAGE labels preceding each image for citation. Format citation exactly as: "file name, Section <number or heading>, page <number>".
- If section/page are not explicit, write "Section not specified" and "page n/a".
- If a snapshot is truly unreadable, omit findings for that specific section. Do NOT hallucinate findings.

Checklist (verbatim subitems):
{json.dumps(checklist, ensure_ascii=False, indent=2)}
"""
    raw = call_bedrock_chat(prompt, system, image_blocks=image_blocks)
    return _parse_json_list(raw)

def _status_rank(s: str) -> int:
    s = (s or "").strip().lower()
    if s.startswith("no"):
        return 4
    if s.startswith("yes"):
        return 3
    if s.startswith("partial"):
        return 2
    if s.startswith("na"):
        return 1
    return 0

def _merge_findings(findings_list: list[list[dict]]) -> dict:
    """
    Build canonical dict: merged[cid][subitem] = {"status":..., "evidence":..., "citation":..., "location":...}
    Preference: No > Partial > Yes > NA.
    Aggregate up to 2 evidence snippets.
    """
    merged: dict = {cid: {} for cid in CLAUSE_SPEC.keys()}
    logger.debug("Agent1 _merge_findings: merging %d finding groups", len(findings_list))
    
    total_input = sum(len(f) for f in findings_list)
    logger.debug("Agent1 _merge_findings: total input findings: %d", total_input)
    
    for findings in findings_list:
        for f in findings:
            cid = int(f.get("clause_id", 0))
            sub = f.get("subitem", "").strip()
            # Filter out skeletal findings (LLM errors) or missing sub-items
            if cid not in merged or not sub or "status" not in f:
                continue
            cur = merged[cid].get(
                sub,
                {"status": "NA", "evidence": [], "citation": "", "location": "", "_priority": len(DOC_SECTIONS) + 5},
            )
            cand_status = f.get("status", "NA")
            ev = f.get("evidence") or ""
            citation = f.get("citation") or ""
            loc = _normalize_location(f.get("location") or cur.get("location") or "")
            
            # Protection: Only demote if it's very clearly a draft placeholder (PO draft issues)
            # Avoid demoting if it contains real numbers or percentage symbols.
            ev_lower = ev.lower()
            is_placeholder_only = any(x in ev_lower for x in ["to be completed", "to be evaluated", "to be discussed"])
            is_generic_missing = any(x in ev_lower for x in ["not explicitly", "no explicit", "not listed", "not found"])
            
            if _status_rank(cand_status) > 1:
                # If it has a status like Partial/Yes but the evidence is just a 'not found' placeholder
                # we demote it to NA so it doesn't pollute the results. 
                # HOWEVER: if it mentions percentages (7.5%) or numbers, it's likely real data.
                if is_placeholder_only or (is_generic_missing and "%" not in ev and not re.search(r"\d", ev)):
                    logger.debug("Agent1 _merge_findings: demoting %s to NA due to placeholder evidence: %r", cand_status, ev)
                    cand_status = "NA"

            cand_priority = _location_priority(loc)
            cur_priority = cur.get("_priority", len(DOC_SECTIONS) + 5)

            should_replace = False
            
            # CRITICAL FIX: NA should NEVER replace a valid finding (Yes/No/Partial) 
            # even if it comes from a higher priority document.
            if _status_rank(cand_status) <= 1 and _status_rank(cur["status"]) > 1:
                should_replace = False
            elif cand_priority < cur_priority:
                should_replace = True
            elif cand_priority == cur_priority and _status_rank(cand_status) >= _status_rank(cur["status"]):
                should_replace = True

            if should_replace:
                logger.debug("Agent1 _merge_findings: [C%d] %s: %s→%s (priority %d)", cid, sub[:30], cur["status"], cand_status, cand_priority)
                cur["status"] = cand_status
                cur["evidence"] = [ev] if ev and cand_status != "NA" else []
                cur["citation"] = citation
                cur["location"] = loc
                cur["_priority"] = cand_priority
            else:
                if ev:
                    if isinstance(cur["evidence"], list):
                        cur["evidence"].append(ev)
                        cur["evidence"] = cur["evidence"][:2]
                if citation and not cur.get("citation"):
                    cur["citation"] = citation
            merged[cid][sub] = cur
    # fill missing with NA
    for cid, (_, items) in CLAUSE_SPEC.items():
        for si in items:
            merged[cid].setdefault(
                si,
                {"status": "NA", "evidence": [], "citation": "", "location": "", "_priority": len(DOC_SECTIONS) + 5},
            )

    for cid in merged:
        for si in merged[cid]:
            merged[cid][si].pop("_priority", None)
    return merged

def _na_ratio(merged: dict) -> float:
    total = 0
    na_count = 0
    status_counts = {"yes": 0, "no": 0, "partial": 0, "na": 0}
    for cid, (_, items) in CLAUSE_SPEC.items():
        for si in items:
            total += 1
            st = (merged.get(cid, {}).get(si, {}) or {}).get("status", "NA").lower()
            if st.startswith("na"):
                na_count += 1
                status_counts["na"] += 1
            elif st.startswith("yes"):
                status_counts["yes"] += 1
            elif st.startswith("no"):
                status_counts["no"] += 1
            elif st.startswith("partial"):
                status_counts["partial"] += 1
    
    ratio = na_count / total if total else 1.0
    logger.debug("Agent1 _na_ratio: total=%d, na=%d, yes=%d, no=%d, partial=%d, ratio=%.2f%%", 
                 total, status_counts["na"], status_counts["yes"], status_counts["no"], status_counts["partial"], ratio*100)
    return ratio

def _render_table(
    merged: dict,
    doc_names: dict[str, str],
    quality_notes: dict[str, str] | None = None,
    primary_readable: bool = True,
) -> str:
    """
    Render the gold-standard clause table, then a compact risks section (optional).
    """
    lines = []
    lines.append("✅ **Contractual Clause Summary**\n")
    lines.append("| Clause | Requirement | Met | References |")
    lines.append("|--------|-------------|-----|------------|")

    unreadable_files = []
    if quality_notes:
        for label, _ in DOC_SECTIONS:
            note = quality_notes.get(label)
            if not note:
                continue
            file_name = doc_names.get(label) or label
            unreadable_files.append(f"{file_name} (text unreadable/NA)")
    unreadable_refs = "; ".join(unreadable_files).strip()

    for cid in range(1, 15):
        cname, items = CLAUSE_SPEC[cid]
        for si in items:
            rec = merged.get(cid, {}).get(si, {"status": "NA", "evidence": [], "citation": "", "location": ""})
            st = rec.get("status", "NA")
            ev_list = rec.get("evidence") or []
            # Sanitize evidence: remove newlines and pipes which break markdown tables
            ev = "; ".join([str(e).replace("\n", " ").replace("|", " ") for e in ev_list if e])[:420]
            
            loc = _normalize_location(rec.get("location") or "")
            citation = _normalize_citation(rec.get("citation") or "", loc, doc_names, ev)
            
            # Sanitize citation and status text as well
            reference = str(citation).replace("\n", " ").replace("|", " ")
            status_display = st.replace("\n", " ").replace("|", " ")
            
            if status_display.lower().startswith("yes"):
                met = _compose_met("Yes", ev)
            elif status_display.lower().startswith("no"):
                met = _compose_met("No", ev)
            elif status_display.lower().startswith("partial"):
                met = _compose_met("Partial", ev)
            else:
                if ev:
                    met = _compose_met("NA", ev)
                elif quality_notes and not primary_readable:
                    met = "NA – text unreadable/NA in source; refer to file"
                    if not reference and unreadable_refs:
                        reference = unreadable_refs
                else:
                    met = "NA – absent in extracted text"

            # Final safety check on met string (header-related formatting)
            met = met.replace("\n", " ").replace("|", " ")
            reference_fallback = ""
            if st.lower().startswith("na") and quality_notes and not primary_readable:
                reference_fallback = unreadable_refs
            lines.append(
                "| {clause} | {req} | {met} | {ref} |".format(
                    clause=f"{cid}. {cname}",
                    req=si,
                    met=met,
                    ref=_compose_reference(reference, reference_fallback),
                )
            )

    # Optional risks section (useful for Agent 2 fallback)
    lines.append("\n⚠️ **Risks Identified**\n")
    for cid in range(1, 15):
        cname, items = CLAUSE_SPEC[cid]
        for si in items:
            st = (merged.get(cid, {}).get(si, {}) or {}).get("status", "NA").lower()
            if st.startswith("yes"):
                continue
            lines.append(f"- **{cname} – {si}**: status {st.upper()}")

    return "\n".join(lines)

# ---------------------------------
# Main Entry
# ---------------------------------
def run_clause_analysis(
    po_text: str,
    terms_text: str,
    spc_text: str = "",
    gpc_text: str = "",
    *,
    doc_names: dict[str, str] | None = None,
) -> str:
    """
    Chunk both docs → extract sub-item findings as JSON → merge → render
    the exact 4-column Markdown table (+ brief risks list).
    """
    safe_doc_names: dict[str, str] = {}
    for label, _ in DOC_SECTIONS:
        value = (doc_names or {}).get(label)
        safe_doc_names[label] = value if value is not None else label
    
    logger.info("Agent1 run_clause_analysis: START")

    for label, text in [("PO", po_text), ("SPC", spc_text), ("GPC", gpc_text), ("TERMS", terms_text)]:
        content = (text or "").strip()
        if content:
            logger.info("Agent1 run_clause_analysis: [%s] length=%d. First 100 chars: %r", label, len(content), content[:100])
        else:
            logger.warning("Agent1 run_clause_analysis: [%s] is EMPTY or None", label)

    logger.debug("Agent1 run_clause_analysis: input texts: PO=%d, SPC=%d, GPC=%d, TERMS=%d", 
                 len(po_text or ""), len(spc_text or ""), len(gpc_text or ""), len(terms_text or ""))
    
    section_texts = {
        "PO": po_text or "",
        "SPC": spc_text or "",
        "GPC": gpc_text or "",
        "TERMS": terms_text or "",
    }
    quality_notes, primary_readable = _assess_doc_quality(section_texts)
    
    # --- ANALYSIS STRATEGY ---
    # Choice 1: FULL DOCUMENT (Fastest, for docs < 180k chars / ~45k tokens)
    # Choice 2: LARGE CHUNKS (Cover 100% of doc with 50k chunks to avoid 50k token Mumbai Quota)
    total_len = sum(len(txt) for txt in section_texts.values())
    
    # 180k chars is safe for the suspected 50k token request limit in ap-south-1
    if total_len < 180000:
        logger.info("Agent1 run_clause_analysis: [Full Doc Mode] total_len=%d. Using single call.", total_len)
        findings_all = [_compress_chunk(section_texts, safe_doc_names, quality_notes)]
    else:
        logger.info("Agent1 run_clause_analysis: [Large Chunk Mode] total_len=%d. Using 50k chunks for quota safety.", total_len)
        chunk_payloads = []
        
        # We use a larger chunk size (50k) and overlap (10k) to cover the whole doc in few calls
        BIG_CHUNK = 50000
        BIG_OVERLAP = 10000
        
        # Combine all text with clear markers to ensure 100% visibility
        all_text_combined = ""
        for label, txt in section_texts.items():
            if txt:
                all_text_combined += f"\n\n--- SECTION: {label} ---\n\n{txt}"
        
        # Split the combined text into a few large chunks
        start = 0
        while start < len(all_text_combined):
            end = start + BIG_CHUNK
            segment = all_text_combined[start : end]
            # Try to break at a newline to keep it clean
            if end < len(all_text_combined):
                last_nl = segment.rfind("\n")
                if last_nl > BIG_CHUNK * 0.8:
                    segment = all_text_combined[start : start + last_nl]
                    start += last_nl - BIG_OVERLAP
                else:
                    start += BIG_CHUNK - BIG_OVERLAP
            else:
                start = len(all_text_combined)
            
            if segment.strip():
                chunk_payloads.append({"CONTRACT_ALL": segment})

        logger.info("Agent1 run_clause_analysis: starting %d large chunks in parallel", len(chunk_payloads))
        num_workers = int(os.getenv("PED_MAX_WORKERS", "3"))
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            def _process_one(idx_payload):
                idx, chunk_sections = idx_payload
                logger.info("Agent1 run_clause_analysis: Large Chunk %d/%d start", idx, len(chunk_payloads))
                return _compress_chunk(chunk_sections, safe_doc_names, quality_notes)
            
            payload_queue = list(enumerate(chunk_payloads, 1))
            results = list(executor.map(_process_one, payload_queue))
            findings_all = [f for f in results if f]

    total_findings = sum(len(f) for f in findings_all)
    logger.info("Agent1 run_clause_analysis: total findings: %d", total_findings)
    
    merged = _merge_findings(findings_all)
    na_ratio = _na_ratio(merged)
    logger.info("Agent1 run_clause_analysis: after merge NA ratio: %.2f%%", na_ratio * 100)
    
    na_threshold = float(os.getenv("PED_NA_FALLBACK_THRESHOLD", "0.6"))
    if na_threshold <= 0:
        na_threshold = 0.6
    needs_images = (not primary_readable) or (na_ratio >= na_threshold) or not findings_all
    
    if needs_images:
        logger.info("Agent1 run_clause_analysis: triggering image fallback (readable=%s, na_ratio=%.2f, threshold=%.2f)", 
                    primary_readable, na_ratio, na_threshold)
        image_blocks = _build_image_blocks(safe_doc_names)
        if image_blocks:
            logger.info("Agent1 run_clause_analysis: processing %d image blocks", len(image_blocks))
            image_findings = _compress_with_images(safe_doc_names, image_blocks)
            if image_findings:
                logger.info("Agent1 run_clause_analysis: image extraction got %d findings", len(image_findings))
                findings_all.append(image_findings)
                merged = _merge_findings(findings_all)
        else:
            logger.warning("Agent1 run_clause_analysis: no image blocks available")
    
    logger.info("Agent1 run_clause_analysis: COMPLETE")
    return _render_table(merged, safe_doc_names, quality_notes, primary_readable)


# ---------------------------------
# Aerospace-specific extraction contract (JSON-knowledge driven)
# ---------------------------------
def _aero_sentence_candidates(text: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"[\r\n]+", text or ""):
        block = " ".join(block.split()).strip()
        if not block:
            continue
        for sent in [s.strip() for s in re.split(r"(?<=[.!?])\s+", block) if s.strip()]:
            # Drop low-quality binary-like fragments that can leak from bad extraction.
            printable = sum(1 for ch in sent if ch.isprintable() and ch not in "\x00\x01\x02\x03\x04\x05")
            ratio = printable / max(1, len(sent))
            if ratio < 0.92:
                continue
            out.append(sent)
    return out


def _aero_best_evidence(contract_text: str, keywords: list[str]) -> str:
    candidates = _aero_sentence_candidates(contract_text)
    if not candidates:
        return ""
    best = ""
    best_score = 0
    for sent in candidates:
        lowered = sent.lower()
        score = sum(1 for kw in (keywords or []) if kw and kw.lower() in lowered)
        if score > best_score and len(sent) >= 30:
            best_score = score
            best = sent
    return best if best_score > 0 else ""


# Anchor terms: sentence must contain at least one to qualify as evidence for that clause.
# Prevents cross-clause pollution (e.g. liability sentence attributed to Force Majeure).
_AERO_ANCHOR_TERMS: dict[str, list[str]] = {
    "limitation of liability": ["liability", "aggregate liability", "consequential", "indirect damages", "cap", "100%", "200%", "excluded", "exclusion"],
    "governing law": ["governing law", "jurisdiction", "courts", "laws of", "construed", "governed by"],
    "dispute resolution": ["dispute", "arbitration", "mediation", "icc", "siac", "lcia", "arbitrator"],
    "firm price": ["unit price", "unit prices", "price", "prices", "firm and not revisable", "not revisable", "escalation", "price adjustment"],
    "force majeure": ["force majeure", "fm ", "impediment", "act of god", "beyond control", "uncontrollable", "economic hardship", "cash-flow"],
    "liquidated damages": ["liquidated damages", "ld ", "delay", "per week", "0.5%", "2%", "5%", "20%", "delayed value"],
    "orders extending": ["termination", "expiry", "purchase orders", "in-effect", "orders issued", "post-term", "overhang"],
    "quantity protection": ["forecast", "quantity", "deviation", "+/-20%", "reimbursement", "lead time", "firm po"],
    "inventory requirements": ["inventory", "raw material", "weeks", "forecast", "finished goods", "rm", "fg"],
    "change orders": [
        "change order", "change order procedure", "change in law", "equitable adjustment", "price adjustment",
        "nre", "fai", "signed change", "changes procedure", "requests for changes",
        "technical proposal", "commercial quote", "written agreement",
    ],
    "aerospace business critical": ["aerospace", "actuator", "schedule a", "technical specifications", "supplier shall manufacture"],
}

# Exclusion: if evidence contains these phrases WITHOUT the clause's anchor, reject it (cross-clause pollution).
_AERO_EVIDENCE_EXCLUSIONS: dict[str, list[tuple[str, str]]] = {
    "limitation of liability": [
        ("without incurring any liability whatsoever", "program termination right, not liability cap"),
        ("termination of the engine program", "program termination, not liability cap"),
        ("loss of business which is incapable", "often from consequential carve-out, not liability cap"),
        ("incapable of accurate estimation", "damages carve-out, not liability clause"),
        ("per overdue calendar day", "LD/penalty clause, not LoL"),
        ("0,5% of the order line", "LD clause, not LoL"),
        ("0.5% of the order line", "LD clause, not LoL"),
        ("penalty being capped at", "LD clause, not LoL"),
        ("penalty, which does not constitute", "LD clause, not LoL"),
    ],
    "liquidated damages": [
        ("15 days of receipt", "dispute escalation, not LD"),
        ("within 15 days", "notice period, not LD"),
        ("days of receipt of the other", "dispute procedure"),
        ("defend, hold harmless and indemnify", "indemnification clause, not LD"),
        ("hold harmless and indemnify", "indemnification clause, not LD"),
        ("will defend, hold harmless", "indemnification clause, not LD"),
        ("export license be withdrawn", "export control termination, not LD"),
        ("export license be withdrawn, not renewed or invalidated", "export control, not LD"),
        ("claim compensation for the damage sustained by this breach", "export/termination breach, not delivery LD"),
    ],
    "governing law": [
        ("registered capital", "corporate registration details, not governing law"),
        ("registered to the trade", "corporate registration details, not governing law"),
        ("having its head office", "party identity block, not governing law"),
    ],
    "force majeure": [
        ("180 days prior", "design-change clause; require 'force majeure' in same sentence"),
        ("manufacture the goods", "manufacturing clause; require 'force majeure' or 'impediment'"),
    ],
    "orders extending": [
        ("partial termination of this agreement", "termination procedure, not orders extending"),
        ("partial termination", "termination clause; need 'orders' or 'in-effect'"),
    ],
    "inventory requirements": [
        ("manufacturing location", "manufacturing clause; need 'inventory' or 'weeks'"),
        ("subcontracting of process", "subcontracting clause"),
        ("180 days prior to the proposed", "design-change, not inventory"),
        ("non conformity penalty", "non-conformity formula, not inventory"),
        ("non-conformity penalty", "non-conformity formula, not inventory"),
        ("nbc1*f1", "penalty formula, not inventory"),
        ("nbc2c3*f2", "penalty formula, not inventory"),
        # Evidence noise: non-conformity / acceptance-testing fragments that leak via retrieval
        ("c4 is a non-conformity", "non-conformity grading, not inventory obligation"),
        ("non-conformity identified during acceptance", "acceptance testing clause, not inventory"),
        ("non-conformity identified", "non-conformity clause, not inventory"),
        ("acceptance testing", "testing/QC clause, not inventory obligation"),
        ("documentary non-conformance", "QC/documentation clause, not inventory"),
        ("concession issuance", "concession/waiver clause, not inventory"),
    ],
    "quantity protection": [
        ("schedule and/or quantity changes are not eligible for equitable adjustment", "change-order clause, not quantity protection"),
        ("not eligible for equitable adjustment under this changes", "change-order clause"),
    ],
    "firm price": [
        ("firm period", "forecast/order period, not firm price"),
        ("forecasted period", "forecast/order period, not price clause"),
        ("delivery batch", "planning/order mechanics, not price clause"),
    ],
    "change orders": [
        ("forecasted period", "forecast mechanics, not change order procedure"),
        ("delivery batch", "order planning mechanics, not change order procedure"),
        ("committed volume", "volume commitment, not change order procedure"),
        ("committed market share", "market-share appendix, not change order procedure"),
    ],
}


def _aero_anchor_for_clause(name: str) -> list[str]:
    n = (name or "").lower()
    for key, terms in _AERO_ANCHOR_TERMS.items():
        if key in n:
            return terms
    return []


def _aero_evidence_excluded_for_clause(sentence_lower: str, clause_name: str) -> bool:
    """Return True if evidence should be excluded for this clause (cross-clause pollution)."""
    n = (clause_name or "").lower()
    for key, exclusions in _AERO_EVIDENCE_EXCLUSIONS.items():
        if key not in n:
            continue
        for phrase, _ in exclusions:
            if phrase.lower() in sentence_lower:
                return True
    return False


_NEGATION_TOKENS = ("shall not", "does not", "will not", "not", "no", "excluded", "waived")

_CLAUSE_SUPPORTING_DOC_HINTS: dict[str, list[str]] = {
    "firm price": ["appendix 1", "appendix 3", "price schedule"],
    "quantity protection": ["appendix 3", "schedule", "delivery program"],
    "inventory requirements": ["appendix 2", "appendix 3", "delivery program"],
    "liquidated damages": ["appendix 2", "schedule"],
    "change orders procedure": ["change order", "changes procedure", "equitable adjustment"],
}


def _aero_clause_support_hints(clause_name: str) -> list[str]:
    n = (clause_name or "").lower()
    for key, hints in _CLAUSE_SUPPORTING_DOC_HINTS.items():
        if key in n:
            return hints
    return []


def _aero_supporting_doc_relevant(clause_name: str, file_name: str, text: str) -> bool:
    """Return True when a supporting document should be included for this clause."""
    hints = _aero_clause_support_hints(clause_name)
    if not hints:
        return False
    haystack = f"{file_name or ''}\n{text[:2500] if text else ''}".lower()
    return any(hint in haystack for hint in hints)


def _aero_build_clause_text(
    contract_text: str,
    supporting_doc_texts: dict[str, str] | None,
    clause_name: str,
    *,
    allowed_supporting_names: frozenset[str] | None = None,
) -> str:
    """Build clause-specific text, attaching supporting docs only when gated.

    When ``allowed_supporting_names`` is set (referenced + uploaded filenames), include
    a supporting file only if its name is in that set *and* clause-specific hints match.
    This reduces noise from schedules that were not cited in the primary agreement.
    """
    parts = [contract_text or ""]
    if not supporting_doc_texts:
        return contract_text or ""
    for fname, txt in supporting_doc_texts.items():
        if not txt:
            continue
        if allowed_supporting_names is not None and fname not in allowed_supporting_names:
            continue
        if not _aero_supporting_doc_relevant(clause_name, fname, txt):
            continue
        parts.append(f"\n\n[SUPPORTING DOC: {fname}]\n{txt.strip()}")
    return "".join(parts)


def _aero_rag_supplement(
    rag_session_id: str | None,
    clause_name: str,
    keywords: list[str],
    ideal: str,
    base_clause_text: str,
) -> str:
    """Retrieve top chunks for this clause and format for evidence search (deduped vs full text)."""
    if not (rag_session_id and (rag_session_id or "").strip()):
        return ""
    try:
        from . import config as agent_config
        from . import rag as rag_mod
    except Exception:
        try:
            import agents.sample_agent.config as agent_config  # type: ignore
            import agents.sample_agent.rag as rag_mod  # type: ignore
        except Exception:
            return ""

    if not (
        getattr(agent_config, "ENABLE_RAG", False)
        and getattr(agent_config, "ENABLE_VECTOR_RETRIEVER", False)
        and getattr(agent_config, "ENABLE_AGENT1_RAG_CONTEXT", True)
    ):
        return ""

    k = max(2, int(getattr(agent_config, "AGENT1_RAG_TOP_K", 8)))
    max_chars = max(500, int(getattr(agent_config, "AGENT1_RAG_MAX_CHARS", 4500)))
    kw = " ".join(str(x) for x in (keywords or [])[:18] if x)
    ideal_snip = (ideal or "")[:520]
    query = f"{clause_name}\n{kw}\n{ideal_snip}".strip()
    if len(query) < 12:
        return ""

    try:
        hits = rag_mod.retrieve_for_session(rag_session_id.strip(), query, top_k=k)
    except Exception as exc:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Agent1 RAG retrieve skipped: %s", exc)
        return ""

    if not hits:
        return ""

    base_lower = (base_clause_text or "").lower()
    blocks: list[str] = []
    used = 0
    for doc, meta in hits:
        chunk = (doc or "").strip()
        if len(chunk) < 40:
            continue
        # Skip chunks already present in the clause-specific full text (dedupe).
        if len(chunk) >= 80 and chunk.lower()[: min(600, len(chunk))] in base_lower:
            continue
        fname = (meta or {}).get("file_name") or "policy"
        page = (meta or {}).get("page")
        dtype = (meta or {}).get("doc_type") or ""
        loc = f"p{page}" if page is not None else dtype or "chunk"
        header = f"[RAG | {fname} | {loc}]"
        piece = f"{header}\n{chunk}"
        if used + len(piece) + 2 > max_chars:
            remain = max_chars - used - len(header) - 4
            if remain < 120:
                break
            piece = f"{header}\n{chunk[:remain]}…"
        blocks.append(piece)
        used += len(piece) + 2
        if used >= max_chars:
            break

    if not blocks:
        return ""
    return "\n\n".join(blocks)


def _aero_page_near(text_before: str) -> int | None:
    matches = re.findall(r"\[PAGE\s+(\d+)\]", text_before or "", flags=re.IGNORECASE)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _aero_evidence_location_hint(contract_text: str, sentence: str) -> str:
    """Best-effort section / page hint before the evidence sentence."""
    if not contract_text or not sentence:
        return ""
    idx = contract_text.find(sentence)
    if idx < 0:
        idx = contract_text.lower().find(sentence.lower())
    if idx < 0:
        return ""
    before = contract_text[:idx]
    page = _aero_page_near(before)
    tail = before[max(0, len(before) - 1200) :]
    sm = SECTION_HINT_RE.search(tail)
    sec = sm.group(1) if sm else ""
    parts: list[str] = []
    if sec:
        parts.append(f"section {sec}")
    if page is not None:
        parts.append(f"page {page}")
    return ", ".join(parts)


def _aero_source_for_sentence(contract_text: str, sentence: str) -> str:
    """Infer nearest source marker for a selected evidence sentence."""
    if not contract_text or not sentence:
        return ""
    idx = contract_text.find(sentence)
    if idx < 0:
        idx = contract_text.lower().find(sentence.lower())
    if idx < 0:
        return ""
    before = contract_text[:idx]
    support_matches = list(re.finditer(r"\[SUPPORTING DOC:\s*([^\]]+)\]", before, flags=re.IGNORECASE))
    if support_matches:
        source = support_matches[-1].group(1).strip()
    else:
        rag_matches = list(re.finditer(r"\[RAG\s*\|\s*([^|]+)\s*\|", before, flags=re.IGNORECASE))
        source = rag_matches[-1].group(1).strip() if rag_matches else "Primary contract"
    page = _aero_page_near(before)
    return f"{source}, page {page}" if page else source


def _aero_paragraph_for_sentence(contract_text: str, sentence: str, limit: int = 1400) -> str:
    """Return bounded context around the selected sentence (avoid huge \\n\\n blocks swallowing unrelated articles)."""
    if not contract_text or not sentence:
        return (sentence or "").strip()
    idx = contract_text.find(sentence)
    if idx < 0:
        idx = contract_text.lower().find(sentence.lower())
    if idx < 0:
        return sentence.strip()
    half = max(280, min(limit // 2, 720))
    lo = max(0, idx - half)
    hi = min(len(contract_text), idx + len(sentence) + half)
    sub_lo = contract_text.rfind("\n\n", lo, idx)
    if sub_lo >= 0 and (idx - sub_lo) < 9000:
        lo = sub_lo + 2
    sub_hi = contract_text.find("\n\n", idx + len(sentence), hi)
    if sub_hi >= 0 and (sub_hi - idx) < 9000:
        hi = sub_hi
    page_breaks = [m.start() for m in re.finditer(r"\[PAGE\s+\d+\]", contract_text[lo:hi], flags=re.IGNORECASE)]
    if page_breaks and len(contract_text[lo:hi]) > limit + 400:
        rel = min(page_breaks, key=lambda p: abs(p - (idx - lo)))
        lo = max(lo, lo + rel - limit // 3)
        hi = min(hi, lo + limit + 200)
    chunk = " ".join(contract_text[lo:hi].split())
    if len(chunk) <= limit:
        return chunk.strip()
    si = chunk.lower().find(sentence.lower())
    if si < 0:
        return chunk[:limit].strip()
    w0 = max(0, si - limit // 3)
    w1 = min(len(chunk), w0 + limit)
    if w1 - w0 < limit:
        w0 = max(0, w1 - limit)
    return chunk[w0:w1].strip()


def _aero_has_near_negation(sentence_lower: str, anchors: list[str]) -> bool:
    """Detect negation close to an anchor keyword."""
    tokens = re.findall(r"\b[\w'-]+\b", sentence_lower or "")
    if not tokens:
        return False
    anchor_tokens = {a.lower() for a in anchors if a}
    for idx, tok in enumerate(tokens):
        if not any(tok in anchor or anchor in tok for anchor in anchor_tokens):
            continue
        window = " ".join(tokens[max(0, idx - 8) : min(len(tokens), idx + 9)])
        if any(neg in window for neg in _NEGATION_TOKENS):
            return True
    return False


def _aero_clause_candidate_boost(sentence_lower: str, clause_name: str | None) -> float:
    """Clause-specific boost for operative language over headings/peripheral mentions."""
    n = (clause_name or "").lower()
    boost = 0.0
    if "limitation of liability" in n or "consequential" in n:
        if "liable for any direct damage" in sentence_lower:
            boost += 6
        if "excluding any indirect" in sentence_lower or "consequential damages" in sentence_lower:
            boost += 4
        if "liability - insurance" in sentence_lower and len(sentence_lower.split()) <= 6:
            boost -= 5
    elif "firm price" in n:
        if "unit prices" in sentence_lower and ("firm" in sentence_lower or "not revisable" in sentence_lower):
            boost += 6
        if "price revision" in sentence_lower or "price adjustment" in sentence_lower:
            boost += 4
        if "firm period" in sentence_lower or "forecasted period" in sentence_lower:
            boost -= 4
    elif "dispute resolution" in n:
        if "commercial court of paris" in sentence_lower or "tribunal de commerce de paris" in sentence_lower:
            boost += 6
        if "mediation" in sentence_lower and "court" in sentence_lower:
            boost += 2
    elif "governing law" in n or "jurisdiction" in n:
        if "governed by french law" in sentence_lower or "governed by" in sentence_lower:
            boost += 6
        if "commercial court of paris" in sentence_lower or "exclusive jurisdiction" in sentence_lower:
            boost += 3
    elif "orders extending" in n:
        if "orders in progress" in sentence_lower and ("expiry" in sentence_lower or "termination" in sentence_lower):
            boost += 6
    elif "change orders" in n:
        if "all requests for changes" in sentence_lower and "written agreement" in sentence_lower:
            boost += 8
        if "technical proposal and commercial quote" in sentence_lower:
            boost += 6
        if "written agreement" in sentence_lower and ("change" in sentence_lower or "procedure" in sentence_lower):
            boost += 6
        if "change order" in sentence_lower or "change in law" in sentence_lower:
            boost += 5
        if "forecasted period" in sentence_lower or "delivery batch" in sentence_lower:
            boost -= 4
    return boost


def _aero_top_evidence(
    contract_text: str,
    keywords: list[str],
    top_n: int = 3,
    *,
    anchor_terms: list[str] | None = None,
    reserved_sentences: set[str] | None = None,
    clause_name: str | None = None,
    search_boost_spans: Sequence[Tuple[int, int]] | None = None,
) -> list[dict]:
    """Return top evidence sentences. Requires at least one anchor term if provided; prefers unreserved sentences for primary."""
    candidates = _aero_sentence_candidates(contract_text)
    scored: list[dict] = []
    seen: set[str] = set()
    reserved = reserved_sentences or set()

    for sent in candidates:
        normalized = " ".join(sent.split()).strip()
        if not normalized or len(normalized) < 25:
            continue
        if len(normalized.split()) <= 4:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)

        # Exclude cross-clause pollution (e.g. "15 days of receipt" for LD)
        if clause_name and _aero_evidence_excluded_for_clause(lowered, clause_name):
            continue

        # Must match at least one keyword
        score = sum(1 for kw in (keywords or []) if kw and kw.lower() in lowered)
        if score <= 0:
            continue

        # If anchor terms required, sentence must contain at least one
        if anchor_terms:
            has_anchor = any(a.lower() in lowered for a in anchor_terms if a)
            if not has_anchor:
                continue

        is_reserved = lowered in reserved
        negation_flag = _aero_has_near_negation(lowered, anchor_terms or keywords or [])
        adjusted_score = (score + _aero_clause_candidate_boost(lowered, clause_name)) * (0.5 if negation_flag else 1.0)
        try:
            from .contract_search import sentence_overlaps_spans

            if search_boost_spans and sentence_overlaps_spans(normalized, contract_text, search_boost_spans):
                adjusted_score += 4.0
        except Exception:
            pass
        scored.append({
            "text": normalized,
            "paragraph": _aero_paragraph_for_sentence(contract_text, normalized),
            "source": _aero_source_for_sentence(contract_text, normalized),
            "score": adjusted_score + (10 if not is_reserved else 0),  # Prefer unreserved as primary
            "_raw_score": adjusted_score,
            "_negation_flag": negation_flag,
        })

    scored.sort(key=lambda x: (x["score"], x.get("_raw_score", 0), len(x["text"])), reverse=True)
    try:
        from . import config as agent_config
        from .cross_encoder_rerank import rerank_indices_by_query

        if getattr(agent_config, "ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK", False) and len(scored) > 8:
            model_name = (getattr(agent_config, "EVIDENCE_CROSS_ENCODER_MODEL", "") or "").strip()
            if model_name:
                n_pool = min(36, len(scored))
                head = scored[:n_pool]
                tail = scored[n_pool:]
                texts = [x["text"] for x in head]
                q_parts = [s for s in [(clause_name or "").strip(), " ".join(keywords or [])] if s]
                q = " ".join(q_parts)[:800]
                order = rerank_indices_by_query(q, texts, model_name=model_name)
                scored = [head[i] for i in order] + tail
    except Exception:
        pass
    return scored[: max(1, top_n)]


def _aero_confidence(matches: list[dict], keywords: list[str], out_of_scope: bool) -> tuple[float, str]:
    if out_of_scope:
        return 0.2, "Low"
    if not matches:
        return 0.15, "Low"
    keyword_count = max(1, len(set([k.lower() for k in (keywords or []) if str(k).strip()])))
    best_score = float(matches[0].get("_raw_score") or matches[0].get("score") or 0.0)
    best_coverage = min(1.0, best_score / keyword_count)
    breadth = min(1.0, len(matches) / 3.0)
    confidence = 0.7 * best_coverage + 0.3 * breadth
    if confidence >= 0.75:
        return confidence, "High"
    if confidence >= 0.45:
        return confidence, "Medium"
    return confidence, "Low"


def _aero_is_out_of_scope(contract_text: str, clauses: list[dict]) -> bool:
    text = (contract_text or "").lower()
    if not text:
        return False
    out_signals = [
        "non-disclosure agreement",
        "confidential disclosure agreement",
        "receiving party",
        "disclosing party",
        "confidentiality period",
    ]
    has_out = any(s in text for s in out_signals)
    if not has_out:
        return False
    scope_hits = 0
    for clause in clauses:
        kws = clause.get("keywords") or []
        if any(str(k).lower() in text for k in kws[:3]):
            scope_hits += 1
    return scope_hits < 3


def _aero_parse_percent(token_text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", token_text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _aero_parse_all_percents(token_text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"(\d+(?:\.\d+)?)\s*%", token_text or ""):
        try:
            values.append(float(raw))
        except Exception:
            continue
    return values


def _aero_concise_mitigation(name: str, risk_level: str, risk_trigger: str) -> str:
    """Return short, actionable mitigation bullets — NOT the full GB ideal clause text."""
    n = (name or "").lower()
    rl = risk_level or "Amber"

    if "limitation of liability" in n or "consequential" in n:
        if rl == "Red":
            return (
                "1) Add explicit liability cap at 100% of agreement/SOW value. "
                "2) Open clause with 'notwithstanding anything to the contrary'. "
                "3) Expressly exclude consequential, indirect, and lost-profit damages. "
                "4) List carve-outs (criminal acts, IP breach, gross negligence). Route to ERMC."
            )
        return (
            "1) Clarify the liability cap amount (target 100% of agreement value). "
            "2) Add consequential/indirect damage exclusion if absent. "
            "3) Confirm 'notwithstanding' opening and list standard carve-outs. Route to Legal."
        )

    if "governing law" in n or "jurisdiction" in n or "choice of law" in n:
        return (
            "1) Specify approved governing law (India preferred; English law with approved seat if cross-border). "
            "2) Align jurisdiction to Mumbai or agreed seat. "
            "3) Remove any conflicting or unapproved governing-law references. Route to BU Head."
        )

    if "dispute resolution" in n:
        if rl == "Amber" and "arbitration" not in risk_trigger.lower():
            return (
                "1) Insert arbitration-first clause before court proceedings. "
                "2) Specify: seat, language (English), number of arbitrators, appointing rules. "
                "3) Add optional mediation step before arbitration. Route to Legal."
            )
        return (
            "1) Define arbitration seat and governing language explicitly. "
            "2) Specify arbitrator appointment mechanism and applicable rules (1996 Act / SIAC / LCIA / ICC). "
            "3) Confirm mediation precondition if required. Route to Legal."
        )

    if "firm price" in n:
        if rl == "Red":
            return (
                "1) Insert firm/fixed pricing clause for the agreement term. "
                "2) Allow escalation ONLY for: (i) signed change orders, (ii) change in law/taxes, "
                "(iii) documented raw-material cost changes. "
                "3) Require objective evidence for all escalation requests. Route to ERMC."
            )
        return (
            "1) Confirm firm/fixed price language for the full term. "
            "2) Tighten escalation triggers: restrict to change orders, change in law, and RM cost changes with evidence. "
            "3) Remove open-ended escalation clauses. Route to ERMC if term > 2 years or value > 25 Cr."
        )

    if "force majeure" in n:
        if rl == "Red":
            return (
                "1) Remove economic/financial hardship and cash-flow shortfall from FM events. "
                "2) Add payment carve-out: FM does not excuse payment for goods already delivered. "
                "3) Define maximum FM suspension period (e.g., 90/180 days) before termination right triggers. Route to Legal."
            )
        return (
            "1) Add explicit payment carve-out: FM does not relieve obligation to pay for delivered goods/services. "
            "2) Exclude economic hardship from FM trigger events. "
            "3) Align FM event list with GB standard. Route to Legal."
        )

    if "liquidated damages" in n:
        if rl == "Red":
            return (
                "1) Reduce LD cap to maximum 5% of delayed-goods value (not total order value). "
                "2) Change basis from order/contract value to value of delayed goods only. "
                "3) Remove 'in addition to' or stacking language with other Chapter remedies. "
                "4) Add exclusive-remedy framing for delay. Route to ERMC (division thresholds apply)."
            )
        return (
            "1) Confirm LD is calculated on delayed-goods value basis (not total order). "
            "2) Cap LD at 5% maximum. "
            "3) Add exclusive-remedy clause for delay. Route to ERMC if LD cap exceeds division threshold."
        )

    if "orders extending" in n or "beyond termination" in n:
        if rl == "Red":
            return (
                "1) Insert default rule: termination/expiry ends all in-effect orders. "
                "2) Allow carve-out only via mutually signed addendum. "
                "3) Add repricing rights for any agreed residual-period orders. Route to Legal."
            )
        return (
            "1) Add explicit termination default: orders terminate with the agreement unless separately agreed. "
            "2) Require signed addendum for any post-term order continuation. "
            "3) Include repricing mechanism for residual period. Route to Legal."
        )

    if "quantity protection" in n:
        return (
            "1) Add reimbursement clause: if delivered quantity deviates >+/-20% from forecast, "
            "GB is reimbursed at actuals (RM, WIP, FG) on documentary evidence. "
            "2) Specify lead-time firming: forecasts within lead time convert to firm POs. "
            "3) Confirm forecasts are non-binding and do not trigger capex/procurement. Route to Legal."
        )

    if "inventory" in n:
        if "notification" in risk_trigger.lower() or "notify" in risk_trigger.lower():
            return (
                "1) Verify separately whether any clause in the contract imposes inventory-holding obligations. "
                "2) If inventory holding IS required: cap obligation to maximum 4 weeks of RM/FG, "
                "within lead time only, against non-binding forecasts. "
                "3) If no holding obligation: confirm and document as Green. Route to Legal for confirmation."
            )
        if rl == "Red":
            return (
                "1) Cap inventory holding obligation to maximum 4 weeks of RM/FG. "
                "2) Restrict obligation to forecasts within the confirmed lead time only. "
                "3) Ensure non-binding forecasts do not trigger procurement/capex. Route to Legal."
            )
        return (
            "1) Clarify whether inventory holding against non-binding forecasts is required. "
            "2) If yes: cap at 4 weeks maximum, within lead time only. "
            "3) Confirm non-binding forecasts do not trigger procurement obligations. Route to Legal."
        )

    if "change order" in n:
        if rl == "Red":
            return (
                "1) Add signed change-order precondition: no work commences without a signed CO. "
                "2) CO must capture price and schedule impact before execution. "
                "3) GB entitled to equitable adjustment at actuals: RM, tooling/NRE, FAI, logistics, schedule relief. Route to Legal."
            )
        return (
            "1) Add signed CO gate before any scope change is executed. "
            "2) Include equitable adjustment clause covering RM, tooling/NRE, FAI costs, and schedule relief. "
            "3) Specify that no change is binding without both parties' signatures. Route to Legal."
        )

    if "aerospace business critical" in n:
        return (
            "Align aerospace-specific terms (technical scope, specifications, warranties, delivery milestones, IP) "
            "with GB legal playbook and Aerospace Playbook. Route to Legal for full review."
        )

    # Generic fallback (should rarely be reached)
    return (
        f"Align clause to GB legal policy position. "
        f"Risk: {risk_trigger} Route to Legal for targeted redline."
    )


def _aero_concise_change(name: str, risk_level: str) -> str:
    """Return a short 'required change' narrative for the counterfactual column."""
    n = (name or "").lower()
    rl = risk_level or "Amber"

    if "limitation of liability" in n or "consequential" in n:
        return "Add 100% liability cap + consequential damage exclusion + 'notwithstanding' opening."
    if "governing law" in n or "jurisdiction" in n or "choice of law" in n:
        return "Align to approved jurisdiction (India/Mumbai or agreed seat)."
    if "dispute resolution" in n:
        return "Insert arbitration-first mechanism with seat, language, and rules defined."
    if "firm price" in n:
        return "Restrict escalation to: signed change orders, change in law, and documented RM cost changes only."
    if "force majeure" in n:
        return "Add payment carve-out for delivered goods; remove economic/financial hardship from FM events."
    if "liquidated damages" in n:
        return "Cap LD at 5% of delayed-goods value; remove stacking language; add exclusive-remedy framing."
    if "orders extending" in n or "beyond termination" in n:
        return "Add termination-ends-orders default + signed-addendum carve-out + repricing right."
    if "quantity protection" in n:
        return "Add +/-20% deviation reimbursement + lead-time firming to firm POs."
    if "inventory" in n:
        return "Verify holding obligations; if required, cap at 4 weeks within lead time."
    if "change order" in n:
        return "Add signed CO precondition + equitable adjustment at actuals (RM, NRE, FAI, logistics)."
    if "aerospace business critical" in n:
        return "Map aerospace-specific terms to GB Aerospace Playbook and route to Legal."
    return "Align to GB ideal position for this clause; route to Legal for targeted redline."


def _aero_assess_clause(name: str, evidence_text: str, ideal: str, approval: str) -> dict:
    text = (evidence_text or "").lower()
    risk_level = "Amber"
    risk_trigger = "Clause present but partially aligned to GB legal position."
    rationale = "Clause text is detected but does not fully satisfy all policy parameters."

    if "Limitation of Liability" in name:
        pct = _aero_parse_percent(text or "")
        has_unlimited = "unlimited" in text or "not excluded" in text
        has_conseq_exclusion = ("consequential" in text or "indirect" in text) and (
            "exclude" in text or "excluded" in text
        )
        if has_unlimited or (pct is not None and pct > 100):
            risk_level = "Red"
            risk_trigger = "Liability cap exceeds 100% and/or consequential exposure is not properly excluded."
            rationale = "Liability exposure appears above GB cap tolerance."
        elif pct == 100 and has_conseq_exclusion:
            risk_level = "Green"
            risk_trigger = "Liability cap and consequential/indirect exclusion appear aligned."
            rationale = "Core liability controls are close to GB ideal language."
        else:
            risk_level = "Amber"
            risk_trigger = "Liability clause exists but cap/exclusion drafting is incomplete."
            rationale = "Liability wording needs tightening to avoid open-ended exposure."

    elif "Governing Law" in name or "Jurisdiction" in name:
        if "india" in text and "mumbai" in text:
            risk_level = "Green"
            risk_trigger = "Approved law/jurisdiction combination detected (India/Mumbai)."
            rationale = "Governing law clause appears within approved combinations."
        elif "govern" in text or "jurisdiction" in text or "court" in text:
            risk_level = "Amber"
            risk_trigger = "Governing law terms exist but approved combination is not explicit."
            rationale = "Deviation may require BU Head/legal review."

    elif name == "Dispute Resolution":
        has_arb = "arbitration" in text
        has_details = any(k in text for k in ["seat", "language", "tribunal", "rules", "siac", "lcia", "icc"])
        if has_arb and has_details:
            risk_level = "Green"
            risk_trigger = "Arbitration framework with seat/language/rules is present."
            rationale = "Dispute resolution structure is close to GB preferred pattern."
        elif has_arb:
            risk_level = "Amber"
            risk_trigger = "Arbitration is present but lacks full process parameters."
            rationale = "Clause needs explicit seat/language/rules/tribunal details."
        else:
            risk_level = "Amber"
            risk_trigger = "Dispute mechanism exists but arbitration-first structure is unclear."
            rationale = "Legal drafting should prioritize arbitration with clear mechanics."

    elif name == "Firm Price":
        has_fixed = any(k in text for k in ["firm", "fixed"])
        has_limited_triggers = any(k in text for k in ["change order", "change in law", "raw material"])
        if has_fixed and has_limited_triggers:
            risk_level = "Green"
            risk_trigger = "Firm/fixed pricing with controlled escalation triggers is present."
            rationale = "Pricing structure appears materially aligned."
        elif has_fixed:
            risk_level = "Amber"
            risk_trigger = "Firm/fixed pricing exists but escalation controls are not fully bounded."
            rationale = "Unbounded escalation logic can create commercial leakage."

    elif name == "Force Majeure":
        has_hardship = any(k in text for k in ["economic hardship", "cash-flow", "cash flow", "financial hardship"])
        if has_hardship:
            risk_level = "Red"
            risk_trigger = "Force majeure improperly includes economic/cash-flow hardship."
            rationale = "GB position excludes economic hardship as FM grounds."
        elif "force majeure" in text:
            risk_level = "Amber"
            risk_trigger = "Force majeure exists but payment carve-out/economic exclusion is incomplete."
            rationale = "FM language should preserve payment obligations for delivered goods/services."

    elif name == "Liquidated Damages":
        pct = _aero_parse_percent(text or "")
        all_pcts = _aero_parse_all_percents(text or "")
        has_weekly_rate = "week" in text and any(v > 0.5 for v in all_pcts)
        has_high_cap = any(v > 5.0 for v in all_pcts) and ("cap" in text or "capped" in text or "maximum" in text)
        has_total_value_basis = "total contract value" in text or "total value" in text
        has_additive_remedy = "in addition to other remedies" in text
        if has_total_value_basis or has_additive_remedy or has_weekly_rate or has_high_cap or (pct is not None and pct > 5.0):
            risk_level = "Red"
            risk_trigger = "LD appears penalty-like (high cap/total-value basis/additive remedies)."
            rationale = (
                "GB LD position expects delayed-value basis, weekly rate around 0.5%, "
                "controlled cap (~5%), and exclusive-remedy framing."
            )
        elif any(k in text for k in ["delayed value", "exclusive remedy", "0.5%", "5%"]):
            risk_level = "Green"
            risk_trigger = "LD terms resemble delayed-value basis with bounded cap."
            rationale = "LD drafting appears near preferred commercial guardrails."
        else:
            risk_level = "Amber"
            risk_trigger = "LD exists but basis/cap/exclusive-remedy framing is unclear."
            rationale = "Needs legal cleanup to avoid penalty interpretation."

    elif name == "Orders Extending Beyond Termination":
        has_continue_all = "continue" in text and "orders" in text and "termination" in text
        has_repricing = "repricing" in text or "renegotiat" in text
        if has_continue_all and not has_repricing:
            risk_level = "Red"
            risk_trigger = "Post-termination order continuation is broad without repricing protection."
            rationale = "Commercial exposure persists beyond termination without pricing safeguards."
        elif has_continue_all and has_repricing:
            risk_level = "Amber"
            risk_trigger = "Continuation + repricing concept exists but termination default may still be too broad."
            rationale = "Tighten default rule to terminate in-effect orders unless expressly agreed."
        else:
            risk_level = "Amber"
            risk_trigger = "Termination-overhang mechanics are not explicit."
            rationale = "Clause needs clear default + repricing mechanism."

    elif name == "Quantity Protection":
        has_no_reimburse = "no reimbursement" in text or "without liability" in text
        has_plus_minus_20 = "+/-20%" in text or "plus or minus 20%" in text or "20%" in text
        if has_no_reimburse and has_plus_minus_20:
            risk_level = "Red"
            risk_trigger = "Forecast deviations are non-compensable beyond +/-20%."
            rationale = "GB position requires reimbursement at actuals beyond deviation threshold."
        elif "forecast" in text:
            risk_level = "Amber"
            risk_trigger = "Forecast terms exist but firm-PO conversion/reimbursement triggers are incomplete."
            rationale = "Add lead-time firming and reimbursement mechanics."

    elif name == "Inventory Requirements":
        pct = _aero_parse_percent(text or "")
        weeks = None
        wm = re.search(r"(\d+)\s*weeks?", text)
        if wm:
            weeks = int(wm.group(1))

        # Distinguish between a genuine inventory-holding obligation and a notification clause.
        # If evidence is purely about the supplier NOTIFYING the purchaser about forecast changes
        # (e.g. "shall inform within X working days") rather than holding inventory,
        # the risk profile is materially different — likely favorable to GB/Godrej.
        _has_hold_obligation = any(k in text for k in [
            "maintain inventory", "hold stock", "keep in stock", "safety stock",
            "buffer stock", "maintain stock", "maintain raw material", "maintain rm",
            "maintain finished good", "maintain fg", "shall maintain", "shall keep",
            "shall hold", "minimum stock", "stock level", "stocking requirement",
        ])
        _is_notification_only = any(k in text for k in [
            "shall inform", "shall notify", "shall communicate", "acknowledgment of receipt",
            "working days", "inform the sender", "inform the purchaser",
        ]) and not _has_hold_obligation

        if _is_notification_only:
            risk_level = "Amber"
            risk_trigger = (
                "Evidence found is a supplier notification clause (inform purchaser of forecast changes), "
                "not an inventory-holding obligation. Actual inventory-holding requirements need explicit verification."
            )
            rationale = (
                "The extracted text relates to notification/communication obligations, not to inventory stocking. "
                "Verify whether any separate clause imposes inventory-holding obligations against non-binding forecasts. "
                "If no holding obligation exists, this position may be Green for GB."
            )
        elif weeks is not None and weeks > 4:
            risk_level = "Red"
            risk_trigger = f"Inventory obligation appears high ({weeks} weeks) against non-binding forecasts."
            rationale = "GB policy typically caps exposure to ~4 weeks once forecast enters lead time."
        elif weeks is not None and weeks <= 4:
            risk_level = "Green"
            risk_trigger = "Inventory cap appears within expected threshold."
            rationale = "Inventory exposure appears broadly controlled."
        else:
            risk_level = "Amber"
            risk_trigger = "Inventory clause exists but cap/lead-time controls are unclear."
            rationale = "Specify weeks cap and lead-time conditions."

    elif name == "Change Orders Procedure":
        has_email_only = "email approval" in text or "can be completed later" in text
        has_signed_precondition = "signed change order" in text and "no change" in text
        if has_email_only:
            risk_level = "Red"
            risk_trigger = "Changes can proceed before signed change order."
            rationale = "Execution-before-signoff weakens commercial and claims control."
        elif has_signed_precondition:
            risk_level = "Green"
            risk_trigger = "Signed change-order precondition with time/price capture is present."
            rationale = "Change governance appears aligned to GB policy."
        else:
            risk_level = "Amber"
            risk_trigger = "Change-order flow is present but signature/equitable-adjustment controls are incomplete."
            rationale = "Add explicit signed CO gate and pricing/time adjustment mechanics."

    risk_shift = "Maintain Green"
    if risk_level == "Red":
        risk_shift = "Red → Amber/Green"
    elif risk_level == "Amber":
        risk_shift = "Amber → Green"

    # Build a concise, clause-specific mitigation (not a repeat of the full ideal text).
    mitigation = _aero_concise_mitigation(name, risk_level, risk_trigger)
    # Build a concise counterfactual that focuses on the gap, not the full ideal clause text.
    counterfactual = (
        f"Gap: {risk_trigger} "
        f"Change needed: {_aero_concise_change(name, risk_level)} "
        f"Expected shift: {risk_shift}. Approval: {approval}."
    )
    return {
        "risk_level": risk_level,
        "risk_rationale": rationale,
        "risk_trigger": risk_trigger,
        "mitigation_recommendation": mitigation,
        "counterfactual": counterfactual,
        "expected_risk_shift": risk_shift,
    }


def detect_referenced_supporting_docs(contract_text: str) -> list[dict]:
    """
    Scan a contract for references to supporting documents (Appendices, Annexures, Schedules,
    NDAs, GTCs, STCs, and other named attachments). Returns a list of discovered references.

    Each entry: { "type": str, "label": str, "context": str }
    """
    text = contract_text or ""
    found: dict[str, dict] = {}  # keyed by normalised label to deduplicate

    patterns = [
        # Appendix / Annex / Annexure + number/letter (stop at whitespace or punctuation)
        (r"(?i)\b(?:appendix|annex(?:ure)?)\s+([0-9]+(?:bis|ter|[A-Za-z])?(?:\.[0-9]+)*|[A-Z])\b", "Appendix/Annex"),
        # Schedule with number or single letter
        (r"(?i)\bschedule\s+([0-9]+[A-Za-z]?|[A-Z])\b", "Schedule"),
        # Exhibit with number or single letter
        (r"(?i)\bexhibit\s+([0-9]+[A-Za-z]?|[A-Z])\b", "Exhibit"),
        # NDA / Non-Disclosure Agreement references
        (r"(?i)\b(non[\-\s]?disclosure\s+agreement|NDA|confidentiality\s+agreement)\b", "NDA/Confidentiality"),
        # General Terms and Conditions
        (r"(?i)\b(general\s+(?:terms\s+and\s+)?conditions?|GTC(?:s)?)\b", "General Terms & Conditions"),
        # Special/Specific Terms and Conditions
        (r"(?i)\b(special\s+(?:terms\s+and\s+)?conditions?|STC(?:s)?|specific\s+terms)\b", "Special Terms & Conditions"),
        # Quality Assurance Plan / QAP
        (r"(?i)\b(quality\s+assurance\s+plan|QAP|quality\s+plan)\b", "Quality Assurance Plan"),
        # Technical Specifications
        (r"(?i)\b(technical\s+specification[s]?|spec(?:ification)?s?\s+document)\b", "Technical Specifications"),
        # Statements of Work
        (r"(?i)\b(statement\s+of\s+work|SOW)\b", "Statement of Work"),
        # Price schedules / rate cards
        (r"(?i)\b(price\s+schedule|rate\s+card|fee\s+schedule)\b", "Price Schedule"),
    ]

    for pattern, doc_type in patterns:
        for m in re.finditer(pattern, text):
            raw = m.group(0).strip()
            # Build a normalised key
            group1 = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else ""
            if group1 and doc_type in ("Appendix/Annex", "Schedule", "Exhibit"):
                label = f"{doc_type} {group1}"
            else:
                label = raw.title()

            norm_key = re.sub(r"\s+", " ", label.lower()).strip()
            if norm_key in found:
                continue

            # Grab a short context window around the match
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 80)
            ctx = re.sub(r"\s+", " ", text[start:end]).strip()

            found[norm_key] = {
                "type": doc_type,
                "label": label,
                "context": ctx,
            }

    return sorted(found.values(), key=lambda x: x["label"])


def _normalize_doc_match_key(value: str) -> str:
    lowered = (value or "").lower().replace("appendix/annex", "appendix annex")
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _extract_appendix_style_token(ref_label: str) -> str | None:
    """Return the index token for Appendix/Annex/Schedule/Exhibit refs, or None."""
    nl = _normalize_doc_match_key(ref_label or "")
    if not nl:
        return None
    m = re.search(
        r"\b(?:appendix|annex(?:ure)?|schedule|exhibit)(?:\s+(?:appendix|annex(?:ure)?))*\s+"
        r"([0-9]+(?:\.[0-9]+)*|[a-z])\b",
        nl,
        flags=re.I,
    )
    return m.group(1).lower() if m else None


def _filename_matches_appendix_token(fname_norm: str, token: str) -> bool:
    """
    True if the filename carries this appendix/annex/schedule/exhibit index in an anchored way:
    keyword + spaced index, or annex{token}/appendix{token} style (digits must not match as part of
    larger numbers or unrelated tokens like v1 / year digits).
    """
    if not token:
        return False
    compact_fn = re.sub(r"\s+", "", fname_norm)
    kw_alt = "appendix|annex(?:ure)?|schedule|exhibit"
    # Spaced filename: keyword as its own word, then the token (digit tokens not glued into longer nums).
    if re.search(
        rf"(?i)(?<![a-z0-9])(?:{kw_alt})\s+{re.escape(token)}(?![0-9a-z])",
        fname_norm,
    ):
        return True
    # Compact: appendix3, annex_3, annex-3 — digit tokens must not extend into further digits.
    for kw in ("appendix", "annex", "annexure", "schedule", "exhibit"):
        if token.isdigit():
            if re.search(rf"(?i){re.escape(kw)}(?:_|-|\.|){re.escape(token)}(?!\d)", compact_fn):
                return True
            if re.search(rf"(?i){re.escape(kw)}{re.escape(token)}(?!\d)", compact_fn):
                return True
        else:
            if re.search(rf"(?i){re.escape(kw)}(?:_|-|\.|)?{re.escape(token)}(?![a-z0-9])", compact_fn):
                return True
    return False


def referenced_doc_matches_upload(ref_label: str, uploaded_filename: str) -> bool:
    """Fuzzy match between a contract reference (e.g. Appendix 3) and an uploaded file name."""
    fname_norm = _normalize_doc_match_key(uploaded_filename)
    label_lc = _normalize_doc_match_key(ref_label)
    if not fname_norm or not label_lc:
        return False
    if label_lc in fname_norm or fname_norm in label_lc:
        return True
    tok = _extract_appendix_style_token(ref_label)
    if tok is not None:
        return _filename_matches_appendix_token(fname_norm, tok)
    label_parts = [p for p in label_lc.split() if p not in {"appendix", "annex", "annexure", "schedule", "exhibit"}]
    if label_parts and all(part in fname_norm for part in label_parts if part):
        return True
    return False


def _aero_build_legal_context(contract_text: str) -> dict:
    try:
        from agents.sample_agent.legal_preprocessor import build_legal_context

        return build_legal_context(contract_text)
    except Exception:
        return {"defined_terms": {}, "cross_references": [], "jurisdiction_entities": []}


def _aero_definition_context(evidence: str, defined_terms: dict[str, str], limit: int = 240) -> str:
    """Return compact definitions for capitalized terms found in evidence."""
    if not evidence or not defined_terms:
        return ""
    parts = []
    for term, definition in defined_terms.items():
        if term and term in evidence:
            parts.append(f"{term}: {definition}")
        if len(" | ".join(parts)) >= limit:
            break
    return " | ".join(parts)[:limit]


def run_aerospace_clause_extraction(
    contract_text: str,
    knowledge_payload: dict,
    *,
    supporting_doc_texts: dict[str, str] | None = None,
    uploaded_filenames: list[str] | None = None,
    rag_session_id: str | None = None,
) -> list[dict]:
    """
    Deterministic, Aerospace-specific extraction.
    Input:
      - contract_text: extracted upload text (primary contract)
      - knowledge_payload: parsed JSON knowledge with `clauses` list
      - supporting_doc_texts: optional dict of {filename: text} for uploaded supporting docs
      - uploaded_filenames: list of all uploaded file names in the session
      - rag_session_id: when set with RAG enabled, per-clause vector retrieval augments clause_text
    Output:
      - list of normalized rows for table rendering, with supporting-doc metadata on row[0]
    """
    clauses = (knowledge_payload or {}).get("clauses") or []
    if not isinstance(clauses, list):
        clauses = []

    out_of_scope = _aero_is_out_of_scope(contract_text, clauses)
    out_scope_evidence = "CONFIDENTIAL DISCLOSURE AGREEMENT" if out_of_scope else ""
    legal_context = _aero_build_legal_context(contract_text)
    defined_terms = legal_context.get("defined_terms") or {}

    # Detect all supporting documents referenced in the contract text
    referenced_docs = detect_referenced_supporting_docs(contract_text)

    # Determine which referenced docs are missing from the uploads (fuzzy filename match).
    missing_docs: list[dict] = []
    for ref in referenced_docs:
        matched = any(
            referenced_doc_matches_upload(ref["label"], n or "") for n in (uploaded_filenames or []) if n
        )
        ref["uploaded"] = matched
        if not matched:
            missing_docs.append(ref)

    if rag_session_id and (rag_session_id or "").strip():
        try:
            from . import config as _rag_cfg
            from . import rag as _rag_mod
        except Exception:
            try:
                import agents.sample_agent.config as _rag_cfg  # type: ignore
                import agents.sample_agent.rag as _rag_mod  # type: ignore
            except Exception:
                _rag_cfg = None  # type: ignore
                _rag_mod = None  # type: ignore
        if _rag_cfg and _rag_mod:
            if (
                getattr(_rag_cfg, "ENABLE_RAG", False)
                and getattr(_rag_cfg, "ENABLE_VECTOR_RETRIEVER", False)
                and getattr(_rag_cfg, "ENABLE_AGENT1_RAG_CONTEXT", True)
            ):
                try:
                    _rag_mod.ensure_poc_indexed()
                except Exception:
                    pass

    allowed_supporting: set[str] = set()
    for ref in referenced_docs:
        if not ref.get("uploaded"):
            continue
        for fname in (supporting_doc_texts or {}).keys():
            if referenced_doc_matches_upload(ref["label"], fname):
                allowed_supporting.add(fname)
    allowed_supporting_frozen = frozenset(allowed_supporting)
    referenced_gate = bool(referenced_docs)

    reserved_primary: set[str] = set()
    rows: list[dict] = []
    quote_checks_passed = 0
    quote_checks_failed = 0
    try:
        from .contract_search import collect_keyword_spans, verify_evidence_quote
    except Exception:
        try:
            from agents.sample_agent.contract_search import collect_keyword_spans, verify_evidence_quote  # type: ignore
        except Exception:
            collect_keyword_spans = None  # type: ignore
            verify_evidence_quote = None  # type: ignore

    for idx, clause in enumerate(clauses, start=1):
        name = str(clause.get("name") or f"Clause {idx}")
        keywords = [str(k) for k in (clause.get("keywords") or [])]
        anchor = _aero_anchor_for_clause(name)
        ideal = str(clause.get("ideal_position") or "")
        approval = str(clause.get("approval_path") or "Legal team in consultation with Business Team.")

        boost_spans: Sequence[Tuple[int, int]] = ()
        if collect_keyword_spans is not None:
            boost_spans = tuple(collect_keyword_spans(contract_text or "", keywords))

        # Supporting schedules + RAG enrich retrieval prompts for policy alignment, but evidence
        # sentences MUST be chosen only from the primary agreement text so DOCX redline anchoring
        # can find verbatim spans in the exported primary file (supporting uploads are never redlined).
        clause_text_for_supplements = _aero_build_clause_text(
            contract_text,
            supporting_doc_texts,
            name,
            allowed_supporting_names=allowed_supporting_frozen if referenced_gate else None,
        )
        rag_extra = _aero_rag_supplement(
            rag_session_id, name, keywords, ideal, clause_text_for_supplements
        )
        if rag_extra and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Agent1 aerospace: RAG supplement for %s is %d chars (not merged into quoted evidence)",
                name[:48],
                len(rag_extra),
            )
        # Intentionally do not merge RAG/supporting into the sentence corpus used for quotes.
        matches = _aero_top_evidence(
            contract_text,
            keywords,
            top_n=3,
            anchor_terms=anchor if anchor else None,
            reserved_sentences=reserved_primary,
            clause_name=name,
            search_boost_spans=boost_spans or None,
        )
        if matches:
            reserved_primary.add(matches[0]["text"].strip().lower())
        evidence = matches[0]["text"] if matches else ""
        evidence_paragraph = matches[0].get("paragraph", evidence) if matches else ""
        detected = "Yes" if matches else "Unclear"
        risk_level = "Amber"
        risk_rationale = "Clause wording is not clearly present in uploaded text."
        risk_trigger = "Clause text not found with sufficient confidence."
        mitigation_recommendation = _aero_concise_mitigation(name, "Amber", "Clause text not found with sufficient confidence.")
        counterfactual = (
            f"Gap: Clause not clearly identified in uploaded text. "
            f"Change needed: {_aero_concise_change(name, 'Amber')} "
            "Expected shift: Amber → Green after legal validation."
        )
        expected_risk_shift = "Amber -> Green"
        confidence_score, confidence_label = _aero_confidence(matches, keywords, out_of_scope=False)
        if evidence:
            assessment = _aero_assess_clause(name, " | ".join([m.get("text", "") for m in matches]), ideal, approval)
            risk_level = assessment["risk_level"]
            risk_rationale = assessment["risk_rationale"]
            risk_trigger = assessment["risk_trigger"]
            mitigation_recommendation = assessment["mitigation_recommendation"]
            counterfactual = assessment["counterfactual"]
            expected_risk_shift = assessment["expected_risk_shift"]

        if out_of_scope:
            detected = "Unclear"
            risk_level = "Amber"
            evidence = out_scope_evidence
            risk_trigger = "Document appears outside supply-contract POC scope."
            risk_rationale = (
                "Document type appears out-of-scope for this POC (supply-contract clauses). "
                "Route for legal review before relying on this assessment."
            )
            mitigation_recommendation = (
                "Convert/review against supply-contract clause format before policy assessment."
            )
            counterfactual = (
                "Current issue: out-of-scope agreement type for this POC. "
                "Required change: provide supply-contract clause text for this position. "
                "Expected shift: Amber -> Assessable with clause-level confidence."
            )
            expected_risk_shift = "Amber -> Assessable"

        snippet_parts: list[str] = []
        if matches:
            cap_each = 520
            for m in matches[:3]:
                src = (m.get("source") or "").strip()
                sent = (m.get("text") or "").strip()
                para = (m.get("paragraph") or sent).strip()
                base = para if len(para) >= min(len(sent) + 25, 95) else sent
                base = " ".join(base.split())
                if len(base) > cap_each:
                    base = base[: cap_each - 1] + "…"
                def_ctx = _aero_definition_context(m.get("paragraph", "") or m.get("text", ""), defined_terms)
                extra = f" [Definitions: {def_ctx}]" if def_ctx else ""
                if src:
                    snippet_parts.append(f"{base} [Source: {src}]{extra}")
                else:
                    snippet_parts.append(f"{base}{extra}")
        evidence_snippet_val = (
            " | ".join(snippet_parts) if snippet_parts else (evidence or "No direct matching clause text found.")
        )
        if len(evidence_snippet_val) > 2000:
            evidence_snippet_val = evidence_snippet_val[:1999] + "…"

        evidence_quote_val = ""
        if matches and not out_of_scope:
            evidence_quote_val = (matches[0].get("text") or "").strip()
        source_raw = _aero_source_for_sentence(contract_text, evidence_quote_val) if evidence_quote_val else ""
        ev_source_norm = "primary"
        if source_raw:
            low = source_raw.lower()
            if "primary contract" not in low and not low.startswith("primary"):
                ev_source_norm = source_raw.split(",")[0].strip() or "primary"
        loc_hint = _aero_evidence_location_hint(contract_text, evidence_quote_val) if evidence_quote_val else ""

        anchoring_warning = ""
        if (
            not out_of_scope
            and detected == "Yes"
            and evidence_quote_val
            and verify_evidence_quote is not None
        ):
            ok, src_hint = verify_evidence_quote(
                evidence_quote_val,
                primary_text=contract_text or "",
                supporting_texts=supporting_doc_texts,
            )
            if ok:
                quote_checks_passed += 1
                if src_hint and src_hint != "primary":
                    ev_source_norm = src_hint
            else:
                quote_checks_failed += 1
                detected = "Unclear"
                anchoring_warning = (
                    "Evidence quote could not be verified as a verbatim substring of uploaded contract/supporting text."
                )

        row: dict = {
            "clause_name": name,
            "detected": detected,
            "uploaded_position": (
                "Out-of-scope document (NDA/confidentiality format) for this supply-contract POC."
                if out_of_scope
                else (evidence_paragraph or evidence or "Insufficient evidence in uploaded text.")
            ),
            "gb_ideal_position": ideal or "See knowledge JSON for ideal position.",
            "risk_level": risk_level,
            "risk_rationale": risk_rationale,
            "risk_trigger": risk_trigger,
            "mitigation_recommendation": mitigation_recommendation,
            "confidence_score": round(confidence_score * 100, 1),
            "confidence_label": confidence_label,
            "approval_path": approval,
            "evidence_snippet": evidence_snippet_val,
            "evidence_quote": evidence_quote_val,
            "evidence_source": ev_source_norm,
            "evidence_location_hint": loc_hint,
            "anchoring_warning": anchoring_warning,
            "knowledge_reference": (
                "POC scope limitation - supply contracts only"
                if out_of_scope
                else f"POC clause {idx}: {name}"
            ),
            "counterfactual": counterfactual,
            "expected_risk_shift": expected_risk_shift,
            "_quote_verified_by_agent1": True,
        }
        # Attach supporting-doc metadata to the first clause row only (acts as document-level metadata)
        if idx == 1:
            row["_referenced_supporting_docs"] = referenced_docs
            row["_missing_supporting_docs"] = missing_docs
            row["_legal_context"] = legal_context
        rows.append(row)
    if rows:
        rows[0]["_analysis_trace"] = {
            "evidence_quote_verification": {"passed": quote_checks_passed, "failed": quote_checks_failed},
            "supporting_context_referenced_gate": referenced_gate,
            "allowed_supporting_uploads": sorted(allowed_supporting),
            "contract_search_boost": True,
        }
    return rows