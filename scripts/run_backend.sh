#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export PYTHONPATH="$ROOT_DIR"

# Avoid local proxy interfering with local API calls.
export no_proxy="localhost,127.0.0.1${no_proxy:+,$no_proxy}"

mkdir -p logs

echo "Starting backend (uvicorn) on http://127.0.0.1:8000"
echo "Logging to: $ROOT_DIR/logs/backend.log"
echo "Tip: grep '\"request_id\":\"' logs/backend.log | tail"

exec .venv/bin/uvicorn homework_agent.main:app --host 127.0.0.1 --port 8000 --reload
