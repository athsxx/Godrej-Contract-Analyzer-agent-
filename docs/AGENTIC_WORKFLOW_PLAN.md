# Agentic Workflow Plan: pdf2docx + Agent 4 Verifier

## Overview

This plan integrates two new capabilities into the contract analysis pipeline:

1. **pdf2docx** – Layout-preserving PDF-to-DOCX conversion for reviewed contract export
2. **Agent 4** – Post-redline verification agent for semantic/contextual fit of edits (non-blocking, flag-only)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         CONTRACT ANALYSIS PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│  1. Upload (PDF/DOCX) → Text extraction                                          │
│  2. Agent 1 → clause_table (source of truth)                                       │
│  3. Agent 2 → risk_mitigation (from clause_table)                                 │
│  4. Agent 3 → mitigation_checklist (from Agent 2 / clause_table)                  │
│  5. Export: CSV, Counterfactuals, Mitigation Checklist, Reviewed DOCX             │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                    NEW: REVIEWED DOCX EXPORT FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│  generate_reviewed_contract_docx(session_id)                                       │
│       │                                                                           │
│       ├─► IF source is PDF: pdf2docx.Converter → converted.docx (layout preserved)│
│       │   ELSE: use uploaded DOCX directly                                        │
│       │                                                                           │
│       ├─► build_reviewed_contract_docx(..., source_docx_path=converted)            │
│       │       │                                                                    │
│       │       ├─► For each clause (Amber/Red, detected=Yes):                        │
│       │       │     - Match evidence → target paragraph                           │
│       │       │     - original_text, edited_text = _normalize_for_edit(...)         │
│       │       │     - [NEW] Agent 4.verify_redline_edit(...) → pass/flag           │
│       │       │     - _write_redline()  [always applied, non-blocking]              │
│       │       │                                                                    │
│       │       └─► Collect verification_flags (from Agent 4)                         │
│       │                                                                           │
│       └─► Return { path, filename, warnings, verification_report }                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Component 1: pdf2docx Integration

### Files to modify
- `requirements.txt` – add `pdf2docx`
- `agents/sample_agent/chat_agent.py` – `generate_reviewed_contract_docx()`

### Logic
- Before redlining, if the primary source file is a PDF (no DOCX uploaded):
  1. Use `pdf2docx.Converter` to convert PDF → DOCX
  2. Save as `{session_id}/{original_stem}_converted.docx`
  3. Pass this as `source_docx_path` to `build_reviewed_contract_docx()`
- Fallback: If pdf2docx fails (import error, conversion error), fall back to `_build_doc_from_extracted_text()` (current behavior)

## Component 2: Agent 4 Verifier Module

### New file: `agents/sample_agent/agent4_verifier.py`

### Responsibilities
- `verify_redline_edit(original_text, edited_text, clause_name, surrounding_context, gb_ideal)` → `{ verdict: "pass"|"flag", reason: str, suggestion: str }`
- Call LLM (local or Bedrock) with structured prompt
- Parse response; default to `pass` on any error

### Prompt design
- Input: original paragraph, edited paragraph, clause name, GB ideal, surrounding 1–2 paragraphs
- Instructions: Assess semantic fit, terminology consistency, grammatical flow, legal coherence
- Output format: JSON `{ "verdict": "pass"|"flag", "reason": "...", "suggestion": "..." }`

### LLM integration
- Reuse `bedrock_llm.call_bedrock_chat` when `ENABLE_BEDROCK=1`
- Add local Ollama path (same pattern as chat_agent) when `LLM_PROVIDER=local`

## Component 3: Redline Integration

### Files to modify
- `agents/sample_agent/redline_docx.py` – `build_reviewed_contract_docx()`
- `agents/sample_agent/config.py` – add `ENABLE_AGENT4_VERIFICATION`
- `agents/sample_agent/chat_agent.py` – pass `verification_report` in return, add optional CSV export

### Logic in `build_reviewed_contract_docx()`
- Add optional parameter `verification_flags: Optional[List]` (out-param)
- When `ENABLE_AGENT4_VERIFICATION` and validator passes:
  1. Get surrounding paragraphs: `doc.paragraphs[target_idx-1]`, `doc.paragraphs[target_idx+1]`
  2. Call `agent4.verify_redline_edit(...)`
  3. If verdict == "flag", append `{ clause_name, reason, suggestion }` to verification_flags
- Always call `_write_redline()` – never block

## Component 4: Config & Output

### Config (`config.py`)
```
ENABLE_AGENT4_VERIFICATION = env "0" | "1"  # default "1"
```

### `generate_reviewed_contract_docx()` return
```python
{
    "path": str,
    "filename": str,
    "warnings": List[str],
    "verification_report": List[Dict],  # NEW: [{ clause_name, reason, suggestion }]
}
```

### Optional: Verification Report CSV
- New export action: `export_verification_report_csv`
- Columns: Clause, Verdict, Reason, Suggestion

## Component 5: Workflow Diagram

```
User: "Analyze this contract"
    → Agent 1 → clause_table
    → Agent 2 → risk_mitigation
    → Agent 3 → mitigation_checklist
    → UI: table, counterfactuals, checklist

User: "Generate Reviewed DOCX"
    → IF PDF: pdf2docx convert (layout preserved)
    → build_reviewed_contract_docx()
        → For each edit:
            → Agent 4 verify (optional, non-blocking)
            → _write_redline()
        → verification_report
    → Return DOCX + verification_report
```

## Parallel Subagent Work Plan

| Subagent | Task | Deliverables |
|----------|------|--------------|
| 1 | pdf2docx + chat_agent integration | requirements.txt update, generate_reviewed_contract_docx() changes |
| 2 | Agent 4 module | agent4_verifier.py |
| 3 | Redline integration + config | redline_docx.py, config.py, chat_agent wiring |

Subagents 1 and 2 can run in parallel. Subagent 3 depends on 2 (needs agent4 import).

## Testing

1. PDF upload → Generate Reviewed DOCX → verify layout preserved (headers, images)
2. DOCX upload → unchanged behavior
3. Agent 4 enabled → verification_report populated when edits flagged
4. Agent 4 disabled → no verification calls, export works
5. Agent 4 error → default pass, export not blocked

## Rollback

- pdf2docx: Remove conversion block; fall back to _build_doc_from_extracted_text
- Agent 4: Set ENABLE_AGENT4_VERIFICATION=0; no code removal needed

---

## Implementation Status ✅

| Component | Status | Files |
|-----------|--------|-------|
| pdf2docx integration | Done | requirements.txt, chat_agent.py |
| Agent 4 module | Done | agent4_verifier.py |
| Redline integration | Done | redline_docx.py, config.py |
| Verification report CSV | Done | chat_agent.py, guru/views.py, template, JS |
