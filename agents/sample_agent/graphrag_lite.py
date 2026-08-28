"""Lightweight GraphRAG-style context for multi-document sessions.

Builds a small **entity ↔ chunk** bipartite graph from the primary contract and
supporting uploads (overlapping text windows), then expands retrieval from a
**seed** string (typically clause names + evidence from Agent 1).

This is **not** the Microsoft ``graphrag`` CLI/index pipeline (OpenAI-centric,
heavy indexing). It is an in-repo approximation that works offline with the
same stack as the rest of the POC and avoids new heavyweight dependencies.

Downstream use: optional extra context for Agent 2 / narrative review only.
Do **not** merge this text into primary-only evidence used for DOCX anchoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple

# Exhibit / schedule references (stable lexical anchors across documents)
_REF_RE = re.compile(
    r"\b(?:Exhibit|Appendix|Schedule|Annex)\s+[A-Za-z0-9.\-]+|\b(?:SOW|MSA|SLA|NDA)\b",
    re.IGNORECASE,
)
# Title-case multi-word phrases (party names, defined-style labels)
_TITLE_PHRASE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,5})\b")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "shall",
        "will",
        "such",
        "party",
        "parties",
        "each",
        "any",
        "all",
        "per",
        "are",
        "may",
        "not",
        "hereof",
        "thereof",
        "therein",
        "herein",
        "including",
        "without",
        "limitation",
    }
)


@dataclass
class TextChunk:
    cid: int
    source: str
    text: str


@dataclass
class LiteChunkGraph:
    chunks: List[TextChunk] = field(default_factory=list)
    entity_to_chunks: Dict[str, Set[int]] = field(default_factory=dict)
    chunk_entities: Dict[int, Set[str]] = field(default_factory=dict)


def _normalize_entity(s: str) -> str:
    t = " ".join(s.split())
    return t[:120].lower()


def _extract_entities(text: str) -> Set[str]:
    if not text:
        return set()
    found: Set[str] = set()
    for m in _REF_RE.finditer(text):
        found.add(_normalize_entity(m.group(0)))
    for m in _TITLE_PHRASE.finditer(text):
        phrase = m.group(0).strip()
        if len(phrase) >= 6 and phrase.split()[0].lower() not in _STOP:
            found.add(_normalize_entity(phrase))
    return found


def _significant_words(text: str) -> Set[str]:
    words: Set[str] = set()
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", (text or "").lower()):
        if w in _STOP:
            continue
        words.add(w)
    return words


def _chunk_text(source: str, text: str, *, chunk_size: int, overlap: int, start_id: int) -> Tuple[List[TextChunk], int]:
    t = " ".join(text.split())
    if not t:
        return [], start_id
    chunks: List[TextChunk] = []
    step = max(1, chunk_size - overlap)
    i = 0
    cid = start_id
    while i < len(t):
        piece = t[i : i + chunk_size].strip()
        if len(piece) >= 40:
            chunks.append(TextChunk(cid=cid, source=source, text=piece))
            cid += 1
        i += step
    return chunks, cid


def build_lite_chunk_graph(
    doc_texts: Mapping[str, str],
    *,
    chunk_size: int = 900,
    overlap: int = 120,
    max_chunks: int = 220,
) -> LiteChunkGraph:
    """Index all documents into overlapping chunks and link shared entities."""
    all_chunks: List[TextChunk] = []
    next_id = 0
    for source, raw in doc_texts.items():
        if len(all_chunks) >= max_chunks:
            break
        if not raw:
            continue
        parts, next_id = _chunk_text(str(source), str(raw), chunk_size=chunk_size, overlap=overlap, start_id=next_id)
        for p in parts:
            if len(all_chunks) >= max_chunks:
                break
            all_chunks.append(p)

    entity_to_chunks: Dict[str, Set[int]] = {}
    chunk_entities: Dict[int, Set[str]] = {}
    for ch in all_chunks:
        ents = _extract_entities(ch.text) | {w for w in _significant_words(ch.text) if len(w) > 5}
        # Keep entity set bounded per chunk
        ents = set(list(ents)[:40])
        chunk_entities[ch.cid] = ents
        for e in ents:
            entity_to_chunks.setdefault(e, set()).add(ch.cid)

    return LiteChunkGraph(chunks=all_chunks, entity_to_chunks=entity_to_chunks, chunk_entities=chunk_entities)


def clause_table_retrieval_seed(clause_table: Sequence[MutableMapping[str, object]] | None) -> str:
    """Flatten Agent 1 rows into a seed string for graph expansion."""
    if not clause_table:
        return ""
    parts: List[str] = []
    for row in clause_table:
        cn = str(row.get("clause_name") or "").strip()
        ev = str(row.get("evidence_snippet") or "").strip()[:240]
        parts.append(f"{cn}\n{ev}".strip())
    return "\n\n".join(p for p in parts if p)


def retrieve_cross_doc_context(
    graph: LiteChunkGraph,
    seed: str,
    *,
    max_chunks: int = 18,
    max_chars: int = 3500,
) -> str:
    """Score chunks by entity/word overlap with seed, expand one hop on shared entities."""
    if not graph.chunks or not (seed or "").strip():
        return ""

    seed_entities = _extract_entities(seed) | {w for w in _significant_words(seed) if len(w) > 4}
    if not seed_entities:
        return ""

    seed_chunk_ids: Set[int] = set()
    for e in seed_entities:
        seed_chunk_ids |= graph.entity_to_chunks.get(e, set())

    scores: Dict[int, int] = {}
    for cid in seed_chunk_ids:
        scores[cid] = scores.get(cid, 0) + 3
    for ch in graph.chunks:
        inter = len(graph.chunk_entities.get(ch.cid, set()) & seed_entities)
        if inter:
            scores[ch.cid] = scores.get(ch.cid, 0) + inter

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:8]
    selected: Set[int] = {cid for cid, _ in ranked}

    # One-hop expansion via shared entities
    frontier_entities: Set[str] = set()
    for cid in selected:
        frontier_entities |= graph.chunk_entities.get(cid, set())
    for e in list(frontier_entities)[:60]:
        for cid in graph.entity_to_chunks.get(e, set()):
            selected.add(cid)
            if len(selected) >= max_chunks:
                break
        if len(selected) >= max_chunks:
            break

    # Stable order: primary-like sources first (longest source name often contract — caller orders dict)
    id_to_chunk = {c.cid: c for c in graph.chunks}
    ordered = [id_to_chunk[i] for i in sorted(selected) if i in id_to_chunk]

    out_parts: List[str] = []
    used = 0
    for ch in ordered[:max_chunks]:
        block = f"[{ch.source} | chunk {ch.cid}]\n{ch.text}"
        if used + len(block) > max_chars:
            remain = max_chars - used - 40
            if remain > 120:
                out_parts.append(f"[{ch.source} | chunk {ch.cid}]\n{ch.text[:remain]}…")
            break
        out_parts.append(block)
        used += len(block) + 2
    return "\n\n---\n\n".join(out_parts).strip()


def build_session_doc_texts(primary_name: str, primary_text: str, supporting: Mapping[str, str] | None) -> Dict[str, str]:
    """Order primary first, then supporting files."""
    texts: Dict[str, str] = {}
    if primary_text and primary_text.strip():
        label = primary_name.strip() or "primary_contract"
        texts[label] = primary_text
    for name, body in (supporting or {}).items():
        if body and str(body).strip():
            texts[str(name)] = str(body)
    return texts


def compute_graphrag_context(
    *,
    primary_name: str,
    primary_text: str,
    supporting_doc_texts: Mapping[str, str] | None,
    clause_table: Sequence[MutableMapping[str, object]] | None,
    max_chars: int = 3500,
) -> str:
    """End-to-end: build graph from uploads + seed from clause table → context string."""
    doc_texts = build_session_doc_texts(primary_name, primary_text, supporting_doc_texts or {})
    if len(doc_texts) < 1:
        return ""
    graph = build_lite_chunk_graph(doc_texts)
    seed = clause_table_retrieval_seed(clause_table)
    return retrieve_cross_doc_context(graph, seed, max_chars=max_chars)
