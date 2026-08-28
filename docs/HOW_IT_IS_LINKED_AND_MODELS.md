# How Everything Is Linked, and Which Models Are Used

This document explains (1) how the project is wired end-to-end, and (2) what models the app uses and whether **you** must download them.

---

## Part 1: How Everything Is Linked

### 1.1 URL → View → Template (Django)

All user-facing routes are defined in **`geg_guru/urls.py`** and point to functions in **`guru/views.py`**. Each view passes a **context** (data) to a **template** (HTML). The template is chosen by the view’s `render(..., "template_name.html", context)`.

| URL path | URL name | View function | Template |
|----------|----------|---------------|----------|
| `/` | `home` | `guru_views.home` | `guru/home.html` |
| `/aerospace/contract-analyzer/` | `workspace_aerospace_contract_analyzer` | `guru_views.workspace_aerospace_contract_analyzer` | `guru/workspace_aerospace_contract_analyzer.html` |
| `/login/` | `login` | `guru_views.login` | `guru/login.html` |
| `/admin/` | (Django admin) | built-in | admin templates |

So:

- **Home**: `"/"` → `home()` → `home.html`.
- **Contract Analyzer**: `"/aerospace/contract-analyzer/"` → `workspace_aerospace_contract_analyzer()` → `workspace_aerospace_contract_analyzer.html`.
- **Login**: `"/login/"` → `login()` → `login.html`.

The link between “URL” and “what the user sees” is: **urls.py** → **views.py** → **template**.

---

### 1.2 Layout and Sidebar (Shared Shell)

Every page that uses the main app shell extends **`guru/templates/guru/layouts/sidebar_layout.html`**. That layout:

- Extends **`guru/base.html`** (HTML head, CSS).
- Defines the **sidebar** (left) and the **main content area** (right).
- The **main content** is whatever each page puts in `{% block main_content %}` (or `{% block main %}` / `{% block nav_left %}`).

So:

- **`home.html`** extends `sidebar_layout.html` and fills the main area with the dashboard and “Open Contract Analyzer” button.
- **`workspace_aerospace_contract_analyzer.html`** extends the same layout and fills the main area with the chat UI (upload, chat feed, counterfactuals block).

The **sidebar is the same on every page**. It is part of the layout, so it is “linked” to every view that uses that layout.

---

### 1.3 Sidebar Links (How the Sidebar Is Wired)

Inside **`sidebar_layout.html`**, each clickable item uses Django’s **`{% url 'name' %}`** so links stay correct even if you change URL paths later.

- **Logo (top)**: `href="{% url 'home' %}"` → goes to `/`.
- **Home**: `href="{% url 'home' %}"` → `/`.  
  Active when `request.path == '/'`.
- **Aerospace** (section): `<details>` that is **open** when `'/aerospace/' in request.path`.
- **Contract Analyzer**: `href="{% url 'workspace_aerospace_contract_analyzer' %}"` → `/aerospace/contract-analyzer/`.  
  Active when `'/aerospace/contract-analyzer/' in request.path`.
- **Admin Console**: `href="{% url 'admin:index' %}"` → `/admin/`.
- **Sign in**: `href="{% url 'login' %}"` → `/login/`.

So the **process** for “linking” the front end is:

1. Define the route and name in **urls.py**.
2. Implement the view in **views.py** and choose the template.
3. In the **layout** (sidebar), use `{% url 'name' %}` for every link and, if needed, `request.path` to add the `active` class.

Nothing is hardcoded to `#` for the main app routes; Home, Aerospace Contract Analyzer, Login, and Admin are all real links.

---

### 1.4 Contract Analyzer: View → Agent (Backend)

When the user is on **Contract Analyzer** and uploads files or sends a message, the **browser sends a POST** to the same URL: `/aerospace/contract-analyzer/`. The view **`workspace_aerospace_contract_analyzer`** handles it:

1. It reads `request.POST.get("action")` to see what the user did:
   - `reset` → clear session and redirect.
   - `remove_file` → remove one file from the session and re-render.
   - `upload` → call **`sample_agent.index_uploaded_files(session_key, uploads)`**, then re-render with updated file list and any warnings.
   - `ask` → call **`sample_agent.answer_question(session_key, message)`**, then re-render with updated **chat_history**, **assistant_reply** (main answer), and **assistant_counterfactuals** (for the green block).

2. The **view** never calls a model directly. It only talks to **`agents.sample_agent.chat_agent`** (imported as `sample_agent`). So the link is:

   **Browser POST** → **Django view** → **chat_agent** (list_files, index_uploaded_files, answer_question).

3. The view then passes into the template:
   - `chat_history`, `uploaded_files`, `error`, `warnings`
   - `assistant_reply` and `assistant_counterfactuals` (from the last `answer_question` result)

The template **workspace_aerospace_contract_analyzer.html** renders:

- The main answer in the chat bubble from `msg.content` (and `assistant_reply` is reflected in the history that is rendered).
- The counterfactuals in a separate green block when `msg.counterfactuals` is present.

So the **process** for the Contract Analyzer is:

- **Front end**: Form POST (action = upload / ask / reset / remove_file) → same URL → view.
- **View**: Dispatches to `sample_agent.*` and builds context.
- **Template**: Renders context (chat history, counterfactuals, files) inside the shared layout.

---

### 1.5 Agent → RAG and LLM (Where Models Enter)

The **agent** lives in **`agents/sample_agent/`**:

- **`chat_agent.py`**: Session state, file handling, and **`answer_question()`**.
- **`config.py`**: Reads env (and defaults) for model names and paths.
- **`local_llm.py`**: Sends the chat prompt to the **local LLM** (Ollama-compatible HTTP API).
- **`rag.py`**: Loads the POC knowledge file, chunks it, embeds with the **embedding model**, stores in **Chroma**; **`retrieve()`** returns top‑k chunks for the user question.

When the user clicks “Send” (action = **ask**):

1. **`answer_question(session_id, message)`** is called.
2. **RAG** (if available):  
   `rag.ensure_poc_indexed()` → then `rag.retrieve(message, top_k=...)` → list of text chunks from the POC (and the code is set up so uploads could be indexed the same way later).
3. **Context** is built from those chunks plus any uploaded file text previews.
4. **Prompt** = that context + user message. **System prompt** = POC instructions (10 clauses, scope, counterfactuals, disclaimer).
5. **`local_llm.call_local_chat(prompt, system_message=POC_SYSTEM_PROMPT, ...)`** is called → HTTP POST to **Ollama** (`LOCAL_LLM_BASE_URL` + `/api/chat`) with **LOCAL_LLM_MODEL**.
6. The **reply** is parsed: if it contains `"--- Counterfactuals ---"`, the rest is stored as **counterfactuals**; the rest is the **main answer**.
7. **chat_agent** returns `{ "answer", "counterfactuals", "chat_history", "used_files" }` to the view, and the view passes them into the template.

So the **process** for “how the answer is produced” is:

- **User message** → **answer_question** → (optional) **RAG retrieve** (embedding model + Chroma) → **build prompt** → **call_local_chat** (LLM) → **parse reply** → **view** → **template**.

---

### 1.6 Summary Diagram (Links)

```
Browser
   │
   ├─ GET  /                          → home()              → home.html
   ├─ GET  /aerospace/contract-analyzer/  → workspace_aerospace_contract_analyzer() → workspace_aerospace_contract_analyzer.html
   ├─ POST /aerospace/contract-analyzer/  (action=upload/ask/reset/remove_file)
   │       → same view → sample_agent.index_uploaded_files() or answer_question()
   │       → answer_question() uses rag.retrieve() + local_llm.call_local_chat()
   │       → same template with new context
   ├─ GET  /login/                    → login()             → login.html
   └─ GET  /admin/                    → Django admin

Sidebar (in sidebar_layout.html):
   Logo, Home          → {% url 'home' %}
   Aerospace → Contract Analyzer → {% url 'workspace_aerospace_contract_analyzer' %}
   Admin, Sign in      → {% url 'admin:index' %}, {% url 'login' %}
```

Everything the user can click in the sidebar (for this POC) is linked to a real URL and view; the Contract Analyzer is linked from Home and from the Aerospace section, and the same view and template handle both GET and POST for that page.

---

### 1.7 Full pipeline: analysis → redline export (orchestration)

Ordered stages (see also **`agents/sample_agent/workflow.py`** → `WORKFLOW_STAGES`):

1. **Browser POST** to `/aerospace/contract-analyzer/` with `action` = `upload`, `ask`, `reset`, `remove_file`, or export-related actions handled by the same view.
2. **Upload path** (`chat_agent.index_uploaded_files`): extract **full text** per artifact, optional **RAG indexing** when `ENABLE_RAG`, `ENABLE_VECTOR_RETRIEVER`, and `INDEX_UPLOAD_ON_UPLOAD` are on (`rag.index_uploaded_text`).
3. **Analysis path** (user runs clause review from the UI): `chat_agent` loads knowledge, then **`orchestrator.run_analysis_pipeline`**, which runs:
   - **Agent 1** — `agent1_clause_analyzer.run_aerospace_clause_extraction` → structured **clause table** (evidence snippets, risk, etc.).
   - **Agent 2** — `agent2_reviewer.generate_risk_mitigation` → narrative / table markdown.
   - **Agent 3** — `agent3_mitigation_checklist` → checklist markdown.
4. **Optional LangGraph** — disabled in `config.ENABLE_LANGGRAPH`; the supported path is the orchestrator above.
5. **DOCX export** (`chat_agent.generate_reviewed_contract_docx` or equivalent): builds **`reviewed_contract.docx`** via **`redline_docx.build_reviewed_contract_docx`** (or **`build_reviewed_contract_docx_parallel`** if `ENABLE_PARALLEL_REDLINE`):
   - Flatten **body + table** paragraphs for matching.
   - **`_align_evidence_snippet_to_document`** (when `ENABLE_EVIDENCE_DOC_ALIGNMENT`) re-grounds evidence on real paragraph wording so matchers see substrings that exist in the file.
   - **`_find_best_matching_paragraph_index`** → rule and/or **semantic** edit (`ENABLE_SEMANTIC_EDIT_GENERATION`, `EDIT_STRATEGY`); **`ENABLE_SEMANTIC_FALLBACK_TO_RULE`** keeps strikes when the LLM edit fails validation.
   - Optional **Agent 4** (`ENABLE_AGENT4_VERIFICATION`); **`SKIP_REDLINE_WHEN_AGENT4_FLAGS`** controls whether a flag removes strikes.
   - Writes **strikethrough + underline runs** (not OOXML `w:ins`/`w:del` track changes).

**Config rollout order** is summarized in comments in **`agents/sample_agent/config.py`** (anchoring → semantic with fallback → RAG → Agent 4 advisory).

---

## Part 2: Models Used (and Whether They Are Downloaded)

The app uses **two kinds of models**. Both are intended to run **locally** (no AWS, no cloud API keys in this POC). The **code** does not download any model files; it assumes you have either started a server (Ollama) or installed a Python package that will download its own weights when first used.

---

### 2.1 Chat / Reasoning Model (LLM)

- **What the code uses**:  
  **`agents.sample_agent.config`** sets:
  - `LOCAL_LLM_MODEL` (default: **`qwen2.5:7b`**, same value for extraction / editing / classify / chat unless overridden)
  - `LOCAL_LLM_BASE_URL` (default: **`http://127.0.0.1:11434`**)

- **Where it’s used**:  
  **`agents/sample_agent/local_llm.py`** sends a POST to `{LOCAL_LLM_BASE_URL}/api/chat` with `"model": LOCAL_LLM_MODEL`. That is the **Ollama** HTTP API.

- **So the “model” here is**:  
  Whatever **Ollama** is serving at that URL with that model name (e.g. **qwen2.5:7b**). The app does not contain or download that model; **Ollama** does.

- **Have you downloaded it?**  
  **We have not downloaded it for you.** You must:
  1. Install and run **Ollama** on your machine.
  2. Run: **`ollama pull qwen2.5:7b`** (or whatever model name you set in `LOCAL_LLM_MODEL`).

  If you use a different model (e.g. `mistral`, `qwen2.5`), set **`LOCAL_LLM_MODEL`** in the environment and run **`ollama pull <that name>`**. The app will use whatever model name is in config.

---

### 2.2 Embedding Model (for RAG)

- **What the code uses**:  
  **`agents/sample_agent/config.py`** sets:
  - `LOCAL_EMBED_MODEL` (default: **`all-MiniLM-L6-v2`**)
  - `LOCAL_EMBED_BASE_URL` (default: empty), so the code uses the **sentence-transformers** path, not a remote server.

- **Where it’s used**:  
  **`agents/sample_agent/rag.py`** calls **`SentenceTransformer(agent_config.LOCAL_EMBED_MODEL)`**. That is the **sentence-transformers** library; the first time you call it with `all-MiniLM-L6-v2`, the library will **download** that model from the Hugging Face Hub (or cache) and cache it locally.

- **So the “model” here is**:  
  The **sentence-transformers** model named **`all-MiniLM-L6-v2`** (or whatever you set in `LOCAL_EMBED_MODEL`). It runs **in the same process** as Django; no separate server is required.

- **Have you downloaded it?**  
  **Not by us.** The **sentence-transformers** package will download the weights the **first time** you trigger RAG (e.g. first time you ask a question that calls `rag.ensure_poc_indexed()` or `rag.retrieve()`). So:
  - If you have not run the app yet, or have not asked a question that hits RAG, the embedding model is **not** downloaded yet.
  - As soon as RAG runs, `SentenceTransformer("all-MiniLM-L6-v2")` will trigger the library’s download (if not already in cache). That download is done by the library, not by our code.

  You can pre-download it in Python if you want:
  ```bash
  python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
  ```

---

### 2.3 Summary Table (Models)

| Role | Model / server | Where configured | Who downloads / runs it |
|------|----------------|------------------|--------------------------|
| **Chat (LLM)** | Ollama model, e.g. **qwen2.5:7b** | `config.py`: `LOCAL_LLM_MODEL`, `LOCAL_LLM_BASE_URL` | **You**: install Ollama, run `ollama pull qwen2.5:7b` (or your chosen model). The app does not download it. |
| **Embeddings (RAG)** | **all-MiniLM-L6-v2** (sentence-transformers) | `config.py`: `LOCAL_EMBED_MODEL` | **sentence-transformers** downloads it on first use (or you can run the one-liner above). We do not ship or download it in the repo. |

So:

- **LLM**: You must have **Ollama** running and the chosen model **pulled** (e.g. **qwen2.5:7b**). If not, the app will show an error when you send a message (e.g. “Local LLM unreachable”).
- **Embeddings**: **sentence-transformers** will download **all-MiniLM-L6-v2** the first time RAG is used, unless it’s already in the library’s cache.

No model files are stored in this repository; the project only contains configuration (env/defaults) and code that calls Ollama and sentence-transformers.
