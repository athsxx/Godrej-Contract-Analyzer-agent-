"""Tests for contract_search helpers (find phrase, verification)."""

from agents.sample_agent.contract_search import (
    collapse_whitespace,
    collect_keyword_spans,
    extract_windows,
    find_phrase,
    normalize_for_substring_match,
    phrase_in_text,
    verify_evidence_quote,
)


def test_collapse_whitespace():
    assert collapse_whitespace("  a \n\t b  ") == "a b"


def test_phrase_in_text_case_and_whitespace():
    hay = "The Supplier shall pay Liquidated   Damages at 0.5% per week."
    assert phrase_in_text(hay, "liquidated damages at 0.5%")
    assert not phrase_in_text(hay, "nonexistent clause")


def test_find_phrase_flexible_spacing():
    text = "Foo   bar\nbaz  End"
    spans = find_phrase(text, "foo bar baz")
    assert spans
    start, end = spans[0]
    matched = text[start:end]
    assert "Foo" in matched and "bar" in matched and "baz" in matched


def test_collect_keyword_spans_merge():
    blob = "alpha beta gamma. Alpha beta delta. " + "word " * 25
    spans = collect_keyword_spans(blob, ["alpha beta", "gamma"])
    wins = extract_windows(blob, spans, radius=80, max_windows=2)
    assert wins
    assert "alpha" in wins[0].lower()


def test_verify_evidence_quote_primary():
    primary = "Payment net thirty (30) days from invoice date."
    ok, src = verify_evidence_quote("net thirty (30) days", primary_text=primary, supporting_texts=None)
    assert ok and src == "primary"


def test_verify_evidence_quote_supporting():
    primary = "See Schedule A for LD rates."
    supp = {"sched_a.pdf": "Liquidated damages shall be 0.5% per week of delayed value."}
    ok, src = verify_evidence_quote("0.5% per week of delayed value", primary_text=primary, supporting_texts=supp)
    assert ok and src == "sched_a.pdf"


def test_normalize_for_substring_match_strips_nbsp():
    s = normalize_for_substring_match("Foo\u00a0Bar")
    assert s == "foo bar"
