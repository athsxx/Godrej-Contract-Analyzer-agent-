"""Tests for master_orchestrator (delegation + model snapshot)."""

from __future__ import annotations

from unittest.mock import patch

import agents.sample_agent.config as agent_config
from agents.sample_agent.master_orchestrator import (
    run_contract_analysis_master,
    snapshot_local_models,
)


def test_snapshot_local_models_keys():
    m = snapshot_local_models()
    assert set(m.keys()) == {"default", "extraction", "chat", "editing", "classify"}
    assert all(isinstance(v, str) for v in m.values())


def test_run_contract_analysis_master_uses_orchestrator_when_langgraph_off():
    fake_rows = [{"clause_name": "Test", "risk_level": "Amber", "detected": "Unclear"}]

    def fake_pipeline(**kwargs):
        assert kwargs.get("uploaded_full_text") == "body"
        return (fake_rows, "a2", "a3")

    with patch.object(agent_config, "ENABLE_LANGGRAPH", False):
        with patch("agents.sample_agent.orchestrator.run_analysis_pipeline", side_effect=fake_pipeline):
            rows, a2, a3, warns, meta = run_contract_analysis_master(
                uploaded_full_text="body",
                primary_text="body",
                primary_name="c.docx",
                supporting_doc_texts={},
                uploaded_filenames_all=["c.docx"],
                knowledge_payload={},
                rag_session_id="sess1",
            )
    assert rows == fake_rows
    assert a2 == "a2" and a3 == "a3"
    assert meta.get("analysis_path") == "orchestrator"
    assert meta.get("row_count") == 1


def test_master_falls_through_to_agent1_when_orchestrator_empty():
    with patch.object(agent_config, "ENABLE_LANGGRAPH", False):
        with patch("agents.sample_agent.orchestrator.run_analysis_pipeline", return_value=([], "", "")):
            with patch(
                "agents.sample_agent.agent1_clause_analyzer.run_aerospace_clause_extraction",
                return_value=[{"clause_name": "FromAgent1"}],
            ):
                rows, a2, a3, _, meta = run_contract_analysis_master(
                    uploaded_full_text="x",
                    primary_text="x",
                    primary_name="",
                    supporting_doc_texts={},
                    uploaded_filenames_all=[],
                    knowledge_payload={},
                    rag_session_id="s",
                )
    assert len(rows) == 1
    assert rows[0].get("clause_name") == "FromAgent1"
    assert meta.get("analysis_path") == "agent1_only"
    assert a2 == "" and a3 == ""
