"""RAG: chunk, embed, and query POC + uploaded documents.

Uses sentence-transformers for embeddings and a lightweight numpy-based
in-memory vector store (no external DB). Avoids SQLite mutex issues that
ChromaDB triggers inside Django's threaded dev server on macOS.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import config as agent_config
from .cross_encoder_rerank import rerank_indices_by_query

logger = logging.getLogger(__name__)

_sentence_transformer = None

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 300


class _HashEmbeddingModel:
    """Offline fallback embedding model.

    Uses a deterministic hashing trick over tokens so upload indexing still works
    without HuggingFace/model downloads. This is less semantic than Legal-BERT but
    good enough for lexical retrieval and avoids blocking uploads.
    """

    dim = 384

    def encode(self, chunks: List[str], show_progress_bar: bool = False):
        vectors = []
        for chunk in chunks:
            vec = np.zeros(self.dim, dtype=np.float32)
            tokens = re.findall(r"[a-zA-Z0-9]+", (chunk or "").lower())
            for token in tokens:
                digest = hashlib.sha1(token.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vec[idx] += sign
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec.tolist())
        return np.array(vectors, dtype=np.float32)

    def get_sentence_embedding_dimension(self) -> int:
        return self.dim


class _OllamaEmbeddingModel:
    """Ollama embedding model wrapper (e.g. nomic-embed-text)."""

    def __init__(self, model_name: str, base_url: str):
        self.model_name = model_name
        self.base_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        self._dim: int | None = None

    def _embed_one(self, text: str) -> List[float]:
        body = {"model": self.model_name, "prompt": text or ""}
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        vec = payload.get("embedding")
        if not isinstance(vec, list) or not vec:
            raise RuntimeError(f"Ollama embedding model {self.model_name} returned no embedding")
        if self._dim is None:
            self._dim = len(vec)
        return [float(v) for v in vec]

    def encode(self, chunks: List[str], show_progress_bar: bool = False):
        return np.array([self._embed_one(chunk) for chunk in chunks], dtype=np.float32)

    def get_sentence_embedding_dimension(self) -> int:
        if self._dim is None:
            self._dim = len(self._embed_one("dimension probe"))
        return self._dim


class _VectorCollection:
    """Minimal in-memory vector store backed by numpy."""

    def __init__(self, name: str):
        self.name = name
        self._ids: List[str] = []
        self._documents: List[str] = []
        self._metadatas: List[dict] = []
        self._embeddings: Optional[np.ndarray] = None  # shape (N, dim)

    def count(self) -> int:
        return len(self._ids)

    def add(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[dict],
    ) -> None:
        new_embed = np.array(embeddings, dtype=np.float32)
        if self._embeddings is None or len(self._embeddings) == 0:
            self._embeddings = new_embed
        else:
            self._embeddings = np.vstack([self._embeddings, new_embed])
        self._ids.extend(ids)
        self._documents.extend(documents)
        self._metadatas.extend(metadatas)

    def query(self, query_embedding: List[float], n_results: int) -> List[Tuple[str, dict, float]]:
        if self._embeddings is None or len(self._embeddings) == 0 or n_results <= 0:
            return []
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-10)
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True) + 1e-10
        normed = self._embeddings / norms
        similarities = normed @ q_norm  # cosine similarity
        k = min(n_results, len(self._ids))
        top_idx = np.argpartition(-similarities, k - 1)[:k]
        top_idx = top_idx[np.argsort(-similarities[top_idx])]
        results: List[Tuple[str, dict, float]] = []
        for idx in top_idx:
            dist = 1.0 - float(similarities[idx])
            results.append((self._documents[idx], self._metadatas[idx], dist))
        return results

    def clear(self) -> None:
        self._ids.clear()
        self._documents.clear()
        self._metadatas.clear()
        self._embeddings = None


_policy_collection: Optional[_VectorCollection] = None
_upload_collections: Dict[str, _VectorCollection] = {}

# Ollama / local API embedding model ids — not valid SentenceTransformer Hub names.
_OLLAMA_ONLY_EMBED_NAMES = frozenset(
    {
        "nomic-embed-text",
        "mxbai-embed-large",
        "snowflake-arctic-embed",
        "jina-embeddings-v2-base-en",
        "bge-m3",
        "bge-large-en-v1.5",
        "paraphrase-multilingual-minilm",
    }
)


def _is_ollama_only_embed_name(model_name: str) -> bool:
    """True when model_name must not be passed to SentenceTransformer()."""
    base = (model_name or "").strip().split(":")[0].strip().lower()
    if not base:
        return False
    if base in _OLLAMA_ONLY_EMBED_NAMES:
        return True
    if base.startswith("nomic-embed") or base.startswith("mxbai-embed"):
        return True
    return False


def _get_embedding_model():
    global _sentence_transformer
    if _sentence_transformer is None:
        configured = (agent_config.LOCAL_EMBED_MODEL or "").strip()
        if (agent_config.LOCAL_EMBED_BASE_URL or "").strip() and configured:
            try:
                _sentence_transformer = _OllamaEmbeddingModel(configured, agent_config.LOCAL_EMBED_BASE_URL)
                _sentence_transformer.get_sentence_embedding_dimension()
                return _sentence_transformer
            except Exception as e:
                logger.warning("Ollama embedding model failed (%s): %s", configured, e)
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "sentence-transformers is not importable. Install with: pip install sentence-transformers"
            ) from e
        candidates = []
        if configured and not _is_ollama_only_embed_name(configured):
            candidates.append(configured)
        # Runtime fallback for restricted networks / unavailable legal model.
        if "all-MiniLM-L6-v2" not in candidates:
            candidates.append("all-MiniLM-L6-v2")
        errors = []
        for model_name in candidates:
            try:
                _sentence_transformer = SentenceTransformer(model_name)
                if agent_config.DEBUG_AGENT and model_name != configured:
                    logger.warning("Embedding model fallback: %s -> %s", configured, model_name)
                break
            except Exception as e:
                errors.append(f"{model_name}: {type(e).__name__}: {e}")
        if _sentence_transformer is None:
            logger.warning(
                "Falling back to offline hash embeddings because model loading failed. Tried: %s",
                " | ".join(errors),
            )
            _sentence_transformer = _HashEmbeddingModel()
    return _sentence_transformer


def _get_policy_collection() -> _VectorCollection:
    global _policy_collection
    if _policy_collection is None:
        _policy_collection = _VectorCollection("poc_policy_clauses")
    return _policy_collection


def _get_upload_collection(session_id: str) -> _VectorCollection:
    key = _safe_collection_suffix(session_id)
    if key not in _upload_collections:
        _upload_collections[key] = _VectorCollection(f"uploads_{key}")
    return _upload_collections[key]


def _safe_collection_suffix(value: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in (value or "session"))
    return clean[:48] or "session"


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if end < len(text):
            paragraph_break = chunk.rfind("\n\n")
            sentence_break = chunk.rfind(". ")
            last_break = paragraph_break if paragraph_break > chunk_size // 3 else sentence_break
            if last_break > chunk_size // 2:
                chunk = chunk[: last_break + 1]
                end = start + len(chunk)
        chunks.append(chunk.strip())
        start = end - overlap if overlap < chunk_size else end
    return [c for c in chunks if c]


def _page_for_chunk(chunk: str, previous_page: int | None = None) -> int | None:
    """Infer page number from [PAGE N] markers inside a chunk."""
    import re

    matches = re.findall(r"\[PAGE\s+(\d+)\]", chunk or "", flags=re.IGNORECASE)
    if matches:
        try:
            return int(matches[-1])
        except ValueError:
            return previous_page
    return previous_page


def _embed(chunks: List[str]) -> List[List[float]]:
    model = _get_embedding_model()
    return model.encode(chunks, show_progress_bar=False).tolist()


def load_poc_and_index() -> int:
    """Load and index the POC knowledge file into the policy collection."""
    path = Path(agent_config.POC_KNOWLEDGE_PATH)
    if not path.exists():
        raise FileNotFoundError(f"POC knowledge file not found: {path}")

    if path.suffix.lower() == ".docx":
        from .knowledge_loader import load_knowledge_payload, payload_to_text

        payload = load_knowledge_payload(path)
        text = payload_to_text(payload)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    coll = _get_policy_collection()
    if coll.count() > 0:
        return 0

    embeds = _embed(chunks)
    ids = [f"poc_{i}" for i in range(len(chunks))]
    coll.add(
        ids=ids,
        embeddings=embeds,
        documents=chunks,
        metadatas=[{"source": "poc_doc"}] * len(chunks),
    )
    if agent_config.DEBUG_AGENT:
        logger.info("POC knowledge indexed: chunks=%d", len(chunks))
    return len(chunks)


def ensure_poc_indexed() -> bool:
    """Ensure policy collection has the POC document indexed."""
    coll = _get_policy_collection()
    if coll.count() > 0:
        return False
    load_poc_and_index()
    return True


def _chunk_metadata_hints(file_name: str) -> dict:
    """Extract appendix/schedule-style hints from filename for retrieval diagnostics."""
    fn = (file_name or "").lower()
    hints: list[str] = []
    for m in re.finditer(r"(?:appendix|annex|schedule|exhibit)[_\s\-\.]?([0-9]{1,3}|[a-z])\b", fn):
        hints.append(m.group(1))
    compact = re.sub(r"[^a-z0-9]+", "", fn)
    out: dict = {}
    if hints:
        out["filename_ref_tokens"] = ",".join(sorted(set(hints)))
    if compact:
        out["filename_compact"] = compact[:120]
    return out


def index_uploaded_text(session_id: str, file_name: str, text: str, *, doc_type: str = "upload") -> int:
    """Chunk + embed uploaded text into a session-scoped collection."""
    chunks = _chunk_text(text)
    if not chunks:
        return 0

    coll = _get_upload_collection(session_id)
    embeds = _embed(chunks)
    base = hashlib.sha1(f"{session_id}:{file_name}".encode("utf-8")).hexdigest()[:16]
    ids = [f"up_{base}_{i}" for i in range(len(chunks))]
    metadatas = []
    current_page: int | None = None
    fname_hints = _chunk_metadata_hints(file_name)
    for chunk in chunks:
        current_page = _page_for_chunk(chunk, current_page)
        meta = {
            "source": "upload",
            "file_name": file_name,
            "session_id": session_id,
            "doc_type": doc_type,
            "page": current_page,
        }
        meta.update(fname_hints)
        metadatas.append(meta)
    coll.add(
        ids=ids,
        embeddings=embeds,
        documents=chunks,
        metadatas=metadatas,
    )
    return len(chunks)


def retrieve_for_session(session_id: str, query: str, top_k: Optional[int] = None) -> List[Tuple[str, dict]]:
    """
    Retrieve from both policy collection and the current session's upload collection,
    then merge by ascending distance.
    """
    k = top_k or agent_config.RAG_TOP_K
    if k <= 0:
        return []

    model = _get_embedding_model()
    q_embed = model.encode([query], show_progress_bar=False).tolist()[0]

    per_source_k = max(2, k)
    merged: List[Tuple[str, dict, float]] = []

    policy_coll = _get_policy_collection()
    merged.extend(policy_coll.query(q_embed, per_source_k))

    upload_coll = _get_upload_collection(session_id)
    merged.extend(upload_coll.query(q_embed, per_source_k))

    # Prefer playbook (POC knowledge) chunks ahead of uploads for ideal-position grounding.
    merged.sort(
        key=lambda x: (
            0 if (isinstance(x[1], dict) and x[1].get("source") == "poc_doc") else 1,
            x[2],
        )
    )
    if getattr(agent_config, "ENABLE_RAG_CROSS_ENCODER_RERANK", False) and len(merged) >= 3:
        pool_n = min(
            len(merged),
            max(k * 2, int(getattr(agent_config, "RAG_RERANK_CANDIDATE_POOL", 32))),
        )
        pool = merged[:pool_n]
        texts = [t[0] for t in pool]
        model_name = (getattr(agent_config, "RAG_CROSS_ENCODER_MODEL", None) or "").strip()
        if model_name:
            order = rerank_indices_by_query(query, texts, model_name=model_name)
            merged = [pool[i] for i in order] + merged[pool_n:]
    out: List[Tuple[str, dict]] = []
    seen = set()
    for doc, meta, _ in merged:
        key = (doc[:80], meta.get("file_name") if isinstance(meta, dict) else None)
        if key in seen:
            continue
        seen.add(key)
        out.append((doc, meta if isinstance(meta, dict) else {}))
        if len(out) >= k:
            break
    return out


def clear_session_upload_index(session_id: str) -> None:
    """Delete and recreate the upload collection for a session."""
    key = _safe_collection_suffix(session_id)
    if key in _upload_collections:
        _upload_collections[key].clear()
