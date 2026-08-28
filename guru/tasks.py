"""Celery tasks for guru."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from guru.models import AnalysisArtifact, AnalysisJob

logger = logging.getLogger(__name__)


@shared_task
def run_detection_analysis_job(job_id: str) -> None:
    """Run full contract analysis via ``chat_agent`` and persist clause table + trace artifacts."""
    try:
        job = AnalysisJob.objects.get(pk=job_id)
    except AnalysisJob.DoesNotExist:
        return

    session_id = (job.session_id or "").strip()
    if not session_id:
        with transaction.atomic():
            job = AnalysisJob.objects.select_for_update().get(pk=job_id)
            job.status = AnalysisJob.Status.FAILED
            job.error_message = "Missing session_id on job"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return

    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(pk=job_id)
        job.status = AnalysisJob.Status.RUNNING
        job.error_message = ""
        job.started_at = timezone.now()
        job.save(update_fields=["status", "error_message", "started_at", "updated_at"])
        AnalysisArtifact.objects.filter(job=job).delete()

    try:
        from agents.sample_agent import chat_agent as ca
        from agents.sample_agent import config as agent_config
        from agents.sample_agent.supervisor_orchestrator import run_hitl_pipeline_locally

        result = ca.run_detection_analysis_for_session(session_id, message="[Analyze clauses]")
        warnings = list(result.get("warnings") or [])
        hist = result.get("chat_history") or []
        last_assistant: dict | None = None
        for m in reversed(hist):
            if m.get("role") == "assistant" and m.get("clause_table"):
                last_assistant = m
                break
        clause_table = list(last_assistant.get("clause_table") or []) if last_assistant else []
        meta = dict(last_assistant.get("orchestration_meta") or {}) if last_assistant else {}

        primary_snippet = ""
        try:
            from agents.sample_agent.chat_agent import _ensure_session, _primary_readable_artifact

            prim = _primary_readable_artifact(_ensure_session(session_id))
            if prim is not None:
                primary_snippet = str(prim.extras.get("full_text") or "")[:24_000]
        except Exception:
            primary_snippet = ""

        hitl_ctx = {
            "primary_text": primary_snippet,
            "enable_llm_suggestions": bool(getattr(agent_config, "ENABLE_HITL_PIPELINE_LLM", False)),
        }
        verified, comment_specs = run_hitl_pipeline_locally(hitl_ctx)

        with transaction.atomic():
            job = AnalysisJob.objects.select_for_update().get(pk=job_id)
            AnalysisArtifact.objects.create(
                job=job,
                kind=AnalysisArtifact.Kind.TRACE,
                version=1,
                payload={
                    "orchestration_meta": meta,
                    "analysis_warnings": warnings,
                    "hitl_sidecar": {
                        "verified_count": len(verified),
                        "comment_specs_count": len(comment_specs),
                        "sample_findings": verified[:12],
                    },
                },
            )
            AnalysisArtifact.objects.create(
                job=job,
                kind=AnalysisArtifact.Kind.CLAUSE_TABLE,
                version=1,
                payload={"rows": clause_table},
            )
            para_idx = (last_assistant or {}).get("paragraph_index") if last_assistant else None
            if para_idx:
                AnalysisArtifact.objects.create(
                    job=job,
                    kind=AnalysisArtifact.Kind.PARAGRAPH_MAP,
                    version=1,
                    payload={"paragraphs": para_idx},
                )
            exec_payload = (last_assistant or {}).get("executive_read") if last_assistant else None
            if exec_payload:
                AnalysisArtifact.objects.create(
                    job=job,
                    kind=AnalysisArtifact.Kind.EXECUTIVE_READ,
                    version=1,
                    payload=exec_payload if isinstance(exec_payload, dict) else {"raw": exec_payload},
                )
            if comment_specs:
                AnalysisArtifact.objects.create(
                    job=job,
                    kind=AnalysisArtifact.Kind.SUGGESTIONS,
                    version=1,
                    payload={"comment_specs": comment_specs},
                )
            job.status = AnalysisJob.Status.SUCCEEDED
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at", "updated_at"])
    except Exception as exc:
        logger.exception("run_detection_analysis_job failed job_id=%s", job_id)
        with transaction.atomic():
            job = AnalysisJob.objects.select_for_update().get(pk=job_id)
            job.status = AnalysisJob.Status.FAILED
            job.error_message = str(exc)[:8000]
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        raise
