"""Regression tests for Amethyst plan rollout (primary-contract redlines, appendix matching)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.sample_agent.agent1_clause_analyzer import referenced_doc_matches_upload
from agents.sample_agent.chat_agent import UPLOAD_ROOT, UploadedArtifact, _validate_redline_template_source


def test_referenced_appendix_fuzzy_matches_filename():
    assert referenced_doc_matches_upload("Appendix 3", "Appendix_3_Pricing_Schedule.docx")
    assert referenced_doc_matches_upload("Schedule A", "schedule_a_rates.xlsx")
    assert not referenced_doc_matches_upload("Appendix 99", "unrelated_notes.txt")


def test_redline_template_must_be_primary_docx():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        primary = td_path / "master_agreement.docx"
        other = td_path / "supporting_schedule.docx"
        primary.write_bytes(b"PK")
        other.write_bytes(b"PK")
        art = UploadedArtifact(name=primary.name, path=primary, size=2)
        session_id = "s_test"
        _validate_redline_template_source(art, primary, session_id)
        with pytest.raises(ValueError, match="primary contract"):
            _validate_redline_template_source(art, other, session_id)


def test_redline_template_pdf_conversion_path():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        pdf = td_path / "deal.pdf"
        pdf.write_bytes(b"%PDF")
        art = UploadedArtifact(name=pdf.name, path=pdf, size=4)
        session_id = "s_pdf_test_rollout"
        session_dir = UPLOAD_ROOT / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        converted = session_dir / "deal_converted.docx"
        converted.write_bytes(b"PK")
        try:
            _validate_redline_template_source(art, converted, session_id)
        finally:
            converted.unlink(missing_ok=True)
            session_dir.rmdir()
