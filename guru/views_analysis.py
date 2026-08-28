"""JSON API for analysis jobs (Celery-backed detection pipeline)."""

from __future__ import annotations

import json
from typing import Any, Dict

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from guru.models import AnalysisArtifact, AnalysisJob


def _job_summary(job: AnalysisJob) -> Dict[str, Any]:
    arts = job.artifacts.order_by("created_at")
    summary: Dict[str, Any] = {
        "id": str(job.pk),
        "status": job.status,
        "session_id": job.session_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_message": job.error_message or "",
        "artifacts": [{"kind": a.kind, "version": a.version, "created_at": a.created_at.isoformat()} for a in arts],
    }
    if job.status == AnalysisJob.Status.SUCCEEDED:
        ct = (
            job.artifacts.filter(kind=AnalysisArtifact.Kind.CLAUSE_TABLE)
            .order_by("-created_at")
            .first()
        )
        if ct and isinstance(ct.payload, dict):
            rows = ct.payload.get("rows")
            if isinstance(rows, list):
                summary["clause_table_row_count"] = len(rows)
        er = (
            job.artifacts.filter(kind=AnalysisArtifact.Kind.EXECUTIVE_READ)
            .order_by("-created_at")
            .first()
        )
        if er and isinstance(er.payload, dict):
            items = er.payload.get("executive_items")
            if isinstance(items, list):
                summary["executive_read_item_count"] = len(items)
    return summary


@csrf_exempt
@require_http_methods(["POST"])
def analysis_job_create(request) -> JsonResponse:
    """POST JSON { \"session_id\": \"...\", \"input_hash\": \"...\" } → { \"job_id\": \"...\" }."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        body = {}
    session_id = str(body.get("session_id") or request.session.session_key or "")
    input_hash = str(body.get("input_hash") or "")

    from agents.sample_agent.supervisor_orchestrator import enqueue_detection_job

    job_id = enqueue_detection_job(session_id=session_id, input_hash=input_hash)
    return JsonResponse({"job_id": job_id}, status=201)


@csrf_exempt
@require_GET
def analysis_job_detail(request, job_id: str) -> JsonResponse:
    """GET /api/analysis/jobs/<uuid>/ — status + artifact list (payload omitted for brevity)."""
    try:
        job = AnalysisJob.objects.get(pk=job_id)
    except (AnalysisJob.DoesNotExist, ValueError):
        return JsonResponse({"error": "not_found"}, status=404)
    data = _job_summary(job)
    if request.GET.get("include_payload") == "1":
        data["payloads"] = [
            {"kind": a.kind, "version": a.version, "payload": a.payload} for a in job.artifacts.order_by("created_at")
        ]
    return JsonResponse(data)
