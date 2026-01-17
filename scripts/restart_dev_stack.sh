#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

export PYTHONPATH="$ROOT_DIR"
export no_proxy="localhost,127.0.0.1${no_proxy:+,$no_proxy}"

LOG_DIR="$ROOT_DIR/logs/dev"
mkdir -p "$LOG_DIR"

kill_pidfile() {
  local pidfile="$1"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]]; then
      if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping PID $pid ($pidfile)"
        kill "$pid" 2>/dev/null || true
        sleep 0.5
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pidfile" || true
  fi
}

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -n "${pids:-}" ]]; then
    echo "Stopping processes on port $port: $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}

echo "==> Stopping existing processes"
kill_pidfile "$LOG_DIR/frontend.pid"
kill_pidfile "$LOG_DIR/backend.pid"
kill_pidfile "$LOG_DIR/qindex_worker.pid"
kill_pidfile "$LOG_DIR/grade_worker.pid"
kill_pidfile "$LOG_DIR/facts_worker.pid"
kill_pidfile "$LOG_DIR/report_worker.pid"

kill_port 5173
kill_port 8000

pkill -f "homework_agent.workers.qindex_worker" 2>/dev/null || true
pkill -f "homework_agent.workers.grade_worker" 2>/dev/null || true
pkill -f "homework_agent.workers.facts_worker" 2>/dev/null || true
pkill -f "homework_agent.workers.report_worker" 2>/dev/null || true
pkill -f "uvicorn homework_agent.main:app" 2>/dev/null || true

sleep 0.8

start_bg() {
  local name="$1"
  local logfile="$2"
  local pidfile="$3"
  shift 3

  echo "==> Starting $name"
  echo "  log: $logfile"
  # shellcheck disable=SC2086
  nohup "$@" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
  echo "  pid: $(cat "$pidfile")"
}

start_bg "backend" "$LOG_DIR/backend.log" "$LOG_DIR/backend.pid" \
  "$ROOT_DIR/.venv/bin/uvicorn" homework_agent.main:app --host 127.0.0.1 --port 8000 --reload

start_bg "qindex_worker" "$LOG_DIR/qindex_worker.log" "$LOG_DIR/qindex_worker.pid" \
  "$ROOT_DIR/.venv/bin/python" -m homework_agent.workers.qindex_worker

start_bg "grade_worker" "$LOG_DIR/grade_worker.log" "$LOG_DIR/grade_worker.pid" \
  "$ROOT_DIR/.venv/bin/python" -m homework_agent.workers.grade_worker

start_bg "facts_worker" "$LOG_DIR/facts_worker.log" "$LOG_DIR/facts_worker.pid" \
  "$ROOT_DIR/.venv/bin/python" -m homework_agent.workers.facts_worker

start_bg "report_worker" "$LOG_DIR/report_worker.log" "$LOG_DIR/report_worker.pid" \
  "$ROOT_DIR/.venv/bin/python" -m homework_agent.workers.report_worker

start_bg "frontend" "$LOG_DIR/frontend.log" "$LOG_DIR/frontend.pid" \
  npm --prefix "$ROOT_DIR/homework_frontend" run dev -- --host 127.0.0.1 --port 5173

echo
echo "Done."
echo "Frontend: http://127.0.0.1:5173"
echo "Backend:   http://127.0.0.1:8000"
echo "Logs:      $LOG_DIR"

