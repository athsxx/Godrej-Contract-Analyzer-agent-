# DOCX Redline & Highlighting vs Agent 1/2/3 – Cross-Check Findings

**Inputs referenced:**  
- Test contract: `test_supply_agreement_contract.docx`  
- Clause analysis CSV: `clause_analysis (1).csv`  
- Output DOCX: `reviewed_contract (7).docx`  
- Terminal log (DOCX export validator warnings)

---

## 1. Data flow: one source for CSV and DOCX

- **CSV** and **DOCX** both use the **same in-session `clause_table`** produced after the user runs analysis (e.g. “analyze this contract”).
- **Clause table** comes from:
  - **Agent 1** (`agent1_clause_analyzer.run_aerospace_clause_extraction`) when upload + POC knowledge are available, **or**
  - Fallback `_build_clause_rows()` in `chat_agent` (e.g. when Agent1 fails or document is out-of-scope).
- **Agent 2** and **Agent 3** use the same clause table:
  - Agent 2: `generate_risk_mitigation(agent1_output, po_text, terms_text)` with Agent1-style markdown built from `clause_table`.
  - Agent 3: `generate_mitigation_checklist(agent2_output)` for the Risk Mitigation Checklist.
- **DOCX export** uses:
  - The **latest assistant message’s `clause_table`** (same as CSV).
  - `_build_edit_instructions_from_clause_table(clause_table)` to build `edit_instructions`.
  - `build_reviewed_contract_docx(..., clause_table=..., edit_instructions=...)` in `agents/sample_agent/redline_docx.py`.

So: **CSV, counterfactuals, mitigation strategies, and DOCX redlining all align to the same Agent 1 (or fallback) output.** The link is the single `clause_table` stored on the last assistant turn.

---

## 2. DOCX output: what actually gets redlined and highlighted

- **Redlining** = strike-through for “deleted” text, underline for “inserted” text (computed by `_write_redline` from `original_text` vs `edited_text`).
- **Highlighting** = no separate highlight in code; emphasis is via strike/underline only.
- **Margin comments** = policy deviation + counterfactual comments when `doc.add_comment` is available (often not in standard python-docx).

Only clauses that **pass all of these** get a redline:

1. **Risk ≠ Green** (Green rows are skipped).
2. **Detected = Yes** (otherwise: “skipped redline because clause was not confidently detected”).
3. **Evidence** present and not “No direct matching…” (otherwise: “no valid evidence snippet for redline”).
4. **Paragraph match**: a body paragraph in the source DOCX is found that matches the evidence (`_find_best_matching_paragraph_index` with token overlap ≥ 0.25).
5. **Original-text check**: matched paragraph text must match the `original_text` hint (`_matches_original_hint`).
6. **Edit validator** (`_is_valid_edit`):  
   - Original and edited must differ.  
   - Original must look like a clause body (length ≥ 45, sentence-like).  
   - Edited must have ≥ 8 tokens.  
   - Length ratio `edited_tokens / original_tokens` must be between **0.55 and 1.9**.  
   - **Token overlap** between original and edited must be **≥ 0.3** (blocks full replacement with unrelated policy text).

If any of these fail, the clause is **not** redlined and a warning is appended (e.g. “validator rejected proposed edit (overlap/length/sentence guardrail).”).

---

## 3. Why 8 clauses got “validator rejected proposed edit”

From your terminal:

- **Applicable / Governing Law**, **Firm Price**, **Force Majeure**, **Liquidated Damages**, **Orders Extending Beyond Termination**, **Quantity Protection**, **Inventory Requirements**, **Change Orders Procedure** → all hit:  
  `validator rejected proposed edit (overlap/length/sentence guardrail)`.

**Cause:**

- Edit instructions are built with **`suggested_text = gb_ideal_position`** (from `_build_edit_instructions_from_clause_table`).
- In `_normalize_for_edit`, **if `suggested_text` is non-empty it is returned as `edited_text`** before any clause-specific regex edits.
- Your CSV “GB Ideal Position” values are **short policy summaries**, e.g.:
  - “Use approved governing law and jurisdiction combinations (e.g., India/Mumbai, approved alternatives).”
  - “Firm/fixed pricing with limited escalation triggers (change order, change in law, raw material changes).”
- The **source DOCX paragraphs** are long clause sentences (e.g. “The courts located in San Francisco, California shall have exclusive jurisdiction…”).
- So **edited_text** = short policy line, **original_text** = long paragraph →:
  - **Length ratio** often &lt; 0.55 (edited too short) → validator fails.
  - **Token overlap** often &lt; 0.3 (different wording) → validator fails.

So the DOCX output is **correctly** refusing to replace a full clause sentence with a one-line policy summary; the validator is doing what it’s designed to do. The downside is that most clauses then get **no** redline in the DOCX.

**Clause that can still pass:** **Limitation of Liability** – `_normalize_for_edit` has **hardcoded regex** that only changes “200%” → “100%” and “not excluded” → “excluded” in the same paragraph, so edited text stays similar in length and overlap → validator can pass and redline appears.

---

## 4. Alignment with CSV and mitigation strategies

| Item | Match? | Notes |
|------|--------|--------|
| **Clause list** | Yes | DOCX logic iterates the same 10 POC clauses as the CSV (from same `clause_table`). |
| **Risk levels** | Yes | Red/Amber skipped for Green; only non-Green are considered for redline. |
| **Evidence / Uploaded Position** | Yes | Evidence is used to find the paragraph and as `original_text` hint; source is `evidence_snippet` (same as CSV “Evidence”). |
| **GB Ideal / Mitigation** | Partially | They drive **proposed** edit via `suggested_text` / `gb_ideal_position`, but when that proposal is a short policy line, the **validator rejects** it, so no redline is applied. So DOCX does not “contradict” the CSV; it just doesn’t show a redline for those clauses. |
| **Counterfactuals** | Yes | Counterfactual text is passed into margin comments (when comments are supported); source is `counterfactual` from the same row. |
| **Redlining style** | N/A | Only clauses that pass the validator get strike/underline; others get no change in the DOCX. |

So: **the output document’s redlining and highlighting (strike/underline) are consistent with the same Agent 1/2/3 pipeline and the CSV**, but **most clauses have no redline** because the proposed edit (GB ideal policy line) fails the overlap/length/sentence guardrail.

---

## 5. Vector retrieval (RAG) and this behaviour

- You had **ENABLE_RAG=1** and **INDEX_UPLOAD_ON_UPLOAD=1**.
- RAG is used in **answer_question** for the conversational reply and context; the **clause table** itself is filled by **Agent1** (or fallback) from **uploaded full text + POC knowledge**, not from the vector index used for Q&A.
- So enabling vector retrieval **does not change** how the clause table or DOCX edit instructions are built. The 8 validator rejections would be the same with or without RAG for this flow.

---

## 6. Summary

- **Single source of truth:** CSV, counterfactuals, mitigation strategies, and DOCX all come from the same `clause_table` (Agent 1 or fallback).
- **DOCX redlining** only appears for clauses that pass paragraph matching and **`_is_valid_edit`** (overlap ≥ 0.3, length ratio 0.55–1.9, etc.).
- **Why you see few (or one) redlines:** Proposed edits are often the short “GB Ideal Position” sentence; the validator correctly rejects replacing a long clause with that short line, so no redline is applied.
- **Result:** The output DOCX is **aligned** with Agent 1/2/3 and the CSV; it does not show redlines for most clauses because of the current edit proposal (suggested_text = GB ideal) and the strict validator, not because of a different data source or broken link.

---

## 7. Recommendations (optional)

- **Prefer rule-based edits when possible:** In `_normalize_for_edit`, consider applying the **clause-specific regex edits first** and only using `suggested_text` / `gb_ideal_position` when no regex applied (so more clauses get minimal, validator-friendly edits).
- **Pass `risk_rationale` into DOCX:** `_build_edit_instructions_from_clause_table` does not currently pass `risk_rationale`; margin comments then use the generic “Deviation requires legal review.” Adding `risk_rationale` to the instruction row (and using it in `build_reviewed_contract_docx` for `policy_comment`) would make margin comments match the CSV “Risk Rationale” column.
- **Relax or separate policy replacements:** If you want to show “replace with GB ideal” even when it’s short, you could either relax the validator for that case (e.g. allow length ratio &lt; 0.55 when the edit is explicitly from policy) or render policy suggestions as comments only, and keep redlining for small, in-paragraph edits only.

If you want, next step can be concrete code changes for the rule-based priority and/or passing `risk_rationale` into the DOCX builder.
