# POC Agent – Local development setup

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Local LLM (Ollama)

The agent uses a local LLM only (no AWS).

1. Install [Ollama](https://ollama.com) and start it.
2. Pull a model, e.g.:
   ```bash
   ollama pull llama3.1:8b
   ```
3. Optional env overrides (defaults shown):
   ```bash
   export LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
   export LOCAL_LLM_MODEL=llama3.1:8b
   ```
4. Deployment-ready optional Bedrock settings are present in code but **disabled by default**:
   ```bash
   export LLM_PROVIDER=local      # default
   export ENABLE_BEDROCK=0        # default
   # Optional for deployment when you choose to enable Bedrock:
   # export LLM_PROVIDER=bedrock
   # export ENABLE_BEDROCK=1
   # export AWS_REGION=ap-south-1
   # export AWS_ACCESS_KEY_ID=...
   # export AWS_SECRET_ACCESS_KEY=...
   # export BEDROCK_MODEL_ID=arn:aws:bedrock:...
   ```

## 3. Run the app

Use the same Python that has the installed packages (if `python` is conda and Django is elsewhere, use `python3`):

```bash
python3 manage.py migrate
python3 manage.py runserver 127.0.0.1:8501
```

Open http://127.0.0.1:8501 . Use **Home** in the sidebar to see the dashboard, then **Aerospace → Contract Analyzer** to open the POC agent. Upload documents and ask questions; the agent will use the local model.

## 4. RAG (POC knowledge)

The agent uses the POC clause document for context. Install RAG deps:

```bash
pip install sentence-transformers numpy
```

Keep the GB Legal POC positions file on your machine (not in git). The app default is the DOCX under `docs/knowledge/` if present, otherwise the JSON fallback. Set `POC_KNOWLEDGE_PATH` if the file lives elsewhere.

Optional env:

- `POC_KNOWLEDGE_PATH` – path to the local POC clause document
- `LOCAL_EMBED_MODEL` – e.g. `all-MiniLM-L6-v2` (sentence-transformers)
- `RAG_TOP_K` – number of chunks to retrieve (default: 8)
- `ENABLE_RAG` – set `1` to use embedding retrieval from the POC knowledge JSON and uploaded files; default is `1` (on)
- `ENABLE_VECTOR_RETRIEVER` – set `1` to enable vector retrieval backend. Default `0` (stable direct document+knowledge comparison mode without vector DB locks)
- `INDEX_UPLOAD_ON_UPLOAD` – set `1` to index uploads immediately on upload; default is `0` (deferred indexing on first ask, prevents upload request hangs)
- `DEBUG_AGENT` – set `1` to enable backend debug logs for model calls, upload parsing, prompt/context building, and counterfactual parsing

Replies show the main answer in the chat bubble and **Counterfactuals** in a separate green block below when the model outputs them.

## 5. Generate reviewed DOCX (redline output)

After running analysis in **Aerospace -> Contract Analyzer**:

1. Click **Generate Reviewed DOCX**.
2. App creates `reviewed_contract.docx` under the current session folder:
   - `media/custom_dev_sample_agent/<session_key>/reviewed_contract.docx`
3. Use the success panel link to download the file.

Document contents:
- original clause text excerpt,
- redline edits (deleted = strikethrough, inserted = underline),
- legal comments (policy deviation and counterfactual risk) as Word comments when supported.

### Test input

Upload a contract from your local machine. Sample and appendix documents are not stored in this repository.
