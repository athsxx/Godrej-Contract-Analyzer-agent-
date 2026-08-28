"""Supervisor + HITL stub pipeline (no Django DB)."""

from agents.sample_agent.supervisor_orchestrator import run_hitl_pipeline_locally


def test_run_hitl_pipeline_locally_returns_tuple():
    verified, comments = run_hitl_pipeline_locally({"doc": "stub"})
    assert verified == []
    assert comments == []


def test_run_hitl_pipeline_locally_section_headings():
    verified, comments = run_hitl_pipeline_locally(
        {"primary_text": "Article 5 — Liability\n\nSome body text.\n", "enable_llm_suggestions": False}
    )
    assert any(isinstance(x, dict) and x.get("kind") == "section_heading" for x in verified)
    assert isinstance(comments, list)

