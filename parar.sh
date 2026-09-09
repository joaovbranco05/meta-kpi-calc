#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

API_PID_FILE="$ROOT_DIR/.logs/uvicorn.pid"
STREAMLIT_PID_FILE="$ROOT_DIR/.logs/streamlit.pid"

stop_pid() {
  local pid_file="$1"
  local label="$2"

  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      echo "$label parado (PID $pid)."
    else
      echo "$label não estava em execução."
    fi
    rm -f "$pid_file"
  else
    echo "$label não possui PID registrado."
  fi
}

stop_pid "$API_PID_FILE" "Uvicorn"
stop_pid "$STREAMLIT_PID_FILE" "Streamlit"

echo "Tudo encerrado."
