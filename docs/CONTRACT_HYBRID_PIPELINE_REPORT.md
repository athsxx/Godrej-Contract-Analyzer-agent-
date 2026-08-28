# Contract POC: hybrid (local LLM + deterministic) pipeline — current state

This report describes how the repository combines **local LLMs** (Ollama-compatible), **deterministic** contract processing, **JSON-structured** extraction, **Celery + Redis** for async jobs, and **human-in-the-loop** controls as of the current codebase.

---

## 1. Executive summary


| Area                                | Status                                                                                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Clause identification (POC)**     | **In place**: fixed `CLAUSE_SPEC` checklist + chunked LLM extraction (`agent1_clause_analyzer`), orchestrated via `master_orchestrator` / optional LangGraph.                                    |
| **Deterministic DOCX redlines**     | **In place**: `redline_docx` builders, paragraph anchoring, validators, optional parallel apply, `EDIT_STRATEGY=rule_first` by default.                                                          |
| **Hybrid refinement (LLM + rules)** | **In place**; use `**DETERMINISTIC_CONTRACT_MODE=1`** to bias toward **rule-only DOCX edits** while keeping extraction/narrative LLM paths.                                                      |
| **HITL on export**                  | **In place**: session-stored accepted row IDs filter `edit_instructions` before DOCX build (`REQUIRE_REDLINE_HITL_ACCEPTANCE`, default on).                                                      |
| **Celery + Redis**                  | **In place**: `run_detection_analysis_job` calls `**chat_agent.run_detection_analysis_for_session`** (same path as sync), persists `**clause_table`** + trace + optional HITL sidecar artifacts. |
| **HITL orchestrator (sidecar)**     | **In place**: `hitl_orchestrator` — deterministic heading scan + optional LLM JSON suggestions (`ENABLE_HITL_PIPELINE_LLM`), then verify + `comment_specs` (parallel to export checkbox HITL).   |
| **Async workspace analyze**         | **Optional** (`ENABLE_ASYNC_CONTRACT_ANALYSIS=1`): **Analyze clauses** enqueues a job and **polls** `GET /api/analysis/jobs/<uuid>/` until success, then reloads the page.                       |


**Clause count:** **14 top-level themes** from `**CLAUSE_SPEC`**. The UI table often shows more rows (sub-items per theme). `**poc_clause_theme_names()`** in `chat_agent.py` aligns the LLM table-fallback prompt with those 14 names.

---

## 2. Local LLMs (Ollama-style)

- **Config:** `agents/sample_agent/config.py` — `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, per-role overrides (`LOCAL_LLM_MODEL_EXTRACTION`, `…_EDITING`, `…_CLASSIFY`, `…_CHAT`), low temperatures for extraction/classify.
- **Provider:** `LLM_PROVIDER` defaults to `local` (Bedrock optional via env).
- **Usage:** Agent 1 JSON extraction, Agent 2/3 where enabled, optional semantic edits on export, Agent 4, optional RAG over `POC_KNOWLEDGE_PATH` and uploads.

Outputs are **bounded** by parsing, validators, and deterministic fallbacks (§4).

---

## 3. Deterministic approach for contracts

1. **Fixed clause ontology** — `CLAUSE_SPEC` drives obligations (Yes/No/Partial/NA) with evidence; chunking + keyword scoring choose segments.
2. **Orchestration** — `master_orchestrator.run_contract_analysis_master` (LangGraph optional, then `run_analysis_pipeline`, then Agent1-only fallback).
3. **DOCX** — `redline_docx` from `clause_table` + `edit_instructions` (anchoring, validators, `EDIT_STRATEGY`, `ENABLE_SEMANTIC_FALLBACK_TO_RULE`).
4. **Matching** — e.g. `orchestrator.py` parallel evidence validation; referenced-doc upload matching in `agent1_clause_analyzer.py`.
5. **Export gating** — `_filter_edit_instructions_for_hitl` + session `redline_accepted_clause_ids` (only when `**ENABLE_REDLINE_DOCX_EXPORT=1`**; UI hides redline export by default).

---

## 4. Hybrid refinement (LLM + deterministic)

- `**EDIT_STRATEGY`**: default `**rule_first`**.
- `**ENABLE_SEMANTIC_FALLBACK_TO_RULE**`: invalid LLM edit → rule redline when possible.
- `**ENABLE_AGENT4_VERIFICATION**` + `**SKIP_REDLINE_WHEN_AGENT4_FLAGS**`.
- **RAG / alignment** — `ENABLE_AGENT1_RAG_CONTEXT`, `ENABLE_EVIDENCE_DOC_ALIGNMENT`, etc.

---

## 5. JSON, job UUIDs, and persistence


| Mechanism                            | Role                                                                                                                                     |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent 1**                          | Strict JSON checklist rows in prompts (`clause_id`, `clause`, `subitem`, `status`, `evidence`, …).                                       |
| `**clause_table`**                   | Rows on the latest assistant message after analysis (UI, CSV, DOCX).                                                                     |
| **Export row IDs**                   | String `**clause_id`** = `"1"`, `"2"`, … from table order; session `**redline_accepted_clause_ids`**.                                    |
| `**AnalysisJob.id`**                 | **UUID** primary key; APIs return `**job_id`** as that string.                                                                           |
| `**GET /api/analysis/jobs/<uuid>/`** | `**status`**, timestamps, `**artifacts`**, optional `**clause_table_row_count**` when succeeded, `**payloads**` if `?include_payload=1`. |
| `**input_hash**`                     | Digest of upload file mtimes (`guru.views._session_upload_digest`), for traceability.                                                    |
| `**AnalysisArtifact.payload**`       | JSON: e.g. `{"rows": [...]}` for clause table; `trace` includes `**hitl_sidecar**`; optional `**suggestions**` with `comment_specs`.     |


---

## 6. Celery and Redis

- **Broker / backend:** `redis://127.0.0.1:6379/0` by default (`geg_guru/settings.py`).
- **App:** `geg_guru/celery.py` → `guru.tasks`.
- **Task:** `run_detection_analysis_job(job_id)` — `RUNNING`, clears old artifacts, `**run_detection_analysis_for_session`** (rehydrate from `**UPLOAD_ROOT/<session_id>/`** + `_upload_roles.json`, then `**answer_question`**), `**run_hitl_pipeline_locally`**, writes artifacts, `**succeeded**` / `**failed**`.
- **Enqueue:** `supervisor_orchestrator.enqueue_detection_job` — persists `**config_snapshot`** (models + flags), `.delay()`. `**CELERY_TASK_ALWAYS_EAGER=1`** runs inline (no worker process).
- **UI:** Default **sync** `analyze_clauses`; **async** when `ENABLE_ASYNC_CONTRACT_ANALYSIS=1` (`workspace_sample_agent.js` polls job URL).

---

## 7. Human-in-the-loop vs “learning”

**Nothing in this repo trains the LLM or auto-updates rules from human clicks.**


| Mechanism        | Human / program action            | Effect                                                            |
| ---------------- | --------------------------------- | ----------------------------------------------------------------- |
| **Export HITL**  | Checkboxes + save                 | Filters `**edit_instructions`** only.                             |
| **Async jobs**   | Enqueue + poll                    | Persists **Postgres JSON** artifacts; audit/API.                  |
| **HITL sidecar** | Worker runs stages after analysis | **Structured** trace + optional comment specs; no weight updates. |


Product-level “learning” would require an explicit pipeline (dataset export, fine-tuning jobs, or curated knowledge doc changes) — **not implemented here**.

---

## 8. Target pipeline (product intent — bounded LLM, jobs, executive HITL)

This section captures the **direction of travel** (not all steps are fully wired as a single named pipeline yet).

1. **Local LLMs only for bounded work** — Every LLM call is framed as **structured extraction**: fixed JSON schema, tight token limits, **temperature 0** (or near‑zero) for extraction/classify roles, no open-ended “rewrite the contract.”
2. **Paragraph IDs** — Deterministic preprocessing assigns **stable paragraph (or block) IDs** in the working document model; LLM output references those IDs so downstream code can anchor commentary without free‑text span guessing.
3. **Django request → background job** — The browser (or API client) **starts a short Django request** that **enqueues** work (`AnalysisJob` UUID), returns `**job_id`**; **Celery** workers run heavy extraction/analysis and **persist JSON to Postgres** via `AnalysisArtifact` (and optional summaries on the job row).
4. **Lightweight retrieval** — Small top‑k context (uploads + knowledge index), **optional** and bounded by char caps, so retrieval does not dominate or drift anchors.
5. **Deterministic orchestration calls the LLM** — The **orchestrator** decides *when* to call the model (which sub‑prompt, which schema); validators reject or repair JSON before merge.
6. **Human‑in‑the‑loop at executive level** — Beyond row‑level export gates, HITL is aimed at a **high‑level contract read**: e.g. *given this claim / clause, risk sits in X; ideal position is Y; gap is Z; **proposal** needed is …; **clearance** route is …* — suitable for Legal/BU review summaries rather than only micro‑checkbox redline control.

**Outcome:** same hybrid principle end‑to‑end — **LLM proposes bounded JSON**, **deterministic code merges and explains**, **Postgres holds auditables**, **humans approve the executive story** (and later, optional fine‑tuning uses exported labels—not silent online learning).

---

## 9. Remaining gaps

1. **Multi-host workers** need **shared disk** (or replace rehydrate with DB-backed session snapshots).
2. **Surface** `comment_specs` / sidecar in HTML (optional).
3. `**CLAUSE_RULES`** (keyword fallback in `chat_agent`) may still be closer to the older GB list than to all 14 `CLAUSE_SPEC` themes — align if `_build_clause_rows` is critical for you.

---

## 10. Commands (reference)

### Deterministic-first preset (edits / export)

One env var tightens the stack for **rule-based behavior** where it still applies (e.g. if you turn `**ENABLE_REDLINE_DOCX_EXPORT`** back on) and turns off optional LLM on analysis/export extras (semantic paragraph rewrites on export, Agent 4, LangGraph, GraphRAG, HITL pipeline LLM). **Agent 1 / Agent 2 / Agent 3** still use the LLM when the pipeline reaches them (extraction temperature stays low by default).

```bash
export DETERMINISTIC_CONTRACT_MODE=1
./scripts/run_contract_tests_deterministic.sh
# or full agent tests:
# DETERMINISTIC_CONTRACT_MODE=1 ./.venv/bin/python -m pytest agents/sample_agent/tests/ -q
```

```bash
export ENABLE_REDLINE_DOCX_EXPORT=1   # re-enable reviewed DOCX strike/underline export + HITL column
```

### Environment and runserver

From repo root:

```bash
cd /path/to/contractual_scaffolding
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=geg_guru.settings
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

**Redis + Celery worker**

```bash
brew services start redis   # or your OS equivalent
export DJANGO_SETTINGS_MODULE=geg_guru.settings
celery -A geg_guru worker -l info
```

**Dev without Redis worker**

```bash
export CELERY_TASK_ALWAYS_EAGER=1
export DJANGO_SETTINGS_MODULE=geg_guru.settings
python manage.py runserver 0.0.0.0:8000
```

**Async UI + optional HITL LLM leg**

```bash
export ENABLE_ASYNC_CONTRACT_ANALYSIS=1
export ENABLE_HITL_PIPELINE_LLM=0    # set 1 to call Ollama inside hitl_orchestrator during jobs
```

**Job API**

```bash
curl -s -X POST http://127.0.0.1:8000/api/analysis/jobs/ \
  -H "Content-Type: application/json" \
  -d '{"session_id":"YOUR_DJANGO_SESSION_KEY","input_hash":""}'
curl -s "http://127.0.0.1:8000/api/analysis/jobs/JOB_UUID/"
```

**Tests**

```bash
python -m pytest agents/sample_agent/tests/ -q
```

---

## 11. Key file map


| Concern                        | Path                                                                                                                               |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Flags                          | `agents/sample_agent/config.py`                                                                                                    |
| Extraction checklist           | `agents/sample_agent/agent1_clause_analyzer.py`                                                                                    |
| Analysis routing               | `agents/sample_agent/master_orchestrator.py`, `orchestrator.py`                                                                    |
| Session + rehydrate + analysis | `agents/sample_agent/chat_agent.py`                                                                                                |
| DOCX                           | `agents/sample_agent/redline_docx.py`                                                                                              |
| Workspace + async POST         | `guru/views.py`, `guru/templates/guru/workspace_aerospace_contract_analyzer.html`, `guru/static/guru/js/workspace_sample_agent.js` |
| Celery task                    | `guru/tasks.py`                                                                                                                    |
| Job API                        | `guru/views_analysis.py`                                                                                                           |
| Sidecar HITL                   | `agents/sample_agent/hitl_orchestrator.py`, `agents/sample_agent/supervisor_orchestrator.py`                                       |


---

*End of report.*