"""LangGraph orchestration for contract analysis.

Wraps existing agents as graph nodes. Agent 1 remains deterministic.
Human-in-loop interrupts are not used here: the Django UI invokes ``invoke``
once per request, so interrupts would yield incomplete analyses. Missing-doc
warnings are surfaced in state instead; full resume-based HITL can be added
when the client supports threading.

Redlines and DOCX export are **not** produced by this graph: they remain in
``redline_docx.build_reviewed_contract_docx`` via ``chat_agent.generate_reviewed_contract_docx``.
Nodes ``build_redlines``, ``agent4_verify``, and ``apply_redlines`` are placeholders
for future observability only.

Optional **GraphRAG-lite** node (``ENABLE_GRAPHRAG=1``) builds an entity–chunk graph
over the primary contract plus supporting uploads and expands context for Agent 2
only (see ``graphrag_lite.py``). It does not replace vector RAG or Microsoft GraphRAG.

Enable the graph runner with ``ENABLE_LANGGRAPH=1``; enable cross-doc context with
``ENABLE_GRAPHRAG=1`` (see ``config.py``).
"""


from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class ContractAnalysisState(TypedDict, total=False):
    primary_text: str
    primary_name: str
    supporting_doc_texts: Dict[str, str]
    uploaded_filenames: List[str]
    knowledge_payload: dict
    rag_session_id: str
    referenced_docs: List[dict]
    missing_docs: List[dict]
    user_confirmed_proceed: bool
    clause_table: List[Dict[str, str]]
    agent2_output: str
    agent3_output: str
    proposed_redlines: List[dict]
    agent4_flags: List[dict]
    approved_redlines: List[dict]
    warnings: List[str]
    graphrag_context: str


def _agent1_extract(state: ContractAnalysisState) -> ContractAnalysisState:
    try:
        from agents.sample_agent import agent1_clause_analyzer as agent1  # type: ignore
    except ImportError:  # pragma: no cover
        import agent1_clause_analyzer as agent1  # type: ignore

    clause_table = agent1.run_aerospace_clause_extraction(
        contract_text=state.get("primary_text", ""),
        knowledge_payload=state.get("knowledge_payload", {}),
        supporting_doc_texts=state.get("supporting_doc_texts") or None,
        uploaded_filenames=state.get("uploaded_filenames") or None,
        rag_session_id=state.get("rag_session_id"),
    )
    referenced = []
    missing = []
    if clause_table:
        first = clause_table[0]
        referenced = list(first.get("_referenced_supporting_docs") or [])
        missing = list(first.get("_missing_supporting_docs") or [])
    return {
        **state,
        "clause_table": clause_table,
        "referenced_docs": referenced,
        "missing_docs": missing,
    }


def _check_missing_docs(state: ContractAnalysisState) -> ContractAnalysisState:
    warnings = list(state.get("warnings") or [])
    missing = state.get("missing_docs") or []
    if missing:
        labels = ", ".join([str(d.get("label", "")) for d in missing[:8] if d.get("label")])
        warnings.append(
            f"Supporting documents referenced but not uploaded: {labels}. "
            "Upload them or confirm that analysis should proceed without them."
        )
    return {**state, "warnings": warnings}


def _graphrag_enrich(state: ContractAnalysisState) -> ContractAnalysisState:
    try:
        from . import config as agent_config
    except ImportError:  # pragma: no cover
        import config as agent_config  # type: ignore

    if not getattr(agent_config, "ENABLE_GRAPHRAG", False):
        return {**state, "graphrag_context": ""}
    try:
        from .graphrag_lite import compute_graphrag_context
    except ImportError:  # pragma: no cover
        return {**state, "graphrag_context": ""}

    max_chars = int(getattr(agent_config, "GRAPHRAG_MAX_CHARS", 3500) or 3500)
    ctx = compute_graphrag_context(
        primary_name=str(state.get("primary_name") or ""),
        primary_text=str(state.get("primary_text") or ""),
        supporting_doc_texts=state.get("supporting_doc_texts") or {},
        clause_table=state.get("clause_table") or [],
        max_chars=max_chars,
    )
    return {**state, "graphrag_context": ctx or ""}


def _to_agent1_style_markdown(rows: List[Dict[str, str]]) -> str:
    lines = [
        "| Clause | Requirement | Met/Gap | References |",
        "|--------|-------------|---------|------------|",
    ]
    for idx, row in enumerate(rows or [], start=1):
        clause = row.get("clause_name", "")
        requirement = row.get("gb_ideal_position", "")
        risk = row.get("risk_level", "Amber")
        status = row.get("detected", "Unclear")
        rationale = row.get("risk_rationale", "")
        references = row.get("knowledge_reference", "")
        lines.append(f"| {idx}. {clause} | {requirement} | {status} ({risk}) - {rationale} | {references} |")
    return "\n".join(lines)


def _knowledge_as_text(payload: dict) -> str:
    if not payload:
        return ""
    if payload.get("raw_text"):
        return str(payload.get("raw_text"))
    from .knowledge_loader import payload_to_text

    return payload_to_text(payload)


def _agent2_review(state: ContractAnalysisState) -> ContractAnalysisState:
    try:
        from agents.sample_agent import agent2_reviewer as agent2  # type: ignore
    except ImportError:  # pragma: no cover
        import agent2_reviewer as agent2  # type: ignore

    clause_table = state.get("clause_table") or []
    po = str(state.get("primary_text") or "")
    gr = str(state.get("graphrag_context") or "").strip()
    if gr:
        po = f"{po}\n\n### Cross-document context (GraphRAG-lite)\n{gr}"
    agent2_output = agent2.generate_risk_mitigation(
        agent1_output=_to_agent1_style_markdown(clause_table),
        po_text=po,
        terms_text=_knowledge_as_text(state.get("knowledge_payload", {})),
        clause_table=clause_table,
    )
    return {**state, "agent2_output": agent2_output}


def _agent3_checklist(state: ContractAnalysisState) -> ContractAnalysisState:
    try:
        from agents.sample_agent import agent3_mitigation_checklist as agent3  # type: ignore
    except ImportError:  # pragma: no cover
        import agent3_mitigation_checklist as agent3  # type: ignore

    if hasattr(agent3, "generate_mitigation_checklist_from_table"):
        agent3_output = agent3.generate_mitigation_checklist_from_table(state.get("clause_table") or [])
    else:
        agent3_output = agent3.generate_mitigation_checklist(state.get("agent2_output") or "")
    return {**state, "agent3_output": agent3_output}


def _build_redlines(state: ContractAnalysisState) -> ContractAnalysisState:
    # The reviewed-DOCX export path still owns actual paragraph matching and edit application.
    # This node reserves the state slot so redline verification can become graph-native.
    return {**state, "proposed_redlines": state.get("proposed_redlines") or []}


def _agent4_verify(state: ContractAnalysisState) -> ContractAnalysisState:
    # Agent 4 is invoked by the redline DOCX builder today. Keep this node as a graph gate
    # for future graph-native redline flows.
    return {**state, "agent4_flags": state.get("agent4_flags") or []}


def _apply_redlines(state: ContractAnalysisState) -> ContractAnalysisState:
    return {**state, "approved_redlines": state.get("approved_redlines") or state.get("proposed_redlines") or []}


def build_graph():
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.memory import MemorySaver

    # Linear pipeline: interrupts are disabled — see module docstring.
    graph = StateGraph(ContractAnalysisState)
    graph.add_node("agent1_extract", _agent1_extract)
    graph.add_node("check_missing_docs", _check_missing_docs)
    graph.add_node("graphrag_enrich", _graphrag_enrich)
    graph.add_node("agent2_review", _agent2_review)
    graph.add_node("agent3_checklist", _agent3_checklist)
    graph.add_node("build_redlines", _build_redlines)
    graph.add_node("agent4_verify", _agent4_verify)
    graph.add_node("apply_redlines", _apply_redlines)

    graph.set_entry_point("agent1_extract")
    graph.add_edge("agent1_extract", "check_missing_docs")
    graph.add_edge("check_missing_docs", "graphrag_enrich")
    graph.add_edge("graphrag_enrich", "agent2_review")
    graph.add_edge("agent2_review", "agent3_checklist")
    graph.add_edge("agent3_checklist", "build_redlines")
    graph.add_edge("build_redlines", "agent4_verify")
    graph.add_edge("agent4_verify", "apply_redlines")
    graph.add_edge("apply_redlines", END)
    return graph.compile(checkpointer=MemorySaver())


def run_contract_analysis_graph(state: ContractAnalysisState, *, thread_id: str) -> ContractAnalysisState:
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id or "default"}}
    return graph.invoke(state, config=config)

