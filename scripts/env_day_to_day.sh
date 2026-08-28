# Day-to-day environment for Contract Analyzer + Celery + local LLM.
# Usage (from repo root):
#   source scripts/env_day_to_day.sh
#
# Then run Redis (if not already), Celery worker, and Django in separate terminals.

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-geg_guru.settings}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-dev-day-to-day-not-for-production}"
export HOST="${HOST:-127.0.0.1}"

export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$CELERY_BROKER_URL}"
export CELERY_TASK_ALWAYS_EAGER="${CELERY_TASK_ALWAYS_EAGER:-0}"

# Async “Analyze clauses” (polls /api/analysis/jobs/…/) — needs a Celery worker.
export ENABLE_ASYNC_CONTRACT_ANALYSIS="${ENABLE_ASYNC_CONTRACT_ANALYSIS:-1}"

# Local Ollama (already running as a service on many Mac installs).
export LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://127.0.0.1:11434}"
export LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-llama3.1:8b}"

# Microsoft SSO — only required if ENFORCE_GLOBAL_LOGIN=1
export AZURE_CLIENT_ID="${AZURE_CLIENT_ID:-}"
export AZURE_TENANT_ID="${AZURE_TENANT_ID:-}"
export AZURE_CLIENT_SECRET="${AZURE_CLIENT_SECRET:-}"
export ENFORCE_GLOBAL_LOGIN="${ENFORCE_GLOBAL_LOGIN:-0}"
