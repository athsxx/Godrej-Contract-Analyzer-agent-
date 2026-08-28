#!/usr/bin/env bash
# Ollama model map for this machine (generated from `ollama list` on 2026-05-05).
# Models present: llama3.1:8b, mistral:7b-instruct, org/qwen2.5-1m:7b, llama3.2:latest,
#                 qwen2.5:3b, nomic-embed-text:latest
#
# Usage (current shell only):
#   source scripts/ollama_contract_agent_env.sh
#
# Django / pytest inherit env from the shell you start them from.

# External pendrive Ollama store (override with OLLAMA_MODELS if mounted elsewhere).
export OLLAMA_MODELS="${OLLAMA_MODELS:-/Volumes/ATH/ollama-models}"

export LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434}"

# Default when code does not pass a per-role override
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-llama3.1:8b}"

# Accuracy-first split: long-context read, strong instruct edit, lighter verify, stable chat
export LOCAL_LLM_MODEL_EXTRACTION="${LOCAL_LLM_MODEL_EXTRACTION:-org/qwen2.5-1m:7b}"
export LOCAL_LLM_MODEL_EDITING="${LOCAL_LLM_MODEL_EDITING:-mistral:7b-instruct}"
export LOCAL_LLM_MODEL_CLASSIFY="${LOCAL_LLM_MODEL_CLASSIFY:-llama3.2:latest}"
export LOCAL_LLM_MODEL_CHAT="${LOCAL_LLM_MODEL_CHAT:-llama3.1:8b}"

# Embeddings (RAG / Agent1 context) — match installed tag
export LOCAL_EMBED_MODEL="${LOCAL_EMBED_MODEL:-nomic-embed-text:latest}"
export LOCAL_EMBED_BASE_URL="${LOCAL_EMBED_BASE_URL:-$LOCAL_LLM_BASE_URL}"

# Optional: log master orchestrator roster without full DEBUG_AGENT
export MASTER_ORCHESTRATOR_LOG="${MASTER_ORCHESTRATOR_LOG:-1}"

# LangGraph (Agent1→2→3 graph) and GraphRAG-lite (cross-doc context for Agent 2)
export ENABLE_LANGGRAPH="${ENABLE_LANGGRAPH:-1}"
export ENABLE_GRAPHRAG="${ENABLE_GRAPHRAG:-1}"

# If org/qwen2.5-1m:7b is slow or OOM on extraction, switch to:
#   export LOCAL_LLM_MODEL_EXTRACTION=llama3.1:8b
# For fastest classification only:
#   export LOCAL_LLM_MODEL_CLASSIFY=qwen2.5:3b
