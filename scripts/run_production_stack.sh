#!/usr/bin/env bash
# Run Django (Gunicorn) + Celery with env vars set. Requires: Redis on 6379, Ollama (optional for LLM).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv"
if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Create venv first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn" >&2
  exit 1
fi
PY="${VENV}/bin/python"
PIP="${VENV}/bin/pip"

# --- Django / security ---
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-geg_guru.settings}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$($PY -c 'import secrets; print(secrets.token_urlsafe(50))')}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-0}"
export HOST="${HOST:-127.0.0.1}"

# --- Celery / Redis ---
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$CELERY_BROKER_URL}"
export CELERY_TASK_ALWAYS_EAGER="${CELERY_TASK_ALWAYS_EAGER:-0}"

# --- Contract analyzer (async jobs) ---
export ENABLE_ASYNC_CONTRACT_ANALYSIS="${ENABLE_ASYNC_CONTRACT_ANALYSIS:-1}"

# --- Local LLM (Ollama) ---
export LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434}"
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-llama3.1:8b}"

# --- Microsoft SSO (override if you enforce login) ---
export AZURE_CLIENT_ID="${AZURE_CLIENT_ID:-}"
export AZURE_TENANT_ID="${AZURE_TENANT_ID:-}"
export AZURE_CLIENT_SECRET="${AZURE_CLIENT_SECRET:-}"

if ! redis-cli ping >/dev/null 2>&1; then
  echo "Warning: Redis not responding to 'redis-cli ping' — start Redis on 127.0.0.1:6379 (e.g. redis-server or docker run -p 6379:6379 redis:7-alpine)." >&2
fi

"$PIP" install -q gunicorn whitenoise markdown bleach >/dev/null 2>&1 || true

"$PY" manage.py migrate --noinput
"$PY" manage.py collectstatic --noinput

cleanup() {
  if [[ -n "${CELERY_PID:-}" ]] && kill -0 "$CELERY_PID" 2>/dev/null; then
    kill "$CELERY_PID" 2>/dev/null || true
    wait "$CELERY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting Celery worker…"
"${VENV}/bin/celery" -A geg_guru worker -l info --concurrency=2 &
CELERY_PID=$!

BIND="${BIND:-0.0.0.0:8000}"
echo "Starting Gunicorn on http://${BIND/0.0.0.0/127.0.0.1} (bind $BIND)…"
exec "${VENV}/bin/gunicorn" geg_guru.wsgi:application \
  --bind "$BIND" \
  --workers "${WORKERS:-4}" \
  --threads "${THREADS:-2}" \
  --timeout "${TIMEOUT:-120}" \
  --access-logfile - \
  --error-logfile -
