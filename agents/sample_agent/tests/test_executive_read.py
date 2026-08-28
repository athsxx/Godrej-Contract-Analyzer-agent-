"""Paragraph index + executive read bundle (deterministic path)."""

from agents.sample_agent.executive_read import generate_executive_read_bundle
from agents.sample_agent.paragraph_index import build_paragraph_index, primary_text_fingerprint


def test_build_paragraph_index_sequential_ids():
    text = "First block.\n\nSecond block here.\n\nThird."
    paras = build_paragraph_index(text, max_paragraphs=10)
    assert [p["paragraph_id"] for p in paras] == ["p-0", "p-1", "p-2"]
    assert "First block." in paras[0]["text"]


def test_primary_text_fingerprint_stable():
    t = "hello\nworld" * 50
    assert primary_text_fingerprint(t) == primary_text_fingerprint(t)


def test_executive_read_deterministic_without_llm(monkeypatch):
    from agents.sample_agent import config as ac

    monkeypatch.setattr(ac, "ENABLE_EXECUTIVE_READ_LLM", False)
    clause_table = [
        {
            "clause_name": "Payment",
            "detected": "Yes",
            "risk_level": "Amber",
            "uploaded_position": "Net 90",
            "gb_ideal_position": "Net 30",
            "evidence_snippet": "Payment shall be due within ninety (90) days.",
            "mitigation_recommendation": "Shorten terms.",
            "approval_path": "Finance + Legal",
        }
    ]
    primary = "Payment shall be due within ninety (90) days after invoice.\n\nOther section."
    out = generate_executive_read_bundle(
        clause_table=clause_table,
        primary_text=primary,
        supporting_summary="",
        knowledge_excerpt="",
    )
    er = out["executive_read"]
    assert er["source"] == "deterministic_fallback"
    assert len(er["executive_items"]) == 1
    assert er["executive_items"][0]["cited_paragraph_ids"]
    assert out["paragraph_index"]
