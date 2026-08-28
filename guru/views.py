"""Views: home, Aerospace Contract Analyzer, login. All linked from sidebar."""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect

from agents.sample_agent import chat_agent as sample_agent
from agents.sample_agent import config as agent_config

from guru.models import ExecutiveFeedback

# Session keys: clause row ids (1-based strings) the user accepted for DOCX body redlines.
REDLINE_ACCEPTED_SESSION_KEY = "redline_accepted_clause_ids"


def _redline_acceptance_from_session(request) -> list[str]:
    raw = request.session.get(REDLINE_ACCEPTED_SESSION_KEY)
    if not raw or not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _redline_accepted_ints_for_template(request) -> list[int]:
    out: list[int] = []
    for x in _redline_acceptance_from_session(request):
        try:
            out.append(int(x))
        except ValueError:
            continue
    return out


def _session_upload_digest(session_key: str) -> str:
    """Stable fingerprint of on-disk uploads for AnalysisJob.input_hash."""
    root = Path(sample_agent.UPLOAD_ROOT) / session_key
    if not root.is_dir():
        return ""
    parts: list[str] = []
    for p in sorted(root.iterdir()):
        if not p.is_file():
            continue
        if p.name in {"_upload_roles.json", "_chat_history.json"}:
            continue
        try:
            parts.append(f"{p.name}:{p.stat().st_mtime_ns}")
        except OSError:
            parts.append(p.name)
    if not parts:
        return ""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:48]


def _as_download(path: Path, filename: str, content_type: str) -> FileResponse:
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )


def home(request):
    """Landing page; links to Aerospace > Contract Analyzer and other workspaces."""
    context = {
        "current_time": timezone.now().strftime("%b %d, %Y • %I:%M %p"),
    }
    return render(request, "guru/home.html", context)


@csrf_protect
def workspace_aerospace_contract_analyzer(request):
    """Aerospace Contract Analyzer (POC): 14 clause themes (Agent 1 checklist), RAG, local LLM, counterfactuals."""
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    if not session_key:
        raise RuntimeError("Failed to initialize session key for workspace.")
    session_out = sample_agent.export_session_state(session_key)
    history = session_out.get("history") or []
    has_clause_analysis = any(
        m.get("role") == "assistant" and (m.get("clause_table") or []) for m in history
    )
    context = {
        "nav_left_label": "Aerospace • Contract Analyzer",
        "current_time": timezone.now().strftime("%b %d, %Y • %I:%M %p"),
        "uploaded_files": sample_agent.list_files(session_key),
        "chat_history": history,
        "has_clause_analysis": has_clause_analysis,
        "allowed_extensions": sorted(sample_agent.ALLOWED_EXTENSIONS),
        "hero_title": "Aerospace Contract Analyzer",
        "hero_subtitle": (
            "Upload the primary agreement for analysis (DOCX/PDF). Add supporting schedules only as "
            "read‑only context — redlines apply to the contract file only. Use **Analyze clauses** (no chat)."
        ),
    }

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "reset":
            sample_agent.reset_session(session_key)
            request.session.pop(REDLINE_ACCEPTED_SESSION_KEY, None)
            return redirect(request.path)

        if action == "save_redline_acceptance":
            ids = [str(x) for x in request.POST.getlist("accepted_clause") if str(x).strip()]
            request.session[REDLINE_ACCEPTED_SESSION_KEY] = ids
            request.session.modified = True
            return redirect(request.path)

        if action == "save_executive_feedback":
            notes = (request.POST.get("executive_feedback_notes") or "").strip()
            if notes:
                ExecutiveFeedback.objects.create(session_id=session_key, notes=notes, extra={})
            return redirect(request.path)

        if action == "remove_file":
            filename = request.POST.get("filename") or ""
            outcome = sample_agent.remove_uploaded_file(session_key, filename)
            context["uploaded_files"] = outcome.get("files", [])

        elif action == "upload":
            uploads = request.FILES.getlist("files")
            upload_role = request.POST.get("upload_role") or "auto"
            try:
                result = sample_agent.index_uploaded_files(session_key, uploads, upload_role=upload_role)
                context["uploaded_files"] = result.get("files", [])
                context["warnings"] = result.get("warnings", [])
            except Exception as err:
                context["error"] = str(err)

        elif action == "ask" or action == "analyze_clauses":
            message = (
                "[Analyze clauses]"
                if action == "analyze_clauses"
                else (request.POST.get("message") or "")
            )
            try:
                result = sample_agent.answer_question(session_key, message)
                context["chat_history"] = result.get("chat_history", [])
                context["has_clause_analysis"] = any(
                    m.get("role") == "assistant" and (m.get("clause_table") or [])
                    for m in (result.get("chat_history") or [])
                )
                context["assistant_reply"] = result.get("answer", "")
                context["assistant_counterfactuals"] = result.get("counterfactuals")
                context["warnings"] = result.get("warnings", [])
                context["uploaded_files"] = sample_agent.list_files(session_key)
                request.session[REDLINE_ACCEPTED_SESSION_KEY] = []
                request.session.modified = True
            except Exception as err:
                context["error"] = str(err)

        elif action == "analyze_clauses_async":
            if not getattr(agent_config, "ENABLE_ASYNC_CONTRACT_ANALYSIS", False):
                return JsonResponse({"error": "async_disabled"}, status=400)
            try:
                from agents.sample_agent.supervisor_orchestrator import enqueue_detection_job

                digest = _session_upload_digest(session_key)
                request.session[REDLINE_ACCEPTED_SESSION_KEY] = []
                request.session.modified = True
                job_id = enqueue_detection_job(session_id=session_key, input_hash=digest)
                rel = f"/api/analysis/jobs/{job_id}/"
                poll_url = request.build_absolute_uri(rel) if hasattr(request, "build_absolute_uri") else rel
                return JsonResponse({"job_id": job_id, "poll_url": poll_url, "status": "queued"}, status=202)
            except Exception as err:
                return JsonResponse({"error": str(err)}, status=500)

        elif action == "export_reviewed_docx":
            if not getattr(agent_config, "ENABLE_REDLINE_DOCX_EXPORT", False):
                context["error"] = (
                    "Reviewed-contract redline export is disabled. "
                    "Detection and clause analysis are unchanged; set ENABLE_REDLINE_DOCX_EXPORT=1 to re-enable."
                )
            else:
                try:
                    accepted = _redline_acceptance_from_session(request)
                    result = sample_agent.generate_reviewed_contract_docx(
                        session_key,
                        accepted_clause_ids=accepted,
                    )
                    path = Path(result["path"])
                    return _as_download(
                        path=path,
                        filename="reviewed_contract.docx",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                except Exception as err:
                    context["error"] = str(err)

        elif action == "export_verification_report_csv":
            if not getattr(agent_config, "ENABLE_REDLINE_DOCX_EXPORT", False):
                context["error"] = (
                    "Verification CSV is tied to redline export, which is disabled. "
                    "Set ENABLE_REDLINE_DOCX_EXPORT=1 to re-enable."
                )
            else:
                try:
                    result = sample_agent.generate_verification_report_csv(session_key)
                    path = Path(result["path"])
                    return _as_download(
                        path=path,
                        filename=result.get("filename", "verification_report.csv"),
                        content_type="text/csv",
                    )
                except Exception as err:
                    context["error"] = str(err)

        elif action == "export_table_csv":
            try:
                result = sample_agent.generate_clause_table_csv(session_key)
                path = Path(result["path"])
                return _as_download(
                    path=path,
                    filename="clause_analysis.csv",
                    content_type="text/csv",
                )
            except Exception as err:
                context["error"] = str(err)

        elif action == "export_contract_commentary_docx":
            if not getattr(agent_config, "ENABLE_CONTRACT_COMMENTARY_DOCX", True):
                context["error"] = "Commentary DOCX export is disabled (ENABLE_CONTRACT_COMMENTARY_DOCX)."
            else:
                try:
                    result = sample_agent.generate_contract_commentary_docx(session_key)
                    path = Path(result["path"])
                    return _as_download(
                        path=path,
                        filename=result.get("filename", "contract_with_review_comments.docx"),
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                except Exception as err:
                    context["error"] = str(err)

        elif action == "export_counterfactuals_csv":
            try:
                result = sample_agent.generate_counterfactuals_csv(session_key)
                path = Path(result["path"])
                return _as_download(
                    path=path,
                    filename=result.get("filename", "counterfactuals.csv"),
                    content_type="text/csv",
                )
            except Exception as err:
                context["error"] = str(err)

        elif action == "export_mitigation_checklist_csv":
            try:
                result = sample_agent.generate_mitigation_checklist_csv(session_key)
                path = Path(result["path"])
                return _as_download(
                    path=path,
                    filename=result.get("filename", "mitigation_checklist.csv"),
                    content_type="text/csv",
                )
            except Exception as err:
                context["error"] = str(err)

    hist = sample_agent.export_session_state(session_key).get("history") or []
    context["chat_history"] = hist
    context["has_clause_analysis"] = any(
        m.get("role") == "assistant" and (m.get("clause_table") or []) for m in hist
    )
    last_clause_idx: int | None = None
    for i in range(len(hist) - 1, -1, -1):
        m = hist[i]
        if m.get("role") == "assistant" and (m.get("clause_table") or []):
            last_clause_idx = i
            break
    context["redline_table_message_index"] = last_clause_idx
    context["require_redline_hitl"] = getattr(agent_config, "REQUIRE_REDLINE_HITL_ACCEPTANCE", True)
    context["redline_accepted_id_list"] = _redline_accepted_ints_for_template(request)
    context["enable_async_contract_analysis"] = getattr(
        agent_config, "ENABLE_ASYNC_CONTRACT_ANALYSIS", False
    )
    context["enable_redline_docx_export"] = getattr(agent_config, "ENABLE_REDLINE_DOCX_EXPORT", False)
    context["enable_contract_commentary_docx"] = getattr(
        agent_config, "ENABLE_CONTRACT_COMMENTARY_DOCX", True
    )
    context["enable_executive_read"] = getattr(agent_config, "ENABLE_EXECUTIVE_READ", True)
    context["executive_feedback_recent"] = list(
        ExecutiveFeedback.objects.filter(session_id=session_key).order_by("-created_at")[:8]
    )

    return render(request, "guru/workspace_aerospace_contract_analyzer.html", context)


def download_reviewed_contract_docx(request):
    """Download the latest generated reviewed contract DOCX for this session."""
    if not getattr(agent_config, "ENABLE_REDLINE_DOCX_EXPORT", False):
        raise Http404("Reviewed-contract download is disabled (ENABLE_REDLINE_DOCX_EXPORT).")
    session_key = request.session.session_key
    if not session_key:
        raise Http404("Session not initialized.")
    path = Path(sample_agent.UPLOAD_ROOT) / session_key / "reviewed_contract.docx"
    if not path.exists():
        raise Http404("Reviewed contract not found. Generate it first.")
    return _as_download(
        path=path,
        filename="reviewed_contract.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def download_clause_csv(request):
    """Download the latest generated clause table CSV for this session."""
    session_key = request.session.session_key
    if not session_key:
        raise Http404("Session not initialized.")
    path = Path(sample_agent.UPLOAD_ROOT) / session_key / "clause_analysis.csv"
    if not path.exists():
        raise Http404("Clause CSV not found. Generate it first.")
    return _as_download(
        path=path,
        filename="clause_analysis.csv",
        content_type="text/csv",
    )


def download_contract_commentary_docx(request):
    """Download primary contract DOCX with Word review comments only (no body redlines)."""
    if not getattr(agent_config, "ENABLE_CONTRACT_COMMENTARY_DOCX", True):
        raise Http404("Contract commentary DOCX is disabled (ENABLE_CONTRACT_COMMENTARY_DOCX).")
    session_key = request.session.session_key
    if not session_key:
        raise Http404("Session not initialized.")
    try:
        result = sample_agent.generate_contract_commentary_docx(session_key)
        path = Path(result["path"])
    except ValueError as exc:
        raise Http404(str(exc)) from exc
    if not path.exists():
        raise Http404("Commentary DOCX was not created.")
    return _as_download(
        path=path,
        filename="contract_with_review_comments.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def login(request):
    """Render a simple Microsoft SSO entrypoint for the cutout."""
    return render(request, "guru/login.html")
