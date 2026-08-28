#!/usr/bin/env bash
# One-shot contract stack tests with DETERMINISTIC_CONTRACT_MODE=1:
# DOCX redlines use rule path only (no semantic LLM edits), Agent4 off, tighter temps.
# LLM remains used for clause extraction / Agent2–3 in the normal pipeline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export DETERMINISTIC_CONTRACT_MODE=1
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-geg_guru.settings}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY="python3"; fi
echo "Using python: $PY"
"$PY" -m pytest \
  agents/sample_agent/tests/test_redline_anchoring.py \
  agents/sample_agent/tests/test_redline_hitl_export.py \
  agents/sample_agent/tests/test_master_orchestrator.py \
  agents/sample_agent/tests/test_referenced_doc_upload_match.py \
  agents/sample_agent/tests/test_rehydrate_session.py \
  agents/sample_agent/tests/test_supervisor_hitl_stub.py \
  -q
echo "OK — deterministic preset tests passed."
