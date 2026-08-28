"""Agent 1 aerospace: quoted evidence must anchor to the primary contract only."""

from __future__ import annotations

from agents.sample_agent.agent1_clause_analyzer import run_aerospace_clause_extraction


def test_aerospace_evidence_snippet_from_primary_not_supporting_schedule():
    """Supporting uploads must not outrank primary sentences for evidence_snippet (DOCX anchoring)."""
    knowledge = {
        "clauses": [
            {
                "name": "Firm Price",
                "keywords": ["firm", "price", "revisable", "unit"],
                "ideal_position": "GB prefers bounded escalation triggers.",
                "approval_path": "Legal",
            }
        ]
    }
    primary = (
        "3.2 Pricing. The unit prices are firm and not revisable except where a written amendment is executed."
    )
    supporting = {
        "Appendix_Pricing_Spam.docx": (
            ("unit price " * 30)
            + ("firm firm firm price escalation " * 25)
            + "revisable revisable raw material change order law law law"
        ),
    }
    rows = run_aerospace_clause_extraction(
        primary,
        knowledge,
        supporting_doc_texts=supporting,
        rag_session_id=None,
    )
    assert len(rows) == 1
    row = rows[0]
    ev = (row.get("evidence_snippet") or "").lower()
    up = (row.get("uploaded_position") or "").lower()
    assert "3.2" in ev or "3.2" in up
    assert "appendix_pricing" not in ev and "[supporting doc:" not in ev
