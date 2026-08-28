"""Legal-facing Word commentary: paragraph anchor, counsel-bubble deduplicated record, optional LLM brief."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import config as agent_config

logger = logging.getLogger(__name__)

# Fixed pipeline: classify model + tight cap for crisp legal brief (no product toggle).
_LEGAL_COMMENTARY_MAX_TOKENS = 900

_PRIMARY_CONTEXT_NOTE = (
    "Note: Supplier-specific redline text is not stored separately in this pipeline. "
    "The excerpt below is primary-agreement context around the evidence sentence (not a second upload)."
)

_LEGAL_COMMENTARY_SYSTEM = (
    "You are a senior legal-ops assistant. You receive STRUCTURED FACTS from contract analysis software.\n"
    "Write a SHORT briefing for in-house counsel in formal legal register (precise, neutral, active voice where natural).\n\n"
    "STRICT RULES:\n"
    "- Use ONLY sentences and phrases supported by the FACTS block. Do not invent article numbers, party names, "
    "amounts, dates, or statutory references that are not in FACTS.\n"
    "- If information is missing, skip that point.\n"
    "- Do not infer a distinct 'supplier vs purchaser' negotiating stance unless FACTS include a field explicitly "
    "labelled as supplier redline or separate supplier-upload text.\n"
    "- Plain text only. Under 1100 characters total.\n"
    "- Use exactly two headings on their own lines (ALL CAPS):\n"
    "REVIEW BRIEF\n"
    "Then at most 2 bullet lines. Each line must start with \"• \" and be at most one sentence (max 190 characters).\n"
    "\n"
    "NEGOTIATION FOCUS\n"
    "Then at most 2 bullet lines, same \"• \" format (max 190 characters per line).\n"
    "- Do not repeat quotation or paragraph-location text from the ANCHOR; assume counsel already sees it above.\n"
)


def format_evidence_provenance_block(
    row: Dict[str, str],
    *,
    primary_upload_display_name: str = "",
    evidence_exact_text: str = "",
    primary_flat_paragraph_1based: Optional[int] = None,
    primary_flat_total_paragraphs: Optional[int] = None,
) -> str:
    """Explicit which uploaded file the evidence quote was verified against (Agent1 + verify_evidence_quote)."""
    raw = (row.get("evidence_source") or "").strip()
    low = raw.lower()
    hint = (row.get("evidence_location_hint") or "").strip()
    aw = (row.get("anchoring_warning") or "").strip()
    primary_label = (primary_upload_display_name or "").strip() or "Primary uploaded contract (filename not passed to export)"
    exact = (evidence_exact_text or "").strip() or (row.get("evidence_quote") or row.get("evidence_snippet") or "").strip()

    if not raw or low in {"primary", "primary contract"}:
        verified = f"Verified: the evidence quote is a verbatim substring of the primary upload: {primary_label}."
    else:
        verified = f"Verified: the evidence quote is a verbatim substring of this supporting upload: {raw}."

    placement = (
        "Word placement: the comment bubble is anchored to the primary contract DOCX paragraph shown above "
        "(the export file is always the main agreement; the quote text is what was matched there)."
    )
    lines = [
        "=== EVIDENCE PROVENANCE (which uploaded document the quote came from) ===",
        verified,
        placement,
    ]
    if exact:
        lines.append(f'Exact verified / matched evidence string: "{_clip(exact, 520)}"')
    if primary_flat_paragraph_1based is not None and primary_flat_total_paragraphs is not None:
        lines.append(
            "Primary contract DOCX position (flattened paragraph order — same index as COMMENT ANCHOR): "
            f"paragraph {int(primary_flat_paragraph_1based)} of {int(primary_flat_total_paragraphs)}."
        )
    if raw and low not in {"primary", "primary contract"}:
        lines.append(
            "Anchor vs evidence file: The Word highlight remains on the main-agreement paragraph in the export. "
            f"The evidence string above was verified inside supporting upload «{raw}»; "
            "that file may use different layout or numbering than the anchor paragraph index."
        )
    if hint:
        lines.append(f"Extract location hint (flattened primary text / analysis): {hint}.")
    if aw:
        lines.append(f"Anchoring note: {aw}")
    return "\n".join(lines).strip()


def provenance_summary_one_line(
    row: Dict[str, str],
    *,
    primary_upload_display_name: str = "",
    evidence_exact_text: str = "",
    primary_flat_paragraph_1based: Optional[int] = None,
    primary_flat_total_paragraphs: Optional[int] = None,
) -> str:
    """Single line for compact / counsel_short facts."""
    raw = (row.get("evidence_source") or "").strip()
    low = raw.lower()
    primary_label = (primary_upload_display_name or "").strip() or "primary upload"
    exact = (evidence_exact_text or "").strip() or (row.get("evidence_quote") or row.get("evidence_snippet") or "").strip()
    tail = ""
    if primary_flat_paragraph_1based is not None and primary_flat_total_paragraphs is not None:
        tail += f" Primary flattened paragraph (main DOCX): {int(primary_flat_paragraph_1based)} of {int(primary_flat_total_paragraphs)}."
    if exact:
        tail += f' Evidence (clip): "{_clip(exact, 200)}"'
    if not raw or low in {"primary", "primary contract"}:
        return f"Verified evidence source (upload): {primary_label} (main agreement).{tail}".strip()
    return f"Verified evidence source (upload): supporting file {raw}.{tail}".strip()


def is_primary_evidence_source(row: Dict[str, str]) -> bool:
    raw = (row.get("evidence_source") or "").strip().lower()
    return not raw or raw in {"primary", "primary contract"}


def format_evidence_verified_single_line(row: Dict[str, str], *, primary_upload_display_name: str) -> str:
    """Single-line provenance for counsel bubble (no duplicate EVIDENCE PROVENANCE section)."""
    primary_label = (primary_upload_display_name or "").strip() or "Primary uploaded contract"
    if is_primary_evidence_source(row):
        return f"Evidence verified in upload: {primary_label} (main agreement)."
    raw = (row.get("evidence_source") or "").strip()
    return (
        f"Evidence verified in upload: {raw} (supporting schedule). "
        "The Word highlight remains on the main agreement paragraph above; confirm numbering in the source schedule."
    )


def build_supporting_hard_cite_block(row: Dict[str, str], evidence_aligned: str) -> str:
    """Hard supporting cite + tiny verification; only when evidence was verified in a supporting upload."""
    if is_primary_evidence_source(row):
        return ""
    fname = (row.get("evidence_source") or "").strip()
    if not fname:
        return ""
    hint = (row.get("evidence_location_hint") or "").strip()
    loc = f" — {hint}" if hint else ""
    gist = _one_line(
        row.get("counterfactual")
        or row.get("brief_counterfactual")
        or row.get("risk_rationale")
        or row.get("reason")
        or row.get("mitigation_recommendation")
        or "Cross-check supporting provision against the main agreement.",
        240,
    )
    ev = _clip((evidence_aligned or "").strip(), 320)
    return (
        "=== SUPPORTING CITE (hard reference) ===\n"
        f"«{fname}»{loc}. Table / analysis summary (verify in schedule): {gist}\n\n"
        f'Supporting verify (exact substring from that upload): "{ev}"'
    )


def format_other_uploads_inventory_line(
    uploaded_filenames: Optional[List[str]],
    *,
    primary_upload_display_name: str,
    row: Dict[str, str],
) -> str:
    """Optional one line when multiple files exist; does not assert verification."""
    if not uploaded_filenames or len(uploaded_filenames) < 2:
        return ""
    primary = (primary_upload_display_name or "").strip().lower()
    primary_base = Path(primary).name.lower() if primary else ""
    ev_src = (row.get("evidence_source") or "").strip()
    ev_base = Path(ev_src).name.lower() if ev_src else ""
    seen: set[str] = set()
    rest: list[str] = []
    for u in uploaded_filenames:
        raw = (u or "").strip()
        if not raw:
            continue
        base = Path(raw).name.lower()
        key = base or raw.lower()
        if key in seen:
            continue
        seen.add(key)
        if primary and (raw.lower() == primary or base == primary_base):
            continue
        if ev_src and (raw.lower() == ev_src.lower() or base == ev_base):
            continue
        rest.append(Path(raw).name)
    if not rest:
        return ""
    tail = "; ".join(rest[:8])
    if len(rest) > 8:
        tail += "; …"
    return (
        "Other schedules or uploads on file (context only; not verified for this clause unless named above): "
        f"{tail}."
    )


def build_comment_anchor_counsel_bubble(
    *,
    clause_name: str,
    anchor_index: int,
    total_paragraphs: int,
    anchored_paragraph_text: str,
    evidence_for_sentence_match: str,
    max_quote: int = 480,
    row: Dict[str, str],
    primary_upload_display_name: str,
) -> str:
    """Compact anchor: location + one-line verification + excerpt (serves as primary verbatim proof)."""
    n = max(1, int(total_paragraphs))
    i1 = int(anchor_index) + 1
    raw_single = re.sub(r"\s+", " ", (anchored_paragraph_text or "").strip())
    quote = _clip(raw_single, max_quote)
    _, sk, st = format_paragraph_sentence_map(
        anchored_paragraph_text or "",
        evidence_needle=evidence_for_sentence_match or "",
    )
    verified = format_evidence_verified_single_line(row, primary_upload_display_name=primary_upload_display_name)
    sup = build_supporting_hard_cite_block(row, evidence_for_sentence_match or "")
    sup_tail = f"\n\n{sup}" if sup else ""
    return (
        "=== COMMENT ANCHOR (main agreement) ===\n"
        f"Clause: {_one_line(clause_name, 160)}\n"
        f"Location: paragraph {i1} of {n} (flattened main contract DOCX order: body and table cells, top-to-bottom, "
        "left-to-right within tables).\n"
        f"Sentence focus (evidence-aligned): sentence {sk} of {st} within this paragraph.\n"
        f"{verified}\n"
        f'Quoted text at anchor: "{quote}"'
        f"{sup_tail}\n"
    )


def build_comment_analysis_record_counsel_bubble(
    row: Dict[str, str],
    *,
    uploaded_filenames: Optional[List[str]] = None,
    primary_upload_display_name: str = "",
    max_gb: int = 300,
    max_mitigation: int = 520,
    max_gap: int = 420,
) -> str:
    """Single-pass analysis fields: no duplicated evidence quote or primary context."""
    risk = (row.get("risk_level") or "").strip()
    det = (row.get("detected") or "").strip()
    gb_raw = (row.get("gb_ideal_position") or row.get("suggested_text") or "").strip()
    gb_line = ""
    if gb_raw:
        gb_line = (
            f"GB baseline (knowledge position; excerpt — verify against playbook): {_clip(gb_raw, max_gb)}\n\n"
        )
    mit = _clip(row.get("mitigation_recommendation") or "", max_mitigation)
    ap = _one_line(row.get("approval_path") or "", 260)
    gap_src = (row.get("counterfactual") or row.get("brief_counterfactual") or "").strip()
    gap = _clip(re.sub(r"\s+", " ", gap_src), max_gap) if gap_src else ""
    inv = format_other_uploads_inventory_line(
        uploaded_filenames,
        primary_upload_display_name=primary_upload_display_name,
        row=row,
    )
    inv_tail = f"\n\n{inv}" if inv else ""
    gap_block = f"Negotiation gap: {gap}\n" if gap else ""
    return (
        "=== ANALYSIS RECORD ===\n"
        f"Risk: {risk} | Detected in contract: {det}\n\n"
        f"{gb_line}"
        f"Mitigation: {mit}\n"
        f"Approval path: {ap}\n\n"
        f"{gap_block}"
        f"{inv_tail}".strip()
    )


def build_comment_facts_for_llm_counsel_bubble(
    row: Dict[str, str],
    *,
    evidence_aligned: str,
    primary_upload_display_name: str = "",
    uploaded_filenames: Optional[List[str]] = None,
) -> str:
    """Deduped FACTS for the legal brief LLM (matches counsel bubble; no repeated verbatim quote)."""
    risk = (row.get("risk_level") or "").strip()
    det = (row.get("detected") or "").strip()
    verified = format_evidence_verified_single_line(row, primary_upload_display_name=primary_upload_display_name)
    gb = _clip(row.get("gb_ideal_position") or row.get("suggested_text") or "", 360)
    mit = _clip(row.get("mitigation_recommendation") or "", 300)
    ap = _one_line(row.get("approval_path") or "", 200)
    gap = _one_line(row.get("counterfactual") or row.get("brief_counterfactual") or "", 360)
    inv = format_other_uploads_inventory_line(
        uploaded_filenames,
        primary_upload_display_name=primary_upload_display_name,
        row=row,
    )
    sup_note = ""
    if not is_primary_evidence_source(row):
        sup_note = (
            f"\nSupporting verification (substring from named schedule): {_clip(evidence_aligned, 360)}\n"
            f"Location hint (if any): {(row.get('evidence_location_hint') or '').strip()}"
        )
    parts = [
        f"Risk: {risk} | Detected in contract: {det}",
        verified,
        "Do not restate the anchored quotation; it is shown separately to counsel.",
        f"GB baseline (knowledge): {gb}" if gb else "",
        f"Mitigation: {mit}",
        f"Approval path: {ap}",
        f"Negotiation gap / counterfactual: {gap}" if gap else "",
        inv if inv else "",
        sup_note.strip(),
    ]
    return "\n".join(p for p in parts if p).strip()


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _clip_centered_on_needle(blob: str, needle: str, max_chars: int) -> str:
    """Keep a window around the first occurrence of needle (or longest prefix) instead of the string head."""
    blob = (blob or "").strip()
    if not blob or max_chars < 40:
        return _clip(blob, max_chars)
    nd = _normalize_sentence_match(needle)
    if len(nd) < 12:
        return _clip(blob, max_chars)
    bl_raw = blob
    bl = bl_raw.lower()
    pos = bl.find(nd[: min(160, len(nd))])
    if pos < 0:
        for length in range(min(100, len(nd)), 11, -1):
            frag = nd[:length]
            pos = bl.find(frag)
            if pos >= 0:
                break
    if pos < 0:
        return _clip(blob, max_chars)
    half = max_chars // 2
    start = max(0, pos - half)
    end = min(len(bl_raw), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    out = bl_raw[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(bl_raw) else ""
    return (prefix + out + suffix).strip()


def primary_contract_context_for_commentary(
    row: Dict[str, str],
    *,
    evidence_aligned: str,
    max_chars: int = 420,
) -> str:
    """Human-honest label: primary text around evidence (not supplier upload)."""
    needle = (row.get("evidence_quote") or "").strip() or (evidence_aligned or "").strip()
    blob = (row.get("uploaded_position") or "").strip()
    if not blob:
        blob = (row.get("evidence_snippet") or row.get("evidence_text") or "").strip()
    if not blob:
        return ""
    excerpt = _clip_centered_on_needle(blob, needle, max_chars) if needle else _clip(blob, max_chars)
    return excerpt


def build_comment_facts_for_llm(
    row: Dict[str, str],
    supporting_blurb: str,
    *,
    evidence_aligned: str,
    primary_upload_display_name: str = "",
    evidence_exact_for_provenance: str = "",
    primary_flat_paragraph_1based: Optional[int] = None,
    primary_flat_total_paragraphs: Optional[int] = None,
) -> str:
    """Facts string for the legal-brief LLM: aligned excerpts only (no misleading head-clipped blobs)."""
    risk = (row.get("risk_level") or "").strip()
    det = (row.get("detected") or "").strip()
    exact = (evidence_exact_for_provenance or "").strip() or (evidence_aligned or "").strip()
    prov = format_evidence_provenance_block(
        row,
        primary_upload_display_name=primary_upload_display_name,
        evidence_exact_text=exact,
        primary_flat_paragraph_1based=primary_flat_paragraph_1based,
        primary_flat_total_paragraphs=primary_flat_total_paragraphs,
    )
    ev = _clip(evidence_aligned or row.get("evidence_snippet") or row.get("evidence_text") or "", 520)
    ctx = primary_contract_context_for_commentary(row, evidence_aligned=evidence_aligned, max_chars=360)
    gb = _clip(row.get("gb_ideal_position") or row.get("suggested_text") or "", 420)
    rat = _clip(row.get("risk_rationale") or row.get("reason") or "", 320)
    mit = _clip(row.get("mitigation_recommendation") or "", 280)
    ap = _one_line(row.get("approval_path") or "", 200)
    sup = _clip(supporting_blurb or "", 380)
    parts = [
        f"Risk: {risk} | Detected in contract: {det}",
        "",
        prov,
        "",
        f"Contract evidence (aligned): {ev}",
        "",
        f"Primary contract context (centred on evidence, not supplier upload): {ctx}" if ctx else "",
        _PRIMARY_CONTEXT_NOTE if ctx else "",
        "",
        f"GB ideal (knowledge baseline): {gb}",
        "",
        f"Risk rationale: {rat}",
        "",
        f"Mitigation: {mit}",
        f"Approval path: {ap}",
        "",
        f"Supporting schedules (excerpts; each excerpt may end with \"Where in supporting file …\" position lines): {sup}",
    ]
    return "\n".join(p for p in parts if p is not None).strip()


def _one_line(s: str, n: int) -> str:
    return _clip(re.sub(r"\s+", " ", (s or "").strip()), n)


def _normalize_sentence_match(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def split_paragraph_sentences(text: str) -> list[str]:
    """Split a paragraph into rough sentences for orientation (legal prose)."""
    raw = (text or "").replace("\r", " ").strip()
    if not raw:
        return []
    parts = re.split(r"(?<=[.!?])\s+", raw)
    out: list[str] = []
    for p in parts:
        c = " ".join(p.split()).strip()
        if not c:
            continue
        if len(c) < 14 and out:
            out[-1] = (out[-1] + " " + c).strip()
        else:
            out.append(c)
    return out if out else [raw]


def best_sentence_index_1based(sentences: list[str], needle: str) -> int:
    """1-based index of the sentence that best contains or overlaps the evidence needle."""
    if not sentences:
        return 1
    nd = _normalize_sentence_match(needle)
    if len(nd) < 10:
        return 1
    # Prefer longest prefix of needle that appears in any sentence
    for length in range(min(len(nd), 220), 9, -1):
        frag = nd[:length]
        for i, sent in enumerate(sentences):
            if frag in _normalize_sentence_match(sent):
                return i + 1
    best_i = 0
    best_hits = -1
    nd_tokens = [t for t in re.findall(r"[a-z0-9]{3,}", nd) if t][:40]
    if not nd_tokens:
        return 1
    nd_set = set(nd_tokens)
    for i, sent in enumerate(sentences):
        st = set(re.findall(r"[a-z0-9]{3,}", _normalize_sentence_match(sent)))
        hits = len(nd_set & st)
        if hits > best_hits:
            best_hits = hits
            best_i = i
    return best_i + 1 if best_hits > 0 else 1


def format_paragraph_sentence_map(
    paragraph_text: str,
    *,
    evidence_needle: str,
    max_sentences: int = 12,
    max_each: int = 220,
) -> tuple[str, int, int]:
    """Numbered sentence list; returns (block, sentence_1based, total_sentences)."""
    sents = split_paragraph_sentences(paragraph_text)
    total = len(sents)
    k = best_sentence_index_1based(sents, evidence_needle)
    lines: list[str] = []
    for i, s in enumerate(sents[:max_sentences], start=1):
        tag = "  >>> " if i == k else "      "
        lines.append(f"{tag}S{i}: {_one_line(s, max_each)}")
    if total > max_sentences:
        lines.append(f"      … ({total - max_sentences} more sentence(s) omitted)")
    block = "=== SENTENCES IN THIS PARAGRAPH (orientation; Word highlight is the whole paragraph) ===\n" + "\n".join(lines)
    return block, k, total


def build_comment_anchor_section(
    *,
    clause_name: str,
    anchor_index: int,
    total_paragraphs: int,
    anchored_paragraph_text: str,
    evidence_for_sentence_match: str = "",
    max_quote: int = 520,
    evidence_provenance_block: str = "",
) -> str:
    """Explicit location: flattened paragraph index + sentence-of-focus within that paragraph."""
    n = max(1, int(total_paragraphs))
    i1 = int(anchor_index) + 1
    raw = (anchored_paragraph_text or "").strip()
    raw_single = re.sub(r"\s+", " ", raw)
    quote = _clip(raw_single, max_quote)
    sent_block, sk, st = format_paragraph_sentence_map(
        anchored_paragraph_text or "",
        evidence_needle=evidence_for_sentence_match or "",
    )
    prov = (evidence_provenance_block or "").strip()
    prov_tail = f"\n{prov}\n\n" if prov else "\n"
    return (
        "=== COMMENT ANCHOR (this note is attached to the highlighted paragraph in Word) ===\n"
        f"Clause: {_one_line(clause_name, 160)}\n"
        f"Location: paragraph {i1} of {n} in flattened contract order "
        "(main document and table cells, top-to-bottom, left-to-right within tables).\n"
        f"Sentence focus (evidence-aligned): sentence {sk} of {st} within this paragraph.\n"
        "Detection: paragraph chosen by deterministic match of aligned evidence to flattened DOCX text; "
        "sentence index picks the best overlap with the same evidence string.\n"
        f'Quoted text at this anchor (paragraph excerpt): "{quote}"\n'
        f"{prov_tail}"
        f"{sent_block}\n"
    )


def build_comment_facts_section(
    row: Dict[str, str],
    supporting_blurb: str,
    *,
    evidence_aligned: str,
    max_evidence: int = 1100,
    max_uploaded: int = 900,
    max_gb: int = 900,
    max_rationale: int = 750,
    max_mitigation: int = 700,
    max_counterfactual: int = 750,
    max_supporting: int = 850,
    export_style: str = "full",
    primary_upload_display_name: str = "",
    evidence_exact_for_provenance: str = "",
    primary_flat_paragraph_1based: Optional[int] = None,
    primary_flat_total_paragraphs: Optional[int] = None,
) -> str:
    """Deterministic full context for counsel (verbatim-style fields)."""
    risk = (row.get("risk_level") or "").strip()
    det = (row.get("detected") or "").strip()
    ctx_block = primary_contract_context_for_commentary(
        row, evidence_aligned=evidence_aligned, max_chars=max_uploaded
    )
    ctx_block = _clip(ctx_block, max_uploaded)
    style = (export_style or "full").strip().lower()
    if style == "counsel_short":
        return build_comment_facts_section_compact(
            row,
            supporting_blurb,
            evidence_aligned=evidence_aligned,
            max_evidence=min(max_evidence, 520),
            max_uploaded=min(max_uploaded, 400),
            max_gb=min(max_gb, 400),
            max_rationale=min(max_rationale, 280),
            max_mitigation=max_mitigation,
            max_counterfactual=min(max_counterfactual, 200),
            max_supporting=min(max_supporting, 360),
            export_style="counsel_short",
            primary_upload_display_name=primary_upload_display_name,
            evidence_exact_for_provenance=evidence_exact_for_provenance,
            primary_flat_paragraph_1based=primary_flat_paragraph_1based,
            primary_flat_total_paragraphs=primary_flat_total_paragraphs,
        )
    lines = [
        "=== CLAUSE STATUS (from analysis table) ===",
        f"Risk level: {risk}",
        f"Detected in contract: {det}",
        "",
        "=== CONTRACT EVIDENCE (aligned / analysis excerpt) ===",
        _clip(evidence_aligned or row.get("evidence_snippet") or row.get("evidence_text") or "", max_evidence),
        "",
        format_evidence_provenance_block(
            row,
            primary_upload_display_name=primary_upload_display_name,
            evidence_exact_text=(evidence_exact_for_provenance or "").strip() or evidence_aligned,
            primary_flat_paragraph_1based=primary_flat_paragraph_1based,
            primary_flat_total_paragraphs=primary_flat_total_paragraphs,
        ),
        "",
        "=== PRIMARY CONTRACT CONTEXT (not supplier upload; excerpt centred on evidence) ===",
        _PRIMARY_CONTEXT_NOTE,
        ctx_block,
        "",
        "=== GB IDEAL POSITION (knowledge baseline) ===",
        _clip(row.get("gb_ideal_position") or row.get("suggested_text") or "", max_gb),
        "",
        "=== RISK RATIONALE ===",
        _clip(row.get("risk_rationale") or row.get("reason") or "", max_rationale),
        "",
        "=== MITIGATION & CLEARANCE ===",
        _clip(row.get("mitigation_recommendation") or "", max_mitigation),
        f"Approval path: {_one_line(row.get('approval_path') or '', 260)}",
        "",
        "=== NEGOTIATION / COUNTERFACTUAL ===",
        _clip(row.get("counterfactual") or row.get("brief_counterfactual") or "", max_counterfactual),
        "",
        "=== SUPPORTING FILES / SCHEDULES (cross-read excerpts; see \"Where in supporting file\" in each excerpt) ===",
        _clip(supporting_blurb or "", max_supporting),
    ]
    return "\n".join(lines)


def build_comment_facts_section_compact(
    row: Dict[str, str],
    supporting_blurb: str,
    *,
    evidence_aligned: str,
    max_evidence: int = 520,
    max_uploaded: int = 380,
    max_gb: int = 520,
    max_rationale: int = 360,
    max_mitigation: int = 320,
    max_counterfactual: int = 360,
    max_supporting: int = 420,
    export_style: str = "full",
    primary_upload_display_name: str = "",
    evidence_exact_for_provenance: str = "",
    primary_flat_paragraph_1based: Optional[int] = None,
    primary_flat_total_paragraphs: Optional[int] = None,
) -> str:
    """Same compliance fields as the full facts block, fewer headings and tighter clips (Word comments)."""
    risk = (row.get("risk_level") or "").strip()
    det = (row.get("detected") or "").strip()
    ev = _clip(evidence_aligned or row.get("evidence_snippet") or row.get("evidence_text") or "", max_evidence)
    ctx = primary_contract_context_for_commentary(
        row, evidence_aligned=evidence_aligned or ev, max_chars=max(200, max_uploaded + 40)
    )
    ctx = _clip(ctx, max_uploaded + 80)
    gb = _clip(row.get("gb_ideal_position") or row.get("suggested_text") or "", max_gb)
    rat = _clip(row.get("risk_rationale") or row.get("reason") or "", max_rationale)
    mit = _clip(row.get("mitigation_recommendation") or "", max_mitigation)
    ap = _one_line(row.get("approval_path") or "", 220)
    cf = _clip(row.get("counterfactual") or row.get("brief_counterfactual") or "", max_counterfactual)
    sup = _clip(supporting_blurb or "", max_supporting)
    style = (export_style or "full").strip().lower()
    exact_prov = (evidence_exact_for_provenance or "").strip() or (evidence_aligned or ev).strip()
    prov_line = provenance_summary_one_line(
        row,
        primary_upload_display_name=primary_upload_display_name,
        evidence_exact_text=exact_prov,
        primary_flat_paragraph_1based=primary_flat_paragraph_1based,
        primary_flat_total_paragraphs=primary_flat_total_paragraphs,
    )
    if style == "counsel_short":
        return (
            "=== ANALYSIS SUMMARY (counsel short export) ===\n"
            f"Risk: {risk} | Detected in contract: {det}\n\n"
            f"Contract evidence (aligned): {ev}\n\n"
            f"{prov_line}\n\n"
            f"Mitigation: {mit}\n"
            f"Approval path: {ap}\n\n"
            f"Supporting schedules (if any; cross-read — each block ends with \"Where in supporting file …\" lines): {sup}"
        )
    return (
        "=== ANALYSIS RECORD (table + uploads; verify against contract text above) ===\n"
        f"Risk: {risk} | Detected in contract: {det}\n\n"
        f"Contract evidence (aligned): {ev}\n\n"
        f"{prov_line}\n\n"
        f"Primary contract context (not supplier upload; centred on evidence):\n{_PRIMARY_CONTEXT_NOTE}\n{ctx}\n\n"
        f"GB ideal (knowledge baseline): {gb}\n\n"
        f"Risk rationale: {rat}\n\n"
        f"Mitigation: {mit}\n"
        f"Approval path: {ap}\n\n"
        f"Counterfactual / negotiation gap: {cf}\n\n"
        f"Supporting schedules (if any; cross-read — each block ends with \"Where in supporting file …\" lines): {sup}"
    )


def synthesize_legal_brief_llm(*, clause_name: str, facts_for_llm: str) -> Optional[str]:
    """Crisp REVIEW BRIEF + NEGOTIATION FOCUS from facts only; returns None if the LLM call fails."""
    facts_for_llm = (facts_for_llm or "").strip()
    if not facts_for_llm:
        return None
    cap = min(4200, len(facts_for_llm))
    payload = facts_for_llm[:cap]
    user = (
        f"Clause label: {_one_line(clause_name, 160)}\n\n"
        f"FACTS:\n{payload}\n\n"
        "Write REVIEW BRIEF and NEGOTIATION FOCUS per the system rules. Output nothing else."
    )
    try:
        if agent_config.ENABLE_BEDROCK:
            from .bedrock_llm import call_bedrock_chat

            raw = call_bedrock_chat(prompt=user, system_message=_LEGAL_COMMENTARY_SYSTEM)
        else:
            from .local_llm import call_local_chat

            raw = call_local_chat(
                prompt=user,
                system_message=_LEGAL_COMMENTARY_SYSTEM,
                model_id=getattr(agent_config, "LOCAL_LLM_MODEL_CLASSIFY", None),
                temperature=float(getattr(agent_config, "LOCAL_LLM_TEMPERATURE_CLASSIFY", 0.0)),
                top_p=min(float(getattr(agent_config, "LOCAL_LLM_TOP_P", 0.6)), 0.35),
                max_tokens=_LEGAL_COMMENTARY_MAX_TOKENS,
            )
    except Exception as exc:
        logger.warning("Legal commentary LLM failed: %s", exc)
        return None
    text = (raw or "").strip()
    if len(text) < 40:
        return None
    return _clip(text, 1100)


_FULL_CONTEXT_HEADER_LEGACY = "=== SOURCE FIELDS (extracted; verify against the anchor) ===\n\n"
_BRIEF_HEADER_LEGACY = "=== LEGAL BRIEF (generated; verify below) ===\n\n"
_BRIEF_HEADER_COUNSEL_BUBBLE = "=== LEGAL BRIEF ===\n\n"


def assemble_legal_comment_body(
    *,
    anchor_section: str,
    facts_section: str,
    llm_brief: Optional[str],
    max_chars: int = 8800,
    comment_layout: str = "legacy",
) -> str:
    """Combine anchor, optional LLM brief, and deterministic facts; trim to Word-safe length."""
    anchor_section = (anchor_section or "").strip()
    facts_section = (facts_section or "").strip()
    brief = (llm_brief or "").strip()
    sep = "\n\n"
    layout = (comment_layout or "legacy").strip().lower()
    if layout == "counsel_bubble":
        hdr = ""
        brief_hdr = _BRIEF_HEADER_COUNSEL_BUBBLE
    else:
        hdr = _FULL_CONTEXT_HEADER_LEGACY
        brief_hdr = _BRIEF_HEADER_LEGACY

    def _pack(include_brief: bool, facts_body: str) -> str:
        m = ""
        if include_brief and brief:
            m = brief_hdr + brief + "\n"
        core = hdr + (facts_body or "").strip()
        if m:
            return anchor_section + sep + m + sep + core
        return anchor_section + sep + core

    # Try full brief + full facts
    cand = _pack(True, facts_section)
    if len(cand) <= max_chars:
        return cand
    # Drop brief if needed
    cand2 = _pack(False, facts_section)
    if len(cand2) <= max_chars:
        return cand2
    # Trim facts (account for headers and optional brief)
    for include_brief in (True, False):
        if include_brief and not brief:
            continue
        m = (brief_hdr + brief + "\n") if (include_brief and brief) else ""
        overhead = len(anchor_section) + len(sep) + len(hdr) + len(m) + (len(sep) if m else 0)
        room = max(120, max_chars - overhead)
        c = _pack(include_brief, _clip(facts_section, room))
        if len(c) <= max_chars:
            return c
    return anchor_section + sep + hdr + _clip(facts_section, 120)
