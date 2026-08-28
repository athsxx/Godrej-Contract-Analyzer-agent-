"""Deterministic contract text search (search-then-assert).

``find_phrase`` matches case-insensitively with flexible whitespace between tokens,
mirroring common legal-tool "find in document" behavior.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space."""
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_for_substring_match(text: str) -> str:
    """Lowercase, Unicode-normalize, collapse whitespace — for verbatim verification."""
    s = (text or "").strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u2009", " ")
    return collapse_whitespace(s.lower())


def phrase_in_text(haystack: str, phrase: str) -> bool:
    """True if ``phrase`` appears in ``haystack`` after whitespace normalization (case-insensitive)."""
    if not phrase or not haystack:
        return False
    h = normalize_for_substring_match(haystack)
    p = normalize_for_substring_match(phrase)
    if not p:
        return False
    return p in h


def find_phrase_spans(haystack: str, query: str) -> List[Tuple[int, int]]:
    """Return (start, end) spans in *original* ``haystack`` for ``query``.

    Tokens in ``query`` are matched in order with arbitrary whitespace allowed between them.
    """
    raw = (haystack or "").strip()
    q = (query or "").strip()
    if not raw or not q:
        return []
    tokens = [t for t in re.split(r"\s+", q) if t]
    if not tokens:
        return []
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    try:
        return [(m.start(), m.end()) for m in re.finditer(pattern, raw, flags=re.IGNORECASE | re.DOTALL)]
    except re.error:
        return []


def find_phrase(haystack: str, query: str) -> List[Tuple[int, int]]:
    """Alias for :func:`find_phrase_spans` (Mike-style find)."""
    return find_phrase_spans(haystack, query)


def _merge_spans(spans: Sequence[Tuple[int, int]], merge_gap: int = 8) -> List[Tuple[int, int]]:
    """Merge overlapping / nearby spans."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda x: (x[0], x[1]))
    out: List[Tuple[int, int]] = [ordered[0]]
    for a, b in ordered[1:]:
        la, lb = out[-1]
        if a <= lb + merge_gap:
            out[-1] = (la, max(lb, b))
        else:
            out.append((a, b))
    return out


def extract_windows(
    haystack: str,
    spans: Sequence[Tuple[int, int]],
    *,
    radius: int = 420,
    max_windows: int = 3,
) -> List[str]:
    """Extract up to ``max_windows`` context windows around span centers."""
    raw = haystack or ""
    if not raw or not spans:
        return []
    merged = _merge_spans(spans)[: max(1, max_windows * 2)]
    windows: List[str] = []
    for a, b in merged:
        center = (a + b) // 2
        start = max(0, center - radius)
        end = min(len(raw), center + radius)
        chunk = raw[start:end].strip()
        chunk = collapse_whitespace(chunk)
        if len(chunk) >= 40:
            windows.append(chunk)
        if len(windows) >= max_windows:
            break
    return windows


def format_search_windows_for_prompt(windows: List[str]) -> str:
    """Human-readable block for LLM context."""
    if not windows:
        return ""
    lines = ["[Contract search — keyword hits; use only if relevant; cite verbatim substrings from contract)]"]
    for i, w in enumerate(windows, start=1):
        lines.append(f"--- Window {i} ---\n{w}")
    return "\n".join(lines)


def collect_keyword_spans(text: str, keywords: Sequence[str], *, max_spans_per_keyword: int = 4) -> List[Tuple[int, int]]:
    """Run ``find_phrase`` for each keyword; merge and cap total span count."""
    all_spans: List[Tuple[int, int]] = []
    for kw in keywords or []:
        k = str(kw).strip()
        if len(k) < 2:
            continue
        found = find_phrase_spans(text, k)[:max_spans_per_keyword]
        all_spans.extend(found)
    return _merge_spans(all_spans)


def sentence_overlaps_spans(sentence: str, haystack: str, spans: Sequence[Tuple[int, int]]) -> bool:
    """True if ``sentence``'s first occurrence in ``haystack`` intersects any span."""
    if not sentence or not haystack or not spans:
        return False
    sent = sentence.strip()
    idx = haystack.find(sent)
    if idx < 0:
        idx = haystack.lower().find(sent.lower())
    if idx < 0:
        return False
    end = idx + len(sent)
    for a, b in spans:
        if idx < b and end > a:
            return True
    return False


def verify_evidence_quote(
    quote: str,
    *,
    primary_text: str,
    supporting_texts: dict[str, str] | None,
) -> tuple[bool, str]:
    """Check that ``quote`` appears verbatim (normalized) in primary or supporting uploads.

    Returns:
        (ok, source_hint) where source_hint is ``primary``, a file name, or ``""`` if ok is False.
    """
    q = (quote or "").strip()
    if not q:
        return True, ""
    if phrase_in_text(primary_text or "", q):
        return True, "primary"
    for name, body in (supporting_texts or {}).items():
        if body and phrase_in_text(body, q):
            return True, name
    return False, ""
