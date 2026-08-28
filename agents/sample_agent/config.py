"""Runtime config for the POC agent.

Default mode is local-only. Bedrock settings are present for future deployment
but are disabled by default.
"""

from __future__ import annotations

import os
from pathlib import Path

# Local LLM (e.g. Ollama)
# ---------------------------------------------------------------------------
# Default "classic POC" preset: one model id for every role unless you set
# per-role env vars. Override LOCAL_LLM_MODEL only (e.g. mistral:7b-instruct).
# ---------------------------------------------------------------------------
LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "llama3.1:8b").strip()
LOCAL_LLM_MODEL_EXTRACTION = os.environ.get("LOCAL_LLM_MODEL_EXTRACTION", LOCAL_LLM_MODEL).strip()
LOCAL_LLM_MODEL_EDITING = os.environ.get("LOCAL_LLM_MODEL_EDITING", LOCAL_LLM_MODEL).strip()
LOCAL_LLM_MODEL_CLASSIFY = os.environ.get("LOCAL_LLM_MODEL_CLASSIFY", LOCAL_LLM_MODEL).strip()
LOCAL_LLM_MODEL_CHAT = os.environ.get("LOCAL_LLM_MODEL_CHAT", LOCAL_LLM_MODEL).strip()
# Tuned for concise, stable contractual outputs in local mode.
LOCAL_LLM_TEMPERATURE = float(os.environ.get("LOCAL_LLM_TEMPERATURE", "0.05"))
LOCAL_LLM_TEMPERATURE_EXTRACTION = float(os.environ.get("LOCAL_LLM_TEMPERATURE_EXTRACTION", "0.0"))
LOCAL_LLM_TEMPERATURE_CLASSIFY = float(os.environ.get("LOCAL_LLM_TEMPERATURE_CLASSIFY", "0.0"))
LOCAL_LLM_TEMPERATURE_EDITING = float(os.environ.get("LOCAL_LLM_TEMPERATURE_EDITING", "0.05"))
LOCAL_LLM_TEMPERATURE_COMMENTS = float(os.environ.get("LOCAL_LLM_TEMPERATURE_COMMENTS", "0.1"))
LOCAL_LLM_TOP_P = float(os.environ.get("LOCAL_LLM_TOP_P", "0.6"))
LOCAL_LLM_MAX_TOKENS = int(os.environ.get("LOCAL_LLM_MAX_TOKENS", "2048"))

# Provider selection: "local" (default) or "bedrock".
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "local").strip().lower()

# Optional Bedrock path (disabled by default).
ENABLE_BEDROCK = os.environ.get("ENABLE_BEDROCK", "0").strip().lower() in {"1", "true", "yes", "on"}
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "arn:aws:bedrock:ap-south-1::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0",
)

# Optional: embeddings and vector store (for RAG phase)
LOCAL_EMBED_MODEL = os.environ.get("LOCAL_EMBED_MODEL", "nomic-embed-text")
LOCAL_EMBED_BASE_URL = os.environ.get("LOCAL_EMBED_BASE_URL", LOCAL_LLM_BASE_URL)  # Ollama embeddings by default

_def_docx = Path(__file__).resolve().parents[2] / "docs" / "knowledge" / "[RFP Tenders-LTAs] Contract Positions for POC_GB Legal_2026.02.19-v1.docx"
_def_json = Path(__file__).resolve().parents[2] / "docs" / "knowledge" / "Contract_Positions_POC_GB_Legal_2026-02-19.json"
POC_KNOWLEDGE_PATH = os.environ.get(
    "POC_KNOWLEDGE_PATH",
    str(_def_docx if _def_docx.exists() else _def_json),
)
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "12"))
# Rerank bi-encoder retrieval with a cross-encoder (sentence-transformers). On by default; set to 0 to skip.
ENABLE_RAG_CROSS_ENCODER_RERANK = os.environ.get(
    "ENABLE_RAG_CROSS_ENCODER_RERANK", "1"
).strip().lower() in {"1", "true", "yes", "on"}
RAG_CROSS_ENCODER_MODEL = os.environ.get(
    "RAG_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
).strip()
RAG_RERANK_CANDIDATE_POOL = int(os.environ.get("RAG_RERANK_CANDIDATE_POOL", "32"))
# Default cpu: Celery prefork + Apple MPS often SIGABRT; use cuda/mps in thread/solo pools if you want.
_cross_dev = (os.environ.get("CROSS_ENCODER_DEVICE", "cpu").strip().lower() or "cpu")
CROSS_ENCODER_DEVICE = _cross_dev if _cross_dev in ("cpu", "cuda", "mps") else "cpu"
# Agent 1 aerospace sentence shortlist: optional second-stage rerank (same stack as RAG). Off by default.
ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK = os.environ.get(
    "ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK", "0"
).strip().lower() in {"1", "true", "yes", "on"}
EVIDENCE_CROSS_ENCODER_MODEL = (
    os.environ.get("EVIDENCE_CROSS_ENCODER_MODEL", "").strip() or RAG_CROSS_ENCODER_MODEL
)
# Air-gapped or no sentence-transformers: set ENABLE_RAG_CROSS_ENCODER_RERANK=0 and ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK=0.
# Per-clause retrieval merged into Agent 1 evidence text (session uploads + POC index).
# Off by default (classic POC): avoids embeddings + chunk drift that breaks DOCX matching.
ENABLE_AGENT1_RAG_CONTEXT = os.environ.get("ENABLE_AGENT1_RAG_CONTEXT", "1").strip().lower() in {"1", "true", "yes", "on"}
AGENT1_RAG_TOP_K = int(os.environ.get("AGENT1_RAG_TOP_K", "12"))
AGENT1_RAG_MAX_CHARS = int(os.environ.get("AGENT1_RAG_MAX_CHARS", "6000"))
ENABLE_RAG = os.environ.get("ENABLE_RAG", "1").strip().lower() in {"1", "true", "yes", "on"}
INDEX_UPLOAD_ON_UPLOAD = os.environ.get("INDEX_UPLOAD_ON_UPLOAD", "1").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_VECTOR_RETRIEVER = os.environ.get("ENABLE_VECTOR_RETRIEVER", "1").strip().lower() in {"1", "true", "yes", "on"}
DEBUG_AGENT = os.environ.get("DEBUG_AGENT", "0").strip().lower() in {"1", "true", "yes", "on"}
# When set (or DEBUG_AGENT=1), master_orchestrator logs per-role model roster at analysis + DOCX export.
MASTER_ORCHESTRATOR_LOG = os.environ.get("MASTER_ORCHESTRATOR_LOG", "0").strip().lower() in {"1", "true", "yes", "on"}

# Agent 4: post-redline verification (extra LLM call). On by default; advisory when SKIP_REDLINE_WHEN_AGENT4_FLAGS=0.
ENABLE_AGENT4_VERIFICATION = os.environ.get("ENABLE_AGENT4_VERIFICATION", "1").strip().lower() in {"1", "true", "yes", "on"}
# When Agent 4 flags an edit as problematic, skip applying the redline.
SKIP_REDLINE_WHEN_AGENT4_FLAGS = os.environ.get("SKIP_REDLINE_WHEN_AGENT4_FLAGS", "0").strip().lower() in {"1", "true", "yes", "on"}

# Semantic LLM rewrites on export (rule_first keeps deterministic edits first).
ENABLE_SEMANTIC_EDIT_GENERATION = os.environ.get("ENABLE_SEMANTIC_EDIT_GENERATION", "1").strip().lower() in {"1", "true", "yes", "on"}
# rule_first matches semantic-off behavior; semantic_first only matters when semantic edits are on.
EDIT_STRATEGY = os.environ.get("EDIT_STRATEGY", "rule_first").strip().lower()  # or "semantic_first"
# If an LLM-produced edit fails export validators, fall back to rule-based edit so the DOCX still redlines.
ENABLE_SEMANTIC_FALLBACK_TO_RULE = os.environ.get("ENABLE_SEMANTIC_FALLBACK_TO_RULE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# --- LLM rollout (re-enable features in this order for stable exports) ---
# 1) Anchoring: table flatten + Unicode tokens in redline_docx (always on in code).
# 2) ENABLE_SEMANTIC_EDIT_GENERATION=1 with EDIT_STRATEGY=rule_first (LLM only when rules make no change).
# 3) ENABLE_SEMANTIC_FALLBACK_TO_RULE=1 (default): invalid LLM edit → still apply rule redline.
# 4) ENABLE_RAG=1 + ENABLE_AGENT1_RAG_CONTEXT=1 (optional; ENABLE_EVIDENCE_DOC_ALIGNMENT helps export match).
#    RAG cross-encoder rerank defaults on (ENABLE_RAG_CROSS_ENCODER_RERANK=1); sentence rerank stays opt-in.
#    Or set ANALYZER_PRESET=structured to turn on sentence rerank + align flags in one shot (see config bottom).
# 5) ENABLE_AGENT4_VERIFICATION=1 with SKIP_REDLINE_WHEN_AGENT4_FLAGS=0 (advisory, non-blocking).
# Evidence-to-clause validation (optional LLM): default off.
ENABLE_EVIDENCE_CLAUSE_VALIDATION = os.environ.get("ENABLE_EVIDENCE_CLAUSE_VALIDATION", "0").strip().lower() in {"1", "true", "yes", "on"}

ENABLE_EVIDENCE_DOC_ALIGNMENT = os.environ.get("ENABLE_EVIDENCE_DOC_ALIGNMENT", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Parallel redline flow: Phase 1–3 run in parallel (ThreadPoolExecutor), Phase 4 applies sequentially.
# Default False to avoid breaking existing flow.
ENABLE_PARALLEL_REDLINE = os.environ.get("ENABLE_PARALLEL_REDLINE", "0").strip().lower() in {"1", "true", "yes", "on"}
# Semantic margin comments: off by default (no extra LLM on export).
ENABLE_SEMANTIC_COMMENTS = os.environ.get("ENABLE_SEMANTIC_COMMENTS", "0").strip().lower() in ("1", "true", "yes", "on")
# Edit semantic validation: LLM verifies edit preserves legal intent before applying (default: 0, adds extra LLM call).
ENABLE_EDIT_SEMANTIC_VALIDATION = os.environ.get("ENABLE_EDIT_SEMANTIC_VALIDATION", "0").strip().lower() in ("1", "true", "yes", "on")

# LangGraph wraps Agent1→2→3 only; DOCX redlines still come from redline_docx (see langgraph_pipeline docstring).
ENABLE_LANGGRAPH = os.environ.get("ENABLE_LANGGRAPH", "0").strip().lower() in {"1", "true", "yes", "on"}
# In-repo GraphRAG-lite (entity–chunk graph over primary + supporting text). Feeds Agent 2 only; off by default.
ENABLE_GRAPHRAG = os.environ.get("ENABLE_GRAPHRAG", "0").strip().lower() in {"1", "true", "yes", "on"}
GRAPHRAG_MAX_CHARS = int(os.environ.get("GRAPHRAG_MAX_CHARS", "3500"))

# Executive read: bounded JSON (risk / gap / proposal / clearance) + paragraph index for anchoring.
ENABLE_EXECUTIVE_READ = os.environ.get("ENABLE_EXECUTIVE_READ", "1").strip().lower() in {"1", "true", "yes", "on"}
EXECUTIVE_READ_MAX_CLAUSES = int(os.environ.get("EXECUTIVE_READ_MAX_CLAUSES", "10"))
# Set to 0 to force deterministic table-only executive read (no extra LLM call).
ENABLE_EXECUTIVE_READ_LLM = os.environ.get("ENABLE_EXECUTIVE_READ_LLM", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# DOCX body redlines (strike/underline) on export — disabled in product UI by default; code remains in
# chat_agent.generate_reviewed_contract_docx / redline_docx. Set ENABLE_REDLINE_DOCX_EXPORT=1 to restore.
ENABLE_REDLINE_DOCX_EXPORT = os.environ.get(
    "ENABLE_REDLINE_DOCX_EXPORT", "0"
).strip().lower() in {"1", "true", "yes", "on"}

# Primary contract DOCX with Word comments (contract vs GB ideal vs supporting) — no body strike/underline.
# Independent of ENABLE_REDLINE_DOCX_EXPORT so Legal can receive an annotated file when redlines are off.
ENABLE_CONTRACT_COMMENTARY_DOCX = os.environ.get(
    "ENABLE_CONTRACT_COMMENTARY_DOCX", "1"
).strip().lower() in {"1", "true", "yes", "on"}
# Word commentary export body:
# - counsel_bubble (default): deduplicated anchor + brief + compact analysis record (counsel-first).
# - full: legacy verbose anchor + analysis blocks with cross-read excerpts.
# - counsel_short: minimal analysis summary for tight Word limits.
CONTRACT_COMMENTARY_EXPORT_STYLE = os.environ.get("CONTRACT_COMMENTARY_EXPORT_STYLE", "counsel_bubble").strip().lower()

# DOCX export: only apply body redlines for clause rows the user explicitly selected (session).
# Set REQUIRE_REDLINE_HITL_ACCEPTANCE=0 to restore legacy "export applies all suggested edits".
REQUIRE_REDLINE_HITL_ACCEPTANCE = os.environ.get(
    "REQUIRE_REDLINE_HITL_ACCEPTANCE", "1"
).strip().lower() in {"1", "true", "yes", "on"}

# When True, Contract Analyzer can enqueue analysis to Celery and poll job status (see workspace JS).
ENABLE_ASYNC_CONTRACT_ANALYSIS = os.environ.get(
    "ENABLE_ASYNC_CONTRACT_ANALYSIS", "0"
).strip().lower() in {"1", "true", "yes", "on"}

# Optional: second HITL pipeline (hitl_orchestrator) calls local LLM for JSON suggestions during async job trace.
ENABLE_HITL_PIPELINE_LLM = os.environ.get(
    "ENABLE_HITL_PIPELINE_LLM", "0"
).strip().lower() in {"1", "true", "yes", "on"}

# ---------------------------------------------------------------------------
# Deterministic-first preset (single switch)
# ---------------------------------------------------------------------------
# When DETERMINISTIC_CONTRACT_MODE=1: keep LLM for clause extraction / Agent2–3 where enabled, but
# force DOCX body edits onto the rule path (no semantic LLM rewrites on export), disable Agent 4 and
# other optional LLM export gates, and tighten sampling (lower temperature / top_p).
_deterministic = os.environ.get("DETERMINISTIC_CONTRACT_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
if _deterministic:
    ENABLE_SEMANTIC_EDIT_GENERATION = False
    ENABLE_AGENT4_VERIFICATION = False
    ENABLE_EDIT_SEMANTIC_VALIDATION = False
    ENABLE_SEMANTIC_COMMENTS = False
    ENABLE_LANGGRAPH = False
    ENABLE_GRAPHRAG = False
    ENABLE_HITL_PIPELINE_LLM = False
    ENABLE_EXECUTIVE_READ_LLM = False
    ENABLE_REDLINE_DOCX_EXPORT = False
    EDIT_STRATEGY = "rule_first"
    LOCAL_LLM_TOP_P = min(float(LOCAL_LLM_TOP_P), 0.25)
    LOCAL_LLM_TEMPERATURE = min(float(LOCAL_LLM_TEMPERATURE), 0.02)
    LOCAL_LLM_TEMPERATURE_EDITING = 0.0
    LOCAL_LLM_TEMPERATURE_COMMENTS = 0.0
elif os.environ.get("ANALYZER_PRESET", "").strip().lower() in {"structured", "structured_deterministic"}:
    # Rule-first edits + RAG/cross-encoder curation + optional sentence rerank for evidence (not full DETERMINISTIC_CONTRACT_MODE).
    EDIT_STRATEGY = "rule_first"
    ENABLE_SEMANTIC_EDIT_GENERATION = True
    ENABLE_SEMANTIC_FALLBACK_TO_RULE = True
    ENABLE_RAG = True
    ENABLE_AGENT1_RAG_CONTEXT = True
    ENABLE_RAG_CROSS_ENCODER_RERANK = True
    ENABLE_EVIDENCE_SENTENCE_CROSS_ENCODER_RERANK = True
    ENABLE_EVIDENCE_DOC_ALIGNMENT = True
    ENABLE_SEMANTIC_COMMENTS = False
    ENABLE_EDIT_SEMANTIC_VALIDATION = False
