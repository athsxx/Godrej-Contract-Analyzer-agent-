"""Deterministic paragraph indexing over plain contract text (for JSON anchoring).

Assigns stable ``paragraph_id`` values ``p-0``, ``p-1``, … over split blocks.
This does not mutate the source document; it only builds an index for LLM
citations and downstream comment/highlight mapping.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List


def primary_text_fingerprint(text: str, *, limit: int = 16_384) -> str:
    """Short stable fingerprint of the primary text prefix (for artifact metadata)."""
    blob = (text or "")[:limit].encode("utf-8", errors="replace")
    return hashlib.sha256(blob).hexdigest()[:24]


def build_paragraph_index(text: str, *, max_paragraphs: int = 400) -> List[Dict[str, Any]]:
    """Split contract text into paragraphs with stable ids.

    Prefers blank-line paragraph breaks; falls back to line splits for dense text.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"\n\s*\n+", raw)
    if len(parts) < 8 and len(raw) > 8000:
        parts = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    blocks: List[str] = []
    for block in parts:
        compact = " ".join(block.split()).strip()
        if not compact:
            continue
        blocks.append(compact)
        if len(blocks) >= max_paragraphs:
            break
    return [
        {"paragraph_id": f"p-{i}", "text": blk[:2000], "preview": blk[:220]}
        for i, blk in enumerate(blocks)
    ]


def paragraph_catalog_for_prompt(paragraphs: List[Dict[str, Any]], *, max_blocks: int = 48) -> str:
    """Compact catalog of paragraph ids for bounded LLM context."""
    lines: List[str] = []
    for p in paragraphs[:max_blocks]:
        pid = p.get("paragraph_id", "")
        pv = str(p.get("preview") or "")[:180].replace("\n", " ")
        lines.append(f"- {pid}: {pv}")
    return "\n".join(lines)
