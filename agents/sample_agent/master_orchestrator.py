"""Master orchestrator: single entry for analysis + explicit multi-model supervision.

Coordinates the same stages as ``chat_agent`` previously inlined (LangGraph path,
linear ``run_analysis_pipeline``, Agent 1-only fallback). Does **not** replace
``redline_docx`` / ``build_reviewed_contract_docx``; it logs which local models
(config per-role env vars) back semantic edits and Agent 4 during export.

Per-role models (all default to ``LOCAL_LLM_MODEL`` unless overridden):

- ``LOCAL_LLM_MODEL_EXTRACTION`` — Agent 1 structured extraction
- ``LOCAL_LLM_MODEL_CHAT`` — Agent 2 narrative when LLM-backed
- ``LOCAL_LLM_MODEL_EDITING`` — semantic paragraph rewrites in redline phase 3
- ``LOCAL_LLM_MODEL_CLASSIFY`` — Agent 4 / semantic-edit validation calls

Enable roster logging with ``DEBUG_AGENT=1`` or ``MASTER_ORCHESTRATOR_LOG=1``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def should_log_master_events() -> bool:
    try:
        from . import config as agent_config
    except ImportError:  # pragma: no cover
        import config as agent_config  # type: ignore

    return bool(getattr(agent_config, "DEBUG_AGENT", False)) or bool(
        getattr(agent_config, "MASTER_ORCHESTRATOR_LOG", False)
    )


def snapshot_local_models() -> Dict[str, str]:
    """Resolved Ollama (or other local) model id per orchestration role."""
    try:
        from . import config as c
    except ImportError:  # pragma: no cover
        import config as c  # type: ignore

    base = getattr(c, "LOCAL_LLM_MODEL", "") or ""
    return {
        "default": base,
        "extraction": getattr(c, "LOCAL_LLM_MODEL_EXTRACTION", base) or base,
        "chat": getattr(c, "LOCAL_LLM_MODEL_CHAT", base) or base,
        "editing": getattr(c, "LOCAL_LLM_MODEL_EDITING", base) or base,
        "classify": getattr(c, "LOCAL_LLM_MODEL_CLASSIFY", base) or base,
    }


def log_analysis_roster(extra: str | None = None) -> None:
    if not should_log_master_events():
        return
    try:
        from . import config as c
    except ImportError:  # pragma: no cover
        import config as c  # type: ignore

    m = snapshot_local_models()
    msg = (
        "master_orchestrator analysis roster: default=%s extraction=%s chat=%s editing=%s classify=%s "
        "ENABLE_LANGGRAPH=%s ENABLE_GRAPHRAG=%s LLM_PROVIDER=%s"
        % (
            m["default"],
            m["extraction"],
            m["chat"],
            m["editing"],
            m["classify"],
            getattr(c, "ENABLE_LANGGRAPH", False),
            getattr(c, "ENABLE_GRAPHRAG", False),
            getattr(c, "LLM_PROVIDER", "local"),
        )
    )
    if extra:
        msg = f"{msg} | {extra}"
    logger.info(msg)


def log_redline_export_roster() -> None:
    """Log which models back DOCX semantic edits and Agent 4 (called before export)."""
    if not should_log_master_events():
        return
    try:
        from . import config as c
    except ImportError:  # pragma: no cover
        import config as c  # type: ignore

    m = snapshot_local_models()
    logger.info(
        "master_orchestrator redline/DOCX roster: editing=%s classify=%s semantic_edits=%s "
        "agent4=%s parallel_redline=%s",
        m["editing"],
        m["classify"],
        getattr(c, "ENABLE_SEMANTIC_EDIT_GENERATION", False),
        getattr(c, "ENABLE_AGENT4_VERIFICATION", False),
        getattr(c, "ENABLE_PARALLEL_REDLINE", False),
    )


def run_contract_analysis_master(
    *,
    uploaded_full_text: str,
    primary_text: str,
    primary_name: str,
    supporting_doc_texts: Dict[str, str],
    uploaded_filenames_all: List[str],
    knowledge_payload: dict,
    rag_session_id: str,
) -> Tuple[List[Dict[str, Any]], str, str, List[str], Dict[str, Any]]:
    """Run clause analysis with LangGraph → orchestrator → Agent1 fallbacks.

    Returns:
        (clause_table, agent2_output, agent3_output, orchestration_warnings, meta)
    """
    try:
        from . import config as agent_config
    except ImportError:  # pragma: no cover
        import config as agent_config  # type: ignore

    orchestration_warnings: List[str] = []
    meta: Dict[str, Any] = {
        "analysis_path": None,
        "models": snapshot_local_models(),
        "langgraph_enabled": bool(getattr(agent_config, "ENABLE_LANGGRAPH", False)),
    }

    log_analysis_roster()
    clause_table: List[Dict[str, Any]] = []
    agent2_output = ""
    agent3_output = ""

    contract_text = primary_text or uploaded_full_text

    if getattr(agent_config, "ENABLE_LANGGRAPH", False):
        try:
            from .langgraph_pipeline import run_contract_analysis_graph

            graph_result = run_contract_analysis_graph(
                {
                    "primary_text": contract_text,
                    "primary_name": primary_name,
                    "supporting_doc_texts": supporting_doc_texts,
                    "uploaded_filenames": uploaded_filenames_all,
                    "knowledge_payload": knowledge_payload,
                    "warnings": [],
                    "rag_session_id": rag_session_id,
                },
                thread_id=rag_session_id,
            )
            if isinstance(graph_result, dict) and "__interrupt__" in graph_result:
                orchestration_warnings.append(
                    "Analysis paused for human review. Please upload missing documents or confirm proceed."
                )
                meta["analysis_path"] = "langgraph_interrupt"
            elif isinstance(graph_result, dict):
                clause_table = list(graph_result.get("clause_table") or [])
                agent2_output = str(graph_result.get("agent2_output") or "")
                agent3_output = str(graph_result.get("agent3_output") or "")
                orchestration_warnings.extend(list(graph_result.get("warnings") or []))
                meta["analysis_path"] = "langgraph"
            if should_log_master_events():
                logger.info("master_orchestrator: completed path=%s rows=%d", meta["analysis_path"], len(clause_table))
        except Exception as exc:
            if getattr(agent_config, "DEBUG_AGENT", False):
                logger.warning("LangGraph path failed; falling back to orchestrator: %s", exc)
            meta["langgraph_error"] = str(exc)

    if not clause_table:
        try:
            from .orchestrator import run_analysis_pipeline

            clause_table, agent2_output, agent3_output = run_analysis_pipeline(
                uploaded_full_text=contract_text,
                knowledge_payload=knowledge_payload,
                supporting_doc_texts=supporting_doc_texts or None,
                uploaded_filenames=uploaded_filenames_all,
                rag_session_id=rag_session_id,
            )
            meta["analysis_path"] = "orchestrator"
            if should_log_master_events():
                logger.info(
                    "master_orchestrator: orchestrator path rows=%d agent2_chars=%d",
                    len(clause_table),
                    len(agent2_output or ""),
                )
        except Exception as exc:
            if getattr(agent_config, "DEBUG_AGENT", False):
                logger.warning("Orchestrator path failed; falling back to Agent1: %s", exc)
            meta["orchestrator_error"] = str(exc)

    if not clause_table:
        try:
            try:
                from agents.sample_agent import agent1_clause_analyzer as agent1  # type: ignore
            except ImportError:  # pragma: no cover
                import agent1_clause_analyzer as agent1  # type: ignore

            clause_table = agent1.run_aerospace_clause_extraction(
                contract_text=contract_text,
                knowledge_payload=knowledge_payload,
                supporting_doc_texts=supporting_doc_texts or None,
                uploaded_filenames=uploaded_filenames_all,
                rag_session_id=rag_session_id,
            )
            agent2_output = ""
            agent3_output = ""
            meta["analysis_path"] = "agent1_only"
            if should_log_master_events():
                logger.info("master_orchestrator: Agent1-only fallback rows=%d", len(clause_table))
        except Exception as exc:
            if getattr(agent_config, "DEBUG_AGENT", False):
                logger.warning("Agent1 extraction failed: %s", exc)
            meta["agent1_error"] = str(exc)

    meta["row_count"] = len(clause_table)
    return clause_table, agent2_output, agent3_output, orchestration_warnings, meta
