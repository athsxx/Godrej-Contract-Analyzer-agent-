"""ANALYZER_PRESET / DETERMINISTIC_CONTRACT_MODE wiring."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reload_sample_agent_config_after_test():
    yield
    import agents.sample_agent.config as cfg

    importlib.reload(cfg)


def test_analyzer_preset_structured(monkeypatch):
    monkeypatch.setenv("ANALYZER_PRESET", "structured")
    monkeypatch.setenv("DETERMINISTIC_CONTRACT_MODE", "0")
    import agents.sample_agent.config as cfg

    importlib.reload(cfg)
    assert cfg.EDIT_STRATEGY == "rule_first"
    assert cfg.ENABLE_SEMANTIC_EDIT_GENERATION is True
    assert cfg.ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK is True
    assert cfg.ENABLE_RAG_CROSS_ENCODER_RERANK is True
    assert cfg.ENABLE_AGENT1_RAG_CONTEXT is True


def test_deterministic_mode_overrides_preset(monkeypatch):
    monkeypatch.setenv("ANALYZER_PRESET", "structured")
    monkeypatch.setenv("DETERMINISTIC_CONTRACT_MODE", "1")
    import agents.sample_agent.config as cfg

    importlib.reload(cfg)
    assert cfg.ENABLE_SEMANTIC_EDIT_GENERATION is False
    assert cfg.ENABLE_AGENT4_VERIFICATION is False
