"""Tests for legal commentary anchor + assembly."""

from __future__ import annotations

from agents.sample_agent.legal_commentary import (
    assemble_legal_comment_body,
    best_sentence_index_1based,
    build_comment_anchor_counsel_bubble,
    build_comment_anchor_section,
    build_comment_analysis_record_counsel_bubble,
    build_comment_facts_for_llm,
    build_comment_facts_section,
    build_comment_facts_section_compact,
    build_supporting_hard_cite_block,
    format_evidence_provenance_block,
    primary_contract_context_for_commentary,
    split_paragraph_sentences,
)


def test_provenance_block_primary_and_supporting() -> None:
    row = {"evidence_source": "primary", "evidence_location_hint": "section 3.2", "anchoring_warning": ""}
    b = format_evidence_provenance_block(row, primary_upload_display_name="Agreement_Main.docx")
    assert "EVIDENCE PROVENANCE" in b
    assert "Agreement_Main.docx" in b
    assert "section 3.2" in b
    row2 = {"evidence_source": "Appendix_3_Market.docx", "evidence_location_hint": "", "anchoring_warning": ""}
    b2 = format_evidence_provenance_block(row2, primary_upload_display_name="Agreement_Main.docx")
    assert "Appendix_3_Market.docx" in b2
    assert "Anchor vs evidence file" in b2
    b3 = format_evidence_provenance_block(
        row,
        primary_upload_display_name="Agreement_Main.docx",
        evidence_exact_text="Unless otherwise stated, prices are firm.",
        primary_flat_paragraph_1based=301,
        primary_flat_total_paragraphs=813,
    )
    assert "paragraph 301 of 813" in b3
    assert "Unless otherwise stated" in b3


def test_anchor_section_explicit_paragraph() -> None:
    para = (
        "First sentence is short here. "
        "The total aggregate liability shall not exceed one hundred percent. "
        "Final words are kept long enough not to merge into prior sentence text."
    )
    s = build_comment_anchor_section(
        clause_name="Limitation of Liability",
        anchor_index=46,
        total_paragraphs=900,
        anchored_paragraph_text=para,
        evidence_for_sentence_match="aggregate liability shall not exceed one hundred percent",
    )
    assert "paragraph 47 of 900" in s
    assert "COMMENT ANCHOR" in s
    assert "Quoted text at this anchor" in s
    assert "Limitation of Liability" in s
    assert "Sentence focus" in s
    assert "sentence 2 of 3" in s
    assert "SENTENCES IN THIS PARAGRAPH" in s
    assert ">>> S2:" in s


def test_best_sentence_prefers_substring() -> None:
    sents = split_paragraph_sentences("Alpha beta. Gamma delta epsilon. Zeta.")
    assert best_sentence_index_1based(sents, "gamma delta") == 2


def test_compact_facts_preserves_key_fields() -> None:
    row = {
        "risk_level": "Amber",
        "detected": "Yes",
        "evidence_snippet": "evidence text",
        "evidence_quote": "align key phrase here",
        "evidence_source": "primary",
        "evidence_location_hint": "page 1",
        "uploaded_position": "preamble noise. " + "align key phrase here" + " tail noise.",
        "gb_ideal_position": "ideal wording",
        "risk_rationale": "because reasons",
        "mitigation_recommendation": "mitigate",
        "approval_path": "GC sign-off",
        "counterfactual": "if X then Y",
    }
    f = build_comment_facts_section_compact(
        row,
        "schedule note",
        evidence_aligned="aligned bit",
        primary_upload_display_name="Contract.docx",
        evidence_exact_for_provenance="aligned bit",
        primary_flat_paragraph_1based=12,
        primary_flat_total_paragraphs=100,
    )
    assert "ANALYSIS RECORD" in f
    assert "Amber" in f and "Yes" in f
    assert "aligned bit" in f
    assert "Primary contract context" in f
    assert "not supplier upload" in f
    assert "align key phrase here" in f
    assert "ideal wording" in f
    assert "because reasons" in f
    assert "mitigate" in f and "GC sign-off" in f
    assert "if X then Y" in f
    assert "schedule note" in f
    assert "Verified evidence source" in f
    assert "Contract.docx" in f
    assert "12 of 100" in f
    assert "aligned bit" in f or "Evidence (clip)" in f


def test_counsel_short_export_style() -> None:
    row = {
        "risk_level": "Red",
        "detected": "Yes",
        "evidence_snippet": "x",
        "evidence_source": "primary",
        "uploaded_position": "y",
        "gb_ideal_position": "z",
        "risk_rationale": "r",
        "mitigation_recommendation": "m",
        "approval_path": "Legal",
        "counterfactual": "cf long " * 20,
    }
    f = build_comment_facts_section_compact(
        row,
        "supp",
        evidence_aligned="ev aligned",
        export_style="counsel_short",
        primary_upload_display_name="Main.docx",
    )
    assert "ANALYSIS SUMMARY" in f
    assert "Counterfactual" not in f
    assert "GB ideal" not in f
    assert "Verified evidence source" in f
    assert "Main.docx" in f


def test_facts_for_llm_excludes_raw_uploaded_head() -> None:
    row = {
        "risk_level": "Amber",
        "detected": "Yes",
        "evidence_source": "primary",
        "evidence_quote": "needle middle",
        "uploaded_position": "AAAA " * 40 + "needle middle" + " BBBB" * 40,
        "gb_ideal_position": "gb",
        "risk_rationale": "rat",
        "mitigation_recommendation": "mit",
        "approval_path": "ap",
    }
    llm = build_comment_facts_for_llm(row, "supporting line", evidence_aligned="needle middle", primary_upload_display_name="P.docx")
    assert "needle middle" in llm
    assert "Primary contract context" in llm
    assert len(llm) < 2200
    assert "P.docx" in llm
    assert "EVIDENCE PROVENANCE" in llm


def test_primary_context_centres_on_quote() -> None:
    row = {"evidence_quote": "beta gamma", "uploaded_position": "alpha " + "beta gamma" + " delta"}
    ctx = primary_contract_context_for_commentary(row, evidence_aligned="beta gamma", max_chars=80)
    assert "beta gamma" in ctx


def test_facts_section_has_status_headers() -> None:
    row = {
        "risk_level": "Amber",
        "detected": "Yes",
        "evidence_snippet": "evidence text",
        "evidence_source": "primary",
        "uploaded_position": "up",
        "gb_ideal_position": "gb",
        "risk_rationale": "because",
        "mitigation_recommendation": "mitigate",
        "approval_path": "GC",
        "counterfactual": "cf",
    }
    f = build_comment_facts_section(
        row, "supporting blurb", evidence_aligned="aligned snippet", primary_upload_display_name="K.docx"
    )
    assert "CLAUSE STATUS" in f
    assert "aligned snippet" in f
    assert "GB IDEAL POSITION" in f
    assert "PRIMARY CONTRACT CONTEXT" in f
    assert "EVIDENCE PROVENANCE" in f
    assert "K.docx" in f


def test_assemble_respects_max_chars() -> None:
    anchor = "A" * 200
    facts = "B" * 8000
    out = assemble_legal_comment_body(anchor_section=anchor, facts_section=facts, llm_brief=None, max_chars=1200)
    assert len(out) <= 1200
    assert out.startswith("A" * 200)


def test_counsel_bubble_anchor_deduped() -> None:
    row = {
        "evidence_source": "primary",
        "evidence_location_hint": "",
        "counterfactual": "gap text",
    }
    s = build_comment_anchor_counsel_bubble(
        clause_name="Firm Price",
        anchor_index=300,
        total_paragraphs=812,
        anchored_paragraph_text="Unless otherwise stated, the Supplier undertakes to maintain firm prices.",
        evidence_for_sentence_match="Unless otherwise stated",
        row=row,
        primary_upload_display_name="MainAgreement.docx",
    )
    assert "COMMENT ANCHOR (main agreement)" in s
    assert "Evidence verified in upload: MainAgreement.docx (main agreement)." in s
    assert "SENTENCES IN THIS PARAGRAPH" not in s
    assert "EVIDENCE PROVENANCE" not in s
    assert "paragraph 301 of 812" in s


def test_counsel_bubble_supporting_cite_block() -> None:
    row = {
        "evidence_source": "Appendix_3.docx",
        "evidence_location_hint": "Clause 3.2(b)",
        "counterfactual": "Creates exposure on volume.",
        "risk_rationale": "",
    }
    b = build_supporting_hard_cite_block(row, "Committed Market Share shall apply")
    assert "SUPPORTING CITE" in b
    assert "Appendix_3.docx" in b
    assert "Committed Market Share" in b


def test_counsel_bubble_analysis_record_no_duplicate_evidence() -> None:
    row = {
        "risk_level": "Amber",
        "detected": "Yes",
        "evidence_source": "primary",
        "gb_ideal_position": "GB baseline long " * 20,
        "mitigation_recommendation": "Mitigate per playbook.",
        "approval_path": "ERMC",
        "counterfactual": "Gap: pricing firm but escalation open-ended.",
    }
    ar = build_comment_analysis_record_counsel_bubble(
        row,
        uploaded_filenames=["Main.docx", "Other.docx"],
        primary_upload_display_name="Main.docx",
    )
    assert "ANALYSIS RECORD" in ar
    assert "Contract evidence (aligned)" not in ar
    assert "Mitigation:" in ar and "ERMC" in ar
    assert "Negotiation gap:" in ar
    assert "Other.docx" in ar


def test_assemble_counsel_bubble_layout_no_source_fields_header() -> None:
    anchor = "ANCHOR"
    facts = "FACTS_BODY"
    out = assemble_legal_comment_body(
        anchor_section=anchor,
        facts_section=facts,
        llm_brief=None,
        max_chars=5000,
        comment_layout="counsel_bubble",
    )
    assert "SOURCE FIELDS" not in out
    assert out == "ANCHOR\n\nFACTS_BODY"
