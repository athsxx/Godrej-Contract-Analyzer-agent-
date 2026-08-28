"""Lazy-loaded cross-encoder reranking for RAG chunks and evidence sentences."""

from __future__ import annotations

import logging
import os
from typing import List, Sequence, Tuple

logger = logging.getLogger(__name__)

_models: dict[Tuple[str, str], object] = {}
_failed_keys: set[Tuple[str, str]] = set()


def _device_for_cross_encoder() -> str:
    """Prefer CPU under Celery prefork: MPS in a forked worker often aborts (SIGABRT) on macOS."""
    try:
        from . import config as agent_config

        d = (getattr(agent_config, "CROSS_ENCODER_DEVICE", None) or "").strip().lower()
    except Exception:
        d = ""
    if d not in ("cpu", "cuda", "mps"):
        d = (os.environ.get("CROSS_ENCODER_DEVICE") or "cpu").strip().lower()
    if d not in ("cpu", "cuda", "mps"):
        return "cpu"
    return d


def rerank_indices_by_query(
    query: str,
    documents: Sequence[str],
    *,
    model_name: str,
) -> List[int]:
    """Return index order 0..n-1 by descending cross-encoder relevance.

    On load or predict failure, returns ``list(range(n))`` (identity order).
    """
    n = len(documents)
    if n == 0:
        return []
    name = (model_name or "").strip()
    if not name:
        return list(range(n))
    q = (query or "").strip()
    if not q:
        return list(range(n))
    device = _device_for_cross_encoder()
    cache_key = (name, device)
    if cache_key in _failed_keys:
        return list(range(n))
    model = _models.get(cache_key)
    if model is None:
        try:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(name, device=device)
            _models[cache_key] = model
            logger.info("CrossEncoder loaded model=%s device=%s", name, device)
        except Exception as e:
            logger.warning("CrossEncoder load failed (%s device=%s): %s", name, device, e)
            _failed_keys.add(cache_key)
            return list(range(n))
    pairs = [(q, (d or "")[:2000]) for d in documents]
    try:
        scores = model.predict(pairs, show_progress_bar=False)
    except Exception as e:
        logger.warning("CrossEncoder predict failed (%s): %s", name, e)
        return list(range(n))
    return sorted(range(n), key=lambda i: float(scores[i]), reverse=True)
