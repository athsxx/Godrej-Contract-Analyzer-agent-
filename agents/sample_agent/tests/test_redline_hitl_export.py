"""Tests for human-in-the-loop filtering of DOCX edit instructions."""

from __future__ import annotations

from agents.sample_agent.chat_agent import _filter_edit_instructions_for_hitl


def _rows() -> list[dict[str, str]]:
    return [
        {"clause_id": "1", "clause_name": "A"},
        {"clause_id": "2", "clause_name": "B"},
        {"clause_id": "3", "clause_name": "C"},
    ]


def test_require_hitl_filters_to_accepted_only() -> None:
    out = _filter_edit_instructions_for_hitl(
        _rows(),
        accepted_clause_ids=["2", "3"],
        require_hitl=True,
    )
    assert [r["clause_id"] for r in out] == ["2", "3"]


def test_require_hitl_empty_accepted_yields_empty() -> None:
    out = _filter_edit_instructions_for_hitl(
        _rows(),
        accepted_clause_ids=[],
        require_hitl=True,
    )
    assert out == []


def test_require_hitl_none_accepted_treated_as_empty() -> None:
    out = _filter_edit_instructions_for_hitl(
        _rows(),
        accepted_clause_ids=None,
        require_hitl=True,
    )
    assert out == []


def test_legacy_mode_full_export_when_accepted_none() -> None:
    out = _filter_edit_instructions_for_hitl(
        _rows(),
        accepted_clause_ids=None,
        require_hitl=False,
    )
    assert len(out) == 3


def test_legacy_mode_optional_subset_when_ids_passed() -> None:
    out = _filter_edit_instructions_for_hitl(
        _rows(),
        accepted_clause_ids=["1"],
        require_hitl=False,
    )
    assert [r["clause_id"] for r in out] == ["1"]
