# Output Verification Report: HW NPI-NG Key Terms

**Input:** `data/HW NPI-NG Key Terms  Conditions_9_21.pdf` (Honeywell R&D Key Terms, 11 pages)  
**Outputs:** clause_analysis (4).csv, counterfactuals (4).csv, verification_report (1).csv, reviewed_contract (26).docx

---

## 1. Clause Analysis CSV ✓

**Status:** Correct structure, 10 POC clauses covered.

| Clause | Detected | Issue |
|--------|----------|-------|
| Limitation of Liability | Yes | Evidence "loss of business which is incapable" is from **Section 10 (Compliance)**, not a liability cap clause. Honeywell R&D terms may not have explicit LOD cap. |
| Governing Law | Yes | Correct – "laws of the State of New York" in Section 9 |
| Dispute Resolution | Yes | Correct – "Additional Arbitration Rules", "English" in Section 9 |
| Firm Price | Unclear | Correct – no explicit firm-price clause in R&D terms |
| Force Majeure | Yes | Evidence "180 days prior" is from **Section 7 (Design/Process changes)**, not FM. Weak match. |
| Liquidated Damages | Yes | Evidence "15 days of receipt" is from **Section 9.C (Executive Escalation)**, not LD. **Wrong clause.** |
| Orders Extending | Yes | Correct – "Any partial termination" in Section 5 |
| Quantity Protection | Yes | Correct – "schedule and/or quantity changes" in Section 6 |
| Inventory Requirements | Yes | Correct – "additional inventory, overlapping production" in Section 7 |
| Change Orders | Yes | Correct – "equitable adjustment" in Section 6 |

**Finding:** Agent 1 is attributing evidence from wrong sections to Limitation of Liability, Force Majeure, and Liquidated Damages (cross-clause pollution).

---

## 2. Counterfactuals CSV ✓

**Status:** Correct structure. What-if narratives align with clause table. Some counterfactuals reference wrong evidence (e.g. FM row says "aerospace terms" instead of FM-specific language).

---

## 3. Agent 4 Verification Report ✓

**Status:** Agent 4 correctly flagged 5 problematic edits:

| Clause | Agent 4 Finding |
|--------|-----------------|
| Governing Law | "Edited paragraph appears to be a duplicate of the original" |
| Liquidated Damages | "Edited paragraph is identical to the original... appears in a different section" |
| Orders Extending | "Edited text disrupts the flow, introducing GB's Ideal Position out of place" |
| Quantity Protection | "Disrupts the flow and context of the surrounding text" |
| Change Orders | "Mix of two different clauses... does not read naturally" |

**Finding:** Agent 4 is working correctly and catching semantic/contextual misfits.

---

## 4. Reviewed Contract DOCX – Issues

### 4.1 Wrong Paragraphs Redlined

| Problem | Detail |
|---------|--------|
| Para 2 "Phase 1 Definitions" | Redlined – should not be. Likely wrong overlap match. |
| Para 143 | LD text ("If the Supplier fails to deliver...") wrongly merged with "be held within 15 days" (Executive Escalation). |
| Para 88 | "GB's Ideal Position" inserted into "Unless agreed upon otherwise in writing" (Change Orders clause). Disrupts flow. |

### 4.2 Evidence–Paragraph Mismatch

- **Limitation of Liability:** Evidence from Section 10 (Compliance) was used to redline; the contract has no traditional liability cap clause in that section.
- **Liquidated Damages:** Evidence "15 days of receipt" is from Section 9.C (Executive Escalation), not an LD clause. The Honeywell R&D terms may not have an LD clause.

### 4.3 Formatting

- **Headers/Footers:** pdf2docx preserved 11 sections with headers/footers ✓
- **Paragraph structure:** Section titles merged with body (e.g. "9. APPLICABLE LAW AND FORUM A. Governing Law") – pdf2docx layout effect
- **Redline application:** `_clear_paragraph_runs` + `_write_redline` replaces all paragraph content. **Original bold/italic/formatting within paragraphs is lost** when redlining.

---

## 5. Root Causes

1. **Evidence attribution:** Agent 1 extracts sentences that contain keywords but from wrong sections (e.g. "liability" in indemnification, "15 days" in dispute resolution).
2. **Paragraph matching:** `_find_best_matching_paragraph_index` uses token overlap (threshold 0.25). Short evidence can match wrong paragraphs; `uploaded_position` can override with longer wrong-clause text.
3. **Wholesale replacements:** When no rule-based edit applies, full `gb_ideal_position` is used. Validator allows it, but the result is redundant or contextually wrong.
4. **Formatting loss:** Clearing and rewriting paragraph runs removes original character formatting (bold, italic).

---

## 6. Fixes Implemented (2025-03-11)

| Fix | Status | File |
|-----|--------|------|
| **Tighten paragraph matching** | Done | `redline_docx.py` |
| - Overlap threshold raised 0.25 → 0.4 | ✓ | `_find_best_matching_paragraph_index` |
| - Require significant phrase (first 5 words or 25 chars of evidence) in paragraph | ✓ | `_evidence_matches_paragraph` |
| **Generic evidence exclusion** | Done | `redline_docx.py` |
| - LD: exclude evidence "15 days of receipt" (dispute/escalation clause) | ✓ | `_is_generic_evidence_for_clause` |
| - Limitation: exclude "loss of business which is incapable" (compliance section) | ✓ | |
| - Force majeure: exclude "180 days prior" when FM not in evidence (design change clause) | ✓ | |
| **Skip redline when Agent 4 flags** | Done | `redline_docx.py`, `config.py` |
| - Config `SKIP_REDLINE_WHEN_AGENT4_FLAGS=1` (default): do not apply edit when Agent 4 flags | ✓ | |

## 7. Remaining Recommendations

| Priority | Fix | Impact |
|----------|-----|--------|
| 1 | **Section-aware matching:** Use `[PAGE N]` or section markers to constrain matches | Further reduces cross-section pollution |
| 2 | **Preserve formatting on redline:** Preserve original bold/italic within paragraph runs | Improves output fidelity |
| 3 | **Agent 1 exclusions:** Clause-specific exclusion terms at extraction (not redline) | Reduces wrong evidence at source |
