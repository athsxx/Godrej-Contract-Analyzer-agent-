"""Tests for in-repo GraphRAG-lite (entity–chunk graph)."""

from __future__ import annotations

from agents.sample_agent.graphrag_lite import (
    build_lite_chunk_graph,
    build_session_doc_texts,
    clause_table_retrieval_seed,
    compute_graphrag_context,
    retrieve_cross_doc_context,
)


def test_shared_exhibit_bridges_documents():
    primary = "The rates are set forth in Exhibit A attached hereto."
    supporting = "Exhibit A\n\nWidgetCo shall pay SupplierCo fifty dollars per unit for all deliveries."
    g = build_lite_chunk_graph(build_session_doc_texts("MSA.docx", primary, {"Exhibit_A.docx": supporting}))
    assert g.chunks
    seed = "Payment terms per Exhibit A and WidgetCo obligations."
    ctx = retrieve_cross_doc_context(g, seed, max_chars=4000)
    assert "Exhibit" in ctx or "WidgetCo" in ctx or "fifty" in ctx


def test_compute_graphrag_context_uses_clause_seed():
    clause_table = [
        {
            "clause_name": "Payment",
            "evidence_snippet": "See Schedule B for payment milestones.",
        }
    ]
    primary = "This Agreement references Schedule B for invoicing."
    supporting = {"Schedule_B.docx": "Schedule B requires net thirty payment after acceptance." * 3}
    out = compute_graphrag_context(
        primary_name="deal.docx",
        primary_text=primary,
        supporting_doc_texts=supporting,
        clause_table=clause_table,
        max_chars=5000,
    )
    assert "Schedule" in out or "payment" in out.lower()


def test_clause_table_retrieval_seed_empty():
    assert clause_table_retrieval_seed([]) == ""


def test_langgraph_build_graph_import():
    from agents.sample_agent.langgraph_pipeline import build_graph

    g = build_graph()
    assert g is not None
