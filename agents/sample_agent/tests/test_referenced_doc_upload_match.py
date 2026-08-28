"""Tests for referenced_doc_matches_upload appendix/annex filename anchoring."""

from __future__ import annotations

from agents.sample_agent.agent1_clause_analyzer import referenced_doc_matches_upload


def test_annex_1_does_not_match_v1_or_year_digits_only():
    assert not referenced_doc_matches_upload("Annex 1", "contract_v1_draft_2026.pdf")


def test_annex_3_matches_appendix_style_filename():
    assert referenced_doc_matches_upload("Annex 3", "Appendix_3_Terms.docx")


def test_annex_6_does_not_match_2026_only():
    assert not referenced_doc_matches_upload("Annex 6", "annual_report_2026.pdf")
