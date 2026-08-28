# PDF Redlining Flow

## Overview

When a user uploads a **PDF** (instead of DOCX), the system produces a redlined DOCX output with layout preservation and optional Agent 4 verification.

## Flow

1. **PDF text extraction** (`utils_doc_loader.extract_pdf_text`)
   - PyMuPDF extracts full text per page
   - Optional `[PAGE N]` markers are added when `include_page_markers=True`

2. **Clause analysis** (Agent1 / aerospace extraction)
   - Uses the extracted text for clause detection and risk assessment
   - No format dependency; analysis works on plain text

3. **Export reviewed DOCX** (`chat_agent.generate_reviewed_contract_docx`)
   - Looks for an uploaded **DOCX** as the base document
   - If **no DOCX** is found (PDF-only upload): uses **pdf2docx** to convert PDF → DOCX with layout preserved (headers, images, tables)
   - If pdf2docx fails: falls back to `_build_doc_from_extracted_text` (plain text)

4. **PDF layout preservation (pdf2docx)**
   - Converts PDF to DOCX with `pdf2docx.Converter`
   - Preserves headers, footers, images, tables, paragraph structure
   - Output: `{original_stem}_converted.docx` in session folder

5. **Redline application** (`redline_docx.build_reviewed_contract_docx`)
   - Match evidence → validate edit → apply strikethrough/underline
   - **Agent 4** (optional): post-redline verification for semantic/contextual fit. Non-blocking; flags only.
   - Margin comments added for risk/counterfactual/approval

6. **Verification report**
   - When `ENABLE_AGENT4_VERIFICATION=1`, Agent 4 assesses each edit
   - Flagged edits appear in `verification_report` (exportable as CSV)

## Fallback: plain text DOCX

When pdf2docx fails or is not used:
- `_build_doc_from_extracted_text` splits extracted text by double newlines, `[PAGE N]`, sentence boundaries
- Layout (columns, tables, headers) is not preserved

## Configuration

- `ENABLE_AGENT4_VERIFICATION` (env, default `1`): Enable post-redline verification
- `pdf2docx` is in `requirements.txt`; install with `pip install pdf2docx`

## Limitations

- **Scanned PDFs**: Image-based PDFs may have poor text extraction; pdf2docx works best with text-based PDFs.
- **Complex layouts**: Some highly complex PDFs may not convert perfectly.
