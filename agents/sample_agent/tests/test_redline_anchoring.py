"""Unit tests for DOCX paragraph anchoring (redline export)."""

from __future__ import annotations

import pytest

from agents.sample_agent.redline_docx import (
    _clause_name_keywords,
    _find_best_matching_paragraph_index,
    _is_generic_evidence_for_clause,
    _matches_original_hint,
)


class _P:
    __slots__ = ("text",)

    def __init__(self, t: str) -> None:
        self.text = t


def _doc_like_paras(*lines: str) -> list[_P]:
    return [_P(s) for s in lines]


def test_generic_filter_bypass_finds_lol_paragraph() -> None:
    """Evidence that hits _is_generic_evidence_for_clause must not abort matching when bypass pass runs."""
    ev = (
        "loss of business which is incapable of accurate estimation; any indirect or consequential loss; "
        "The total aggregate liability of the Supplier shall in no event exceed 100% of the price."
    )
    assert _is_generic_evidence_for_clause(ev, "Limitation of Liability and Exclusion of Consequential Damages")
    paras = _doc_like_paras(
        "6.8 Liability - Insurance",
        "The total aggregate liability of the Supplier under this Agreement shall in no event exceed one hundred percent (100%) of the price paid. "
        "The Parties exclude any indirect, consequential, or loss of business damages except where mandatory law provides otherwise.",
    )
    idx = _find_best_matching_paragraph_index(
        None,
        ev,
        set(),
        uploaded_position="",
        clause_name="Limitation of Liability and Exclusion of Consequential Damages",
        flat_paragraphs=paras,
    )
    assert idx == 1


def test_clause_title_keyword_anchor() -> None:
    """When overlap is low but clause title matches the right section, still anchor."""
    ev = "Price shall be firm and not subject to revision except as set forth in writing."
    paras = _doc_like_paras(
        "3.2 Prices and price conditions",
        "Unless otherwise agreed in the Order, prices are firm, fixed, and not subject to revision, except where a written amendment is executed by both Parties.",
    )
    idx = _find_best_matching_paragraph_index(
        None,
        ev,
        set(),
        uploaded_position="",
        clause_name="Firm Price",
        flat_paragraphs=paras,
    )
    assert idx == 1


def test_matches_original_hint_accepts_loose_align() -> None:
    long_para = (
        "Unless otherwise agreed in the Order, prices are firm, fixed, and not subject to revision, except where a written amendment is executed by both Parties."
    )
    hint = "prices are firm, fixed, and not subject to revision, except"
    assert _matches_original_hint(long_para, hint) is True


def test_clause_name_keywords_extracts_terms() -> None:
    k = _clause_name_keywords("Limitation of Liability and Exclusion of Consequential Damages")
    assert "limitation" in k
    assert "liability" in k
    assert "exclusion" in k
    assert "consequential" in k
    assert "damages" in k
