# Deployment notes — Contract Analyzer (Amethyst-aligned)

## Environment variables (LLM / RAG)

| Variable | Purpose |
|----------|---------|
| `LOCAL_LLM_MODEL` | Default chat model when per-role vars unset |
| `LOCAL_LLM_MODEL_EXTRACTION` | Agent 1 structured extraction |
| `LOCAL_LLM_MODEL_EDITING` | Semantic paragraph edits (`semantic_edit_generator`) |
| `LOCAL_LLM_MODEL_CLASSIFY` | Evidence validation, Agent 4 |
| `LOCAL_LLM_MODEL_CHAT` | Agent 2 **risk narrative** (not a user chat UI) |
| `LOCAL_EMBED_MODEL` | Embeddings (e.g. `nomic-embed-text` via Ollama) |
| `LOCAL_EMBED_BASE_URL` | Usually same as `LOCAL_LLM_BASE_URL` |

Defaults favor **quality-first**: Agent 1 RAG context, upload indexing, semantic edits, and Agent 4 verification are **on** unless overridden.

## Disabling heavy paths

Set any of these to `0` if embeddings or LLM export are unavailable:

- `ENABLE_AGENT1_RAG_CONTEXT`
- `ENABLE_VECTOR_RETRIEVER`
- `INDEX_UPLOAD_ON_UPLOAD`
- `ENABLE_SEMANTIC_EDIT_GENERATION`
- `ENABLE_AGENT4_VERIFICATION`

## LangGraph

`ENABLE_LANGGRAPH=1` runs the **same** Agent 1→2→3 path via `langgraph_pipeline`. **DOCX redlines always** use `redline_docx` through `generate_reviewed_contract_docx`, not the graph.

## Scaling beyond 10 POC positions (200+)

1. Extend the knowledge payload (`clauses` array in JSON / DOCX-derived loader) with additional rows.
2. Adjust Agent 1 clause inventory / keywords if code lists diverge from knowledge (see `agent1_clause_analyzer.py`).
3. Expect longer runs; raise `AGENT1_RAG_TOP_K` / `AGENT1_RAG_MAX_CHARS` only within hardware limits.
4. When session indexes exceed comfortable RAM, plan migration to **Postgres + pgvector** or **LanceDB** (see architecture docs).

## Vector store at enterprise scale

The bundled `rag.py` store is **in-memory** per process — sufficient for session-scale uploads. For **Vault-scale** corpora (thousands of documents), replace retrieval with a hosted vector database and tenant isolation as described in product architecture reviews.
