# Godrej Contract Analyzer Agent

Django app that reviews **supply-side aerospace contracts** against GB Legal POC positions. Upload a contract (PDF/DOCX), run clause analysis, get Red–Amber–Green risk with mitigations, then export a reviewed DOCX (redlines + comments), commentary DOCX, or clause CSV.

Outputs are for **POC validation**. They require Legal sign-off before any commercial use. Scope is supply contracts only — not procurement, NDAs, alliances, or other agreement types. See [docs/POC_SCOPE.md](docs/POC_SCOPE.md).

## What it does

| Step | What happens |
|------|----------------|
| 1. Clause extraction | Agent 1 builds a structured clause table from contract text + POC knowledge |
| 2. Risk review | Agent 2 writes a RAG (Red–Amber–Green) narrative with mitigations |
| 3. Checklist | Agent 3 derives a compact mitigation checklist |
| 4. Redline (optional) | Semantic edits + Word comments; Agent 4 can verify proposed edits |

Chat / counterfactuals sit beside the numbered pipeline and are grounded in the same session uploads and knowledge file.

## Quick start

Requires **Python 3.11+**, and optionally [Ollama](https://ollama.com) for the local LLM (default).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Local LLM (default provider)
ollama pull llama3.1:8b

python3 manage.py migrate
python3 manage.py runserver 127.0.0.1:8501
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501) → **Aerospace → Contract Analyzer**. Upload a contract from your local machine, then run analysis.

Full local setup, RAG flags, and Bedrock overrides: [docs/SETUP.md](docs/SETUP.md).

### Tests

```bash
source .venv/bin/activate
pytest agents/sample_agent/tests -q
```

Deterministic contract-test helper: `scripts/run_contract_tests_deterministic.sh`.

### Production-style stack (optional)

Redis + Celery + Gunicorn. From the repo root:

```bash
source scripts/env_day_to_day.sh
# Redis on 127.0.0.1:6379, then:
./scripts/run_production_stack.sh
```

## Repository layout

| Path | Purpose |
|------|---------|
| `agents/sample_agent/` | Clause pipeline, RAG, redline, chat, orchestrators |
| `guru/` | Django views, templates, static JS, Celery tasks |
| `geg_guru/` | Django project settings, URLs, WSGI, Celery app |
| `docs/` | Workflow, setup, POC scope |
| `docs/knowledge/` | Knowledge mapping notes (GB Legal DOCX is local, not committed) |
| `scripts/` | Env presets, production stack, PEFT helpers, tests |
| `data/` | Optional PEFT JSONL (contracts and appendix files are not committed) |
| `manage.py` | Django entrypoint |
| `requirements.txt` | Python dependencies |

## Agents and request path

Browser → `/aerospace/contract-analyzer/` → `guru/views.py` → `agents.sample_agent.chat_agent`.

| # | Module | Role |
|---|--------|------|
| 1 | `agent1_clause_analyzer.py` | Extract clause table vs POC positions |
| 2 | `agent2_reviewer.py` | RAG risk report and mitigations |
| 3 | `agent3_mitigation_checklist.py` | Compact checklist from Agent 2 / table |
| 4 | `agent4_verifier.py` | Pass/flag proposed DOCX edits |

Supporting modules: `orchestrator.py`, `master_orchestrator.py`, `redline_docx.py`, `legal_commentary.py`, `rag.py`, `semantic_edit_generator.py`.

Canonical narrative: [docs/WORKFLOW_AND_AGENTS.md](docs/WORKFLOW_AND_AGENTS.md). Code-accurate process: [docs/CURRENT_CONTRACT_ANALYSIS_PROCESS.md](docs/CURRENT_CONTRACT_ANALYSIS_PROCESS.md).

## Configuration

Secrets come from the environment. Do not hard-code keys.

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `local` | `local` (Ollama) or `bedrock` |
| `LOCAL_LLM_MODEL` | `llama3.1:8b` | Ollama model |
| `LOCAL_LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama API |
| `ENABLE_BEDROCK` | `0` | Set `1` to use AWS Bedrock |
| `POC_KNOWLEDGE_PATH` | `docs/knowledge/…docx` | GB Legal positions file |
| `ENABLE_RAG` | `1` | Retrieval over knowledge + uploads |
| `DJANGO_SECRET_KEY` | dev placeholder | Required in production |
| `AZURE_CLIENT_ID` / `TENANT_ID` / `CLIENT_SECRET` | unset | Microsoft Entra SSO |
| `ENFORCE_GLOBAL_LOGIN` | `0` | Require login on all routes |

Day-to-day env: `source scripts/env_day_to_day.sh`. Model wiring: [docs/HOW_IT_IS_LINKED_AND_MODELS.md](docs/HOW_IT_IS_LINKED_AND_MODELS.md).

## Docs map

| Doc | Contents |
|-----|----------|
| [docs/SETUP.md](docs/SETUP.md) | Install, Ollama, RAG, reviewed DOCX |
| [docs/WORKFLOW_AND_AGENTS.md](docs/WORKFLOW_AND_AGENTS.md) | Agents, journeys, config toggles |
| [docs/CURRENT_CONTRACT_ANALYSIS_PROCESS.md](docs/CURRENT_CONTRACT_ANALYSIS_PROCESS.md) | What the code does today |
| [docs/POC_SCOPE.md](docs/POC_SCOPE.md) | Ten critical legal positions |
| [docs/PDF_REDLINING_FLOW.md](docs/PDF_REDLINING_FLOW.md) | PDF → DOCX redline path |
| [docs/DEPLOY_AMETHYST.md](docs/DEPLOY_AMETHYST.md) | Deployment notes |

## What is not in this repo

- `.venv`, `db.sqlite3`, Redis dumps, session uploads under `media/`
- Contract files, appendix documents, GB Legal knowledge DOCX, and sample DOCX/PDF/XLSX (keep them local)
- Environment secrets (`.env`, AWS keys, Azure client secret)

Keep those local. Point `POC_KNOWLEDGE_PATH` at your local GB Legal knowledge DOCX (default path `docs/knowledge/`).
