#!/usr/bin/env bash
# Start Ollama (models on external drive) + Django dev server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
source "$ROOT/scripts/ollama_contract_agent_env.sh"

if [[ ! -d "$OLLAMA_MODELS/manifests" ]]; then
  echo "Ollama models not found at: $OLLAMA_MODELS" >&2
  echo "Mount the pendrive (expected: /Volumes/ATH) or set OLLAMA_MODELS." >&2
  exit 1
fi

if ! curl -sf "${LOCAL_LLM_BASE_URL}/api/tags" >/dev/null 2>&1; then
  echo "Starting Ollama with OLLAMA_MODELS=$OLLAMA_MODELS …"
  OLLAMA_MODELS="$OLLAMA_MODELS" ollama serve >/tmp/ollama-serve.log 2>&1 &
  OLLAMA_PID=$!
  for _ in $(seq 1 30); do
    if curl -sf "${LOCAL_LLM_BASE_URL}/api/tags" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "${LOCAL_LLM_BASE_URL}/api/tags" >/dev/null 2>&1; then
    echo "Ollama failed to start. See /tmp/ollama-serve.log" >&2
    exit 1
  fi
  echo "Ollama ready (pid ${OLLAMA_PID:-unknown})."
else
  echo "Ollama already running at ${LOCAL_LLM_BASE_URL}."
fi

echo "Available models:"
ollama list

PORT="${PORT:-8501}"
echo "Starting Django on http://127.0.0.1:${PORT} …"
exec "$ROOT/.venv/bin/python" manage.py runserver "127.0.0.1:${PORT}"
