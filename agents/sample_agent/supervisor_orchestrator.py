"""Supervisor orchestration agent: owns HITL pipeline ordering and background job dispatch.

Logical **subagents** (single process today; can map to separate services later):

1. **Deterministic worker** — ``hitl_orchestrator.deterministic_pass``
2. **LLM suggest worker** — ``hitl_orchestrator.llm_suggest_pass`` (optional Ollama JSON when ``enable_llm_suggestions`` + ``ENABLE_HITL_PIPELINE_LLM``)
3. **Verifier** — ``hitl_orchestrator.verify_pass``
4. **Comment builder** — ``hitl_orchestrator.build_comment_specs``

The supervisor **sequences** these stages, merges findings, and (optionally) persists
results via **Celery** + ``AnalysisJob`` / ``AnalysisArtifact``. It does not perform
RLHF; human approval remains a product step above this layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Tuple

from agents.sample_agent.hitl_orchestrator import (
    build_comment_specs,
    deterministic_pass,
    llm_suggest_pass,
    verify_pass,
)


def run_hitl_pipeline_locally(document_context: Mapping[str, Any] | None = None) -> Tuple[List[Any], List[MutableMapping[str, Any]]]:
    """Run all stages in-process (no Celery). Returns (verified_findings, comment_specs)."""
    ctx = dict(document_context or {})
    raw = list(deterministic_pass(ctx)) + list(llm_suggest_pass(ctx))
    verified = list(verify_pass(raw))
    comments = build_comment_specs(verified)
    return verified, comments


def enqueue_detection_job(*, session_id: str = "", input_hash: str = "") -> str:
    """Create a queued ``AnalysisJob`` and dispatch ``run_detection_analysis_job`` (Celery).

    Returns the job UUID string. When ``CELERY_TASK_ALWAYS_EAGER=1``, runs inline.
    """
    from agents.sample_agent import config as ac
    from agents.sample_agent.master_orchestrator import snapshot_local_models
    from guru.models import AnalysisJob
    from guru.tasks import run_detection_analysis_job

    config_snapshot = {
        "models": snapshot_local_models(),
        "ENABLE_LANGGRAPH": bool(getattr(ac, "ENABLE_LANGGRAPH", False)),
        "ENABLE_ASYNC_CONTRACT_ANALYSIS": bool(getattr(ac, "ENABLE_ASYNC_CONTRACT_ANALYSIS", False)),
        "ENABLE_HITL_PIPELINE_LLM": bool(getattr(ac, "ENABLE_HITL_PIPELINE_LLM", False)),
    }
    job = AnalysisJob.objects.create(
        session_id=session_id or "",
        status=AnalysisJob.Status.QUEUED,
        input_hash=input_hash or "",
        config_snapshot=config_snapshot,
    )
    run_detection_analysis_job.delay(str(job.pk))
    return str(job.pk)
