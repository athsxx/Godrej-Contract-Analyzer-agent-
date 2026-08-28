# Knowledge Source JSON → DOCX Verification Report

**Date:** 2026-03-06  
**Scope:** Verify complete project layout after knowledge source changes from JSON to DOCX.  
**Assumption:** New DOCX loader parses DOCX and returns the same `{ meta, clauses }` structure.

---

## 1. Executive Summary

| Area | Status | Notes |
|------|--------|-------|
| DOCX redlining validator | ✅ No changes needed | Validator works with clause_table from Agent1 |
| Comments (policy, mitigation, counterfactual, approval) | ✅ No changes needed | All data comes from clause_table |
| Counterfactuals render | ✅ No changes needed | Uses clause_table keys |
| Agent1 `run_aerospace_clause_extraction` | ⚠️ Depends on loader | Needs `{ meta, clauses }` with clause schema |
| RAG and `_knowledge_as_text` | ⚠️ RAG needs update | RAG uses `path.read_text()` – breaks on binary DOCX |
| POC_KNOWLEDGE_PATH config | ⚠️ Update required | Point to `.docx` when switching source |

**Critical gap:** No DOCX knowledge loader exists. Current `_load_poc_knowledge_payload` treats non-JSON as `raw_text` via `path.read_text()`, which fails on binary DOCX.

---

## 2. Files and Components to Check

### 2.1 Knowledge loader and consumers

| File | Component | Check |
|------|-----------|-------|
| `agents/sample_agent/chat_agent.py` | `_load_poc_knowledge_payload()` | **Must add DOCX parsing** – currently uses `read_text()` for non-JSON |
| `agents/sample_agent/chat_agent.py` | `_knowledge_as_text()` | OK if payload has `clauses` or `raw_text` |
| `agents/sample_agent/config.py` | `POC_KNOWLEDGE_PATH` | Update default or env to `.docx` path when switching |

### 2.2 Clause extraction (Agent1)

| File | Component | Check |
|------|-----------|-------|
| `agent1_clause_analyzer.py` | `run_aerospace_clause_extraction()` | Expects `knowledge_payload.get("clauses")` – each clause: `name`, `ideal_position`, `approval_path`, `keywords` |
| `agents/sample_agent/chat_agent.py` | `_build_clause_rows()` | Uses hardcoded `CLAUSE_RULES` – fallback when Agent1 fails; **independent of knowledge file** |

### 2.3 Redlining and comments (DOCX export)

| File | Component | Check |
|------|-----------|-------|
| `agents/sample_agent/redline_docx.py` | `_is_valid_edit()` | Operates on `original_text`, `edited_text` – no knowledge dependency |
| `agents/sample_agent/redline_docx.py` | `_normalize_instruction()` | Maps clause_table row keys: `clause_name`, `gb_ideal_position`, `mitigation_recommendation`, `risk_rationale`, `counterfactual`, `approval_path`, `evidence_snippet` |
| `agents/sample_agent/redline_docx.py` | `build_reviewed_contract_docx()` | Uses `clause_table` → `_instructions_from_clause_table()` → row keys above |
| `agents/sample_agent/redline_docx.py` | `_add_risk_aware_margin_comments()` | Uses `policy_comment`, `counterfactual_comment`, `mitigation`, `approval_path` from row |

### 2.4 Comments data flow (policy, mitigation, counterfactual, approval)

| Source | Field | Row key | Used in redline_docx |
|--------|------|--------|------------------------|
| Agent1 | risk_rationale | `risk_rationale` | `policy_comment` |
| Agent1 | counterfactual | `counterfactual` | `counterfactual_comment` |
| Agent1 | mitigation_recommendation | `mitigation_recommendation` | `mitigation` |
| Agent1 | approval_path | `approval_path` | `approval_path` |

All come from `clause_table` produced by Agent1 (or `_build_clause_rows`). **No change needed** if clause schema in knowledge is preserved.

### 2.5 Counterfactuals

| File | Component | Check |
|------|-----------|-------|
| `agents/sample_agent/chat_agent.py` | `_counterfactual_rows_from_clause_table()` | Uses: `clause_name`, `evidence_snippet`, `gb_ideal_position`, `risk_trigger`, `risk_rationale`, `expected_risk_shift`, `mitigation_recommendation` |
| `guru/templates/guru/workspace_aerospace_contract_analyzer.html` | Counterfactual table | Renders `counterfactual_rows` with `clause`, `current_text`, `required_change`, `risk_shift`, `reason` |

**Conclusion:** Counterfactuals render correctly from clause_table. No changes needed.

### 2.6 RAG

| File | Component | Check |
|------|-----------|-------|
| `agents/sample_agent/rag.py` | `load_poc_and_index()` | Uses `path.read_text()` – **breaks on binary DOCX** |
| `agents/sample_agent/rag.py` | `retrieve_for_session()` | Queries policy + upload collections; POC indexed by `load_poc_and_index` |

**Note:** `retrieve_for_session` and `load_poc_and_index` are not used in the main chat analysis flow (which uses `_knowledge_as_text(knowledge_payload)`). If RAG is invoked elsewhere or planned, DOCX support must be added.

---

## 3. Breaking Changes and Adjustments Needed

### 3.1 Critical: Add DOCX knowledge loader

**Current behavior (`_load_poc_knowledge_payload`):**

```python
if path.suffix.lower() == ".json":
    _KNOWLEDGE_CACHE = json.loads(raw) if raw.strip() else {}
else:
    _KNOWLEDGE_CACHE = {"meta": {}, "clauses": [], "raw_text": raw}
```

- For non-JSON, `path.read_text()` on a `.docx` file returns binary-decoded garbage.
- `clauses` is always `[]` for non-JSON, so Agent1 gets no clause definitions.

**Required change:**
- Add a DOCX parser (e.g. using `python-docx` to read tables per `KNOWLEDGE_MAPPING_ANALYSIS.md`).
- Map DOCX table columns to clause schema: `name`, `ideal_position`, `approval_path`, `keywords`.
- Return `{ meta, clauses }` with the same structure as the JSON loader.
- Optionally keep `raw_text` for `_knowledge_as_text` fallback by concatenating clause text.

### 3.2 RAG: `load_poc_and_index` for DOCX

**Current behavior:**
```python
text = path.read_text(encoding="utf-8", errors="replace")
chunks = _chunk_text(text)
```

**Required change:**
- If path ends with `.docx`, extract text via `utils_doc_loader.extract_doc_text` (or equivalent) before chunking.
- Or reuse the DOCX knowledge loader’s text output (e.g. `_knowledge_as_text(payload)`) to avoid dual parsing.

### 3.3 Config: `POC_KNOWLEDGE_PATH`

**Current default:**
```python
str(Path(__file__).resolve().parents[2] / "docs" / "knowledge" / "Contract_Positions_POC_GB_Legal_2026-02-19.json")
```

**Adjustment:**
- When switching to DOCX, set `POC_KNOWLEDGE_PATH` (env or default) to the DOCX path, e.g.  
  `docs/knowledge/Contract_Positions_POC_GB_Legal_2026-02-19.docx`.

---

## 4. Consumer Trace: `knowledge_payload` and `clause_table`

### 4.1 `knowledge_payload` consumers

| Consumer | Location | Expects |
|----------|----------|---------|
| Agent1 `run_aerospace_clause_extraction` | `agent1_clause_analyzer.py` | `clauses` list; each clause: `name`, `ideal_position`, `approval_path`, `keywords` |
| `_knowledge_as_text` | `chat_agent.py` | `raw_text` or `clauses` with `name`, `ideal_position`, `approval_path` |
| `_extract_clause_table_via_llm` (LLM fallback) | `chat_agent.py` | `knowledge_text` from `_knowledge_as_text` |

### 4.2 `clause_table` consumers

| Consumer | Location | Keys used |
|----------|----------|-----------|
| `_instructions_from_clause_table` | `redline_docx.py` | clause_id, clause_name, risk_level, detected, evidence_text, original_text, suggested_text, gb_ideal_position, mitigation_recommendation, risk_rationale, counterfactual, approval_path |
| `_build_edit_instructions_from_clause_table` | `chat_agent.py` | evidence_snippet, suggested_text, gb_ideal_position, mitigation_recommendation, risk_rationale, risk_trigger, counterfactual, approval_path |
| `_counterfactual_rows_from_clause_table` | `chat_agent.py` | clause_name, evidence_snippet, gb_ideal_position, risk_trigger, risk_rationale, expected_risk_shift, mitigation_recommendation |
| `_checklist_rows_from_clause_table` | `chat_agent.py` | clause_name, risk_level, risk_trigger, risk_rationale, mitigation_recommendation, approval_path |
| `_fallback_mitigation_checklist_from_clause_table` | `chat_agent.py` | clause_name, risk_level, risk_rationale, mitigation_recommendation, approval_path |
| `_to_agent1_style_markdown` | `chat_agent.py` | clause_name, gb_ideal_position, risk_level, detected, risk_rationale, knowledge_reference |
| `generate_clause_table_csv` | `chat_agent.py` | All row keys for CSV headers |
| Template `workspace_aerospace_contract_analyzer.html` | `guru/templates` | clause_name, detected, uploaded_position, gb_ideal_position, risk_level, confidence_label, confidence_score, risk_rationale, mitigation_recommendation, approval_path, evidence_snippet, knowledge_reference |

**Conclusion:** `clause_table` is produced by Agent1 (or `_build_clause_rows`) from `knowledge_payload`. As long as the DOCX loader returns the same `{ meta, clauses }` schema and Agent1’s output shape is unchanged, all consumers remain compatible.

---

## 5. Verification Checklist

| # | Item | Verified |
|---|------|----------|
| 1 | DOCX redlining validator (`_is_valid_edit`, overlap, length) works with clause_table | ✅ Yes – validator is text-based only |
| 2 | Comments (policy, mitigation, counterfactual, approval) get correct data from clause_table | ✅ Yes – all from row keys |
| 3 | Counterfactuals render correctly | ✅ Yes – `_counterfactual_rows_from_clause_table` and template |
| 4 | Agent1 `run_aerospace_clause_extraction` gets clauses with name, ideal_position, approval_path, keywords | ✅ Yes – if loader returns `{ meta, clauses }` with that schema |
| 5 | RAG and `_knowledge_as_text` work | ⚠️ `_knowledge_as_text` yes if payload structure unchanged; RAG needs DOCX text extraction |
| 6 | POC_KNOWLEDGE_PATH points to DOCX | ⚠️ Config update required when switching |

---

## 6. Recommended Next Steps

1. Implement a DOCX knowledge loader that parses the DOCX table and returns `{ meta, clauses }` with the same schema as the JSON.
2. Update `_load_poc_knowledge_payload` to call this loader when `path.suffix.lower() == ".docx"`.
3. Update `rag.load_poc_and_index` to extract text from DOCX (or reuse the loader) before chunking.
4. Set `POC_KNOWLEDGE_PATH` to the DOCX file path when deploying with DOCX as the source.
5. Add a `scripts/sync_knowledge_from_docx.py` (per `KNOWLEDGE_MAPPING_ANALYSIS.md`) for optional JSON sync if both formats are maintained.
