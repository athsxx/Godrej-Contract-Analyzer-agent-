# Progress Log

## 2026-03-05 - Iteration 1
- Started enhancement for clause matching quality:
  - Implement top-N evidence per clause.
  - Add confidence score per clause.
  - Expose confidence in UI table.
- Constraint: keep existing JSON knowledge schema as-is.

## 2026-03-05 - Iteration 2
- Updated `agent1_clause_analyzer.py` Aerospace extraction contract:
  - Added top-N evidence selector (`_aero_top_evidence`) with duplicate filtering.
  - Added confidence scoring (`_aero_confidence`) with labels High/Medium/Low.
  - Rows now include:
    - `confidence_score` (0-100)
    - `confidence_label`
    - concatenated evidence snippets from top matches.

## 2026-03-05 - Iteration 3
- Updated UI table (`workspace_aerospace_contract_analyzer.html`):
  - Added a `Confidence` column.
  - Displays per-row confidence label and percentage from Agent 1 extraction.

## 2026-03-05 - Iteration 4
- Validation:
  - Lint check passed for modified files.
  - Local smoke test passed (`upload` + `ask` flow returns HTTP 200).
  - Verified table renders 10 rows with new confidence column.
  - Verified evidence field now carries multiple snippets (top-N, joined) for matched clauses.

## 2026-03-05 - Iteration 5
- Added DOCX redline generator module:
  - New file `agents/sample_agent/redline_docx.py`.
  - Generates `reviewed_contract.docx` with:
    - original clause text,
    - visual redline edits (strikethrough deletions, underline insertions),
    - legal comments and counterfactual comments.
  - Uses current clause-table fields as source of truth.

## 2026-03-05 - Iteration 6
- Added chat-agent export hook:
  - New function `generate_reviewed_contract_docx(session_id)` in `agents/sample_agent/chat_agent.py`.
  - Pulls latest assistant `clause_table` from session history.
  - Builds `reviewed_contract.docx` into session upload directory.

## 2026-03-05 - Iteration 7
- Added backend route handling in `guru/views.py`:
  - New POST action: `export_reviewed_docx`.
  - Calls `sample_agent.generate_reviewed_contract_docx(session_key)`.
  - Returns export metadata to template context and preserves chat history.

## 2026-03-05 - Iteration 8
- Updated workspace UI for export:
  - Added `Generate Reviewed DOCX` button in input bar.
  - Added success message block showing output filename and path.

## 2026-03-05 - Iteration 9
- Added dependency and test input:
  - Added `python-docx` to `requirements.txt`.
  - Added concrete test contract text file:
    - `docs/test_data/sample_supply_contract_for_redline_test.txt`
  - Test file intentionally includes multiple policy deviations for visible redline output.

## 2026-03-05 - Iteration 10
- End-to-end validation completed:
  - Installed `python-docx` in local venv.
  - Smoke-tested upload -> ask -> export flow (all HTTP 200).
  - Verified generated file exists:
    - `media/custom_dev_sample_agent/<session>/reviewed_contract.docx`
  - Verified DOCX contains redline formatting runs:
    - strikethrough runs present,
    - underline runs present.

## 2026-03-05 - Iteration 11
- Backend export finalized:
  - Added download endpoint in `guru/views.py`: `download_reviewed_contract_docx`.
  - Added URL route in `geg_guru/urls.py`:
    - `/aerospace/contract-analyzer/download-reviewed-docx/`
  - Export action now returns `download_url` in template context.

## 2026-03-05 - Iteration 12
- UI export UX finalized:
  - Success panel now includes direct download link:
    - `Download reviewed_contract.docx`
  - Existing status path remains visible for filesystem traceability.

## 2026-03-05 - Iteration 13
- Upgraded DOCX comments behavior:
  - `redline_docx.py` now adds true Word margin comments using `Document.add_comment(...)` when available.
  - Keeps inline paragraph fallback if comments are unavailable.

## 2026-03-05 - Iteration 14
- Updated setup documentation:
  - Fixed RAG wording to reflect JSON knowledge source.
  - Added reviewed DOCX generation flow and output path.
  - Added quick test input reference:
    - `docs/test_data/sample_supply_contract_for_redline_test.txt`.

## 2026-03-05 - Iteration 15
- Final E2E verification:
  - Re-ran upload -> ask -> export using test contract text.
  - Confirmed export response includes direct download URL:
    - `/aerospace/contract-analyzer/download-reviewed-docx/`
  - Downloaded generated document via endpoint and validated:
    - `Content-Disposition: reviewed_contract.docx`
    - redline formatting runs present (`strike` + `underline`)
    - margin comments present (`comments_count = 20`).

## 2026-03-05 - Iteration 16
- Changed DOCX export behavior to direct document mapping:
  - `redline_docx.py` now loads uploaded `.docx` as base document.
  - Applies redline edits only to matched clause paragraphs in-place.
  - Leaves untouched paragraphs unchanged.
  - Removes report/table-style section output from exported DOCX.

## 2026-03-05 - Iteration 17
- Updated export plumbing:
  - `chat_agent.generate_reviewed_contract_docx()` now passes latest uploaded `.docx` path to DOCX builder.
  - Keeps text fallback for non-docx uploads.

## 2026-03-05 - Iteration 18
- Validated direct-mapping export behavior:
  - Confirmed exported DOCX no longer contains report/table heading sections.
  - Confirmed untouched paragraphs remain unchanged in mapped output.
  - Verified in-place redline + margin comments path using synthetic clause mapping:
    - strike runs present,
    - underline runs present,
    - Word comments present.

## 2026-03-05 - Iteration 19
- Fixed extraction quality for `.docx` uploads:
  - `chat_agent._extract_text()` now uses `docx2txt` fallback explicitly for `.docx`.
  - Removed unsafe plain-text fallback for non-`.txt` files to prevent binary/zip gibberish ingestion.
- Hardened evidence candidate filtering:
  - `agent1_clause_analyzer._aero_sentence_candidates()` now drops low-quality non-printable fragments.

## 2026-03-05 - Iteration 20
- Added robust `.docx` parsing fallback using `python-docx`:
  - `chat_agent._extract_text()` now extracts paragraph + table text through `python-docx` before `docx2txt`.
  - `utils_doc_loader.extract_doc_text()` now also uses `python-docx` first for DOCX-like files.
- Goal: prevent empty extraction on valid OOXML files and improve clause matching reliability.

## 2026-03-05 - Iteration 21
- Re-validated using `test_supply_agreement_contract.docx`:
  - Extraction now returns non-empty text (`chars=4597`) with clean contract preview.
  - Ask output no longer shows gibberish markers from binary payload.
  - Clause table no longer filled with `Insufficient evidence`/`No direct matching` defaults for this sample.
  - Exported `reviewed_contract.docx` confirms in-place mapping behavior:
    - no report/table heading injected,
    - strike runs present,
    - underline runs present,
    - Word comments present.

## 2026-03-05 - Iteration 22
- Fixed Agent 3 fallback behavior in orchestrator:
  - In `chat_agent.py`, when Agent 3 returns `No risks identified` but clause table contains non-green/non-yes rows, a deterministic checklist is generated from the current clause table.
  - This keeps checklist and visible table consistent in the UI.

## 2026-03-05 - Iteration 23
- Added table CSV export feature:
  - New backend generator `generate_clause_table_csv(session_id)` in `chat_agent.py`.
  - Added POST action `export_table_csv` in `guru/views.py`.
  - Added download endpoint `download_clause_csv` and route.
  - Updated UI with `Export Table CSV` button and success/download panel.

## 2026-03-05 - Iteration 24
- Verification pass for Agent 3 + CSV:
  - Ran upload -> ask -> export CSV flow with `test_supply_agreement_contract.docx`.
  - Confirmed checklist no longer shows `No risks identified` for risky table rows.
  - Confirmed CSV generation success block and download URL rendering.
  - Confirmed CSV download headers/content:
    - `clause_analysis.csv` attachment,
    - expected header columns,
    - 10 data rows.

## 2026-03-05 - Iteration 25
- Created a showcase `.docx` input for full pipeline demonstration:
  - `docs/test_data/sample_aerospace_supply_showcase.docx`
  - Includes all 10 POC clauses with a mix of aligned and intentionally risky wording
    so table output, counterfactuals, and mitigation checklist are all visible.

## 2026-03-05 - Iteration 26
- Validated showcase input through app flow (upload -> ask):
  - table rendering present,
  - counterfactual block present,
  - Agent 3 checklist present,
  - no false `No risks identified` output.

## 2026-03-05 - Iteration 27
- Updated download UX to immediate browser attachment response:
  - In `guru/views.py`, `export_reviewed_docx` now generates and immediately returns `reviewed_contract.docx` as attachment.
  - In `guru/views.py`, `export_table_csv` now generates and immediately returns `clause_analysis.csv` as attachment.
  - Added shared `_as_download(...)` helper and reused it for explicit download endpoints.

## 2026-03-05 - Iteration 28
- UI polish for download placement and Guru-style look:
  - Added persistent `Download DOCX` and `Download CSV` action buttons in the input action row (visible when files exist).
  - Styled download buttons with brand-aligned magenta tone and rounded controls.
  - Success messages now say `Download started in browser` (no long path text noise).

## 2026-03-05 - Iteration 29
- Quality/conciseness tuning pass:
  - Reduced local LLM defaults for stability:
    - temperature `0.1`
    - top_p `0.8`
    - max_tokens `1536`
  - Tightened counterfactual verbosity:
    - Agent 3 counterfactual bullets now compacted to concise first-sentence guidance.
  - Fallback checklist now uses `risk_rationale` in Risk column for clearer, to-the-point output.

## 2026-03-05 - Iteration 30
- Verified UI placement + browser download behavior:
  - Immediate DOCX/CSV exports still return attachment responses.
  - After first export, persistent `Download DOCX` button appears in action row.
  - After CSV export, persistent `Download CSV` button appears in action row.
  - Counterfactual block remains present and checklist avoids false `No risks identified` in showcase test flow.

## 2026-03-05 - Iteration 31
- Updated local model default hyperparameters in `agents/sample_agent/config.py`:
  - `LOCAL_LLM_TEMPERATURE = 0.05`
  - `LOCAL_LLM_TOP_P = 0.6`
  - `LOCAL_LLM_MAX_TOKENS = 2048`

## 2026-03-05 - Iteration 32
- Simplified export actions in `workspace_aerospace_contract_analyzer` UI:
  - Removed duplicate DOCX flow (separate `Download DOCX` button).
  - Kept a single DOCX action: `Generate Reviewed DOCX` (generate + direct browser download).
  - Moved CSV export action from the bottom input action row to directly below the rendered analysis table.
  - Removed unused `has_docx_export` / `has_csv_export` context flags from `guru/views.py`.

## 2026-03-05 - Iteration 33
- Final UX + output-quality stabilization pass:
  - Added a polished request progress strip with animated loading bar for long-running actions (upload/ask/export/remove/reset).
  - Added action-specific loading messages in frontend JS (e.g., clause analysis up to ~20s, DOCX generation, CSV export).
  - Normalized mitigation checklist rendering:
    - Added deterministic checklist row parsing from Agent 3 markdown output.
    - Added robust fallback checklist rows derived directly from `clause_table` when Agent 3 markdown is missing/malformed.
    - Rendered checklist as a structured HTML table in the UI instead of raw markdown text.
  - Kept counterfactual and clause-table flows intact while improving display consistency and reliability.

## 2026-03-05 - Iteration 34
- Production-grade analysis hardening:
  - Upgraded `agent1_clause_analyzer.run_aerospace_clause_extraction` with clause-specific risk calibration rules (not all-Amber fallback).
  - Added structured fields per clause row:
    - `risk_trigger`
    - `expected_risk_shift`
    - improved `counterfactual` with explicit Current issue -> Required change -> Expected shift.
  - Improved mitigation generation from generic text to policy-directed clause fixes.
- Agent 3 output normalization:
  - Switched checklist UI rendering to richer structured rows from `clause_table` with columns:
    - Clause
    - Risk Trigger
    - Mitigation Recommendation
    - Approval Route
    - Priority
- Counterfactual quality upgrade:
  - Added structured counterfactual rows and rendered them in a dedicated table with:
    - Clause
    - Current Text
    - Required Change
    - Expected Risk Shift
    - Why
- Redline safety improvements:
  - Added edit guardrails in `redline_docx.py` to avoid low-overlap paragraph rewrites.
  - Improved evidence paragraph selection to avoid heading-only fragments.

## 2026-03-05 - Iteration 35
- Final DOCX renderer hardening (legal-redline quality pass):
  - Enforced strict skip for `Green` rows: no redline writes and no legal deviation comments for aligned clauses.
  - Added clause-body-only targeting:
    - Paragraph matcher now excludes heading-like/short non-sentence lines.
    - Validator requires sentence-like clause body before editing.
  - Added stronger validator gate before write:
    - Rejects empty/identical edits.
    - Rejects low-overlap and extreme-length rewrites.
    - Avoids reserving paragraph index until edit is validated.
  - Added risk-aware comment tone:
    - `Red`: high-risk deviation wording.
    - `Amber`: policy deviation requiring legal alignment.
    - `Green`: no counterfactual/deviation comments (rows skipped).
  - Added minimal clause-level edit strategy for high-risk clauses (targeted replacements) before fallback to ideal-text alignment, reducing blended redline artifacts.

## 2026-03-05 - Iteration 36
- Implemented final hardening plan to production baseline:
  - Liquidated Damages rule tightened in `agent1_clause_analyzer.py`:
    - marks Red when any of these are found: weekly rate > `0.5%`, cap > `5%`, total-contract-value basis, additive-remedy wording.
    - rationale now explicitly references delayed-value basis + bounded rate/cap policy.
  - Added canonical structured edit instructions in `chat_agent.py`:
    - per-clause object includes `clause_id`, `clause_name`, `risk_level`, `evidence_text`, `original_text`, `suggested_text`, `reason`, `counterfactual`, `approval_path`.
    - DOCX renderer now receives `edit_instructions` instead of relying only on free-form row fields.
  - Enforced renderer validator + safe skip path in `redline_docx.py`:
    - validates paragraph/body match against `original_text` hint,
    - validates edit materiality and overlap/length constraints,
    - records render warnings for skipped edits (no inline pollution in DOCX body).
  - Refined token-level redline rules:
    - added targeted LD replacements (`1.0% -> 0.5%`, `12% -> 5%`, `total contract value -> delayed value`, remove additive-remedy phrase).
  - Margin-comment policy fix:
    - removed inline fallback comments; if margin comments are unavailable in runtime, export logs warnings and keeps contract body clean.
  - Regression checks completed:
    - syntax/lint clean,
    - LD detection now outputs Red on non-compliant sample language,
    - green-clause skip + heading-skip + validator gates active,
    - generated validation DOCX artifacts under `Downloads` for manual review.
