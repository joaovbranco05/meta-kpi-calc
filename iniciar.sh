#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p "$ROOT_DIR/.logs"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source "$ROOT_DIR/.venv/bin/activate"
elif ! command -v uvicorn >/dev/null 2>&1 || ! command -v streamlit >/dev/null 2>&1; then
  echo "Ambiente virtual não encontrado em .venv e os comandos uvicorn/streamlit não estão no PATH."
  echo "Crie o ambiente com:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  python -m pip install --upgrade pip"
  echo "  python -m pip install -r requirements.txt"
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v uvicorn >/dev/null 2>&1; then
  echo "Comando uvicorn não encontrado no ambiente atual."
  exit 1
fi

if ! command -v streamlit >/dev/null 2>&1; then
  echo "Comando streamlit não encontrado no ambiente atual."
  exit 1
fi

API_LOG="$ROOT_DIR/.logs/uvicorn.log"
STREAMLIT_LOG="$ROOT_DIR/.logs/streamlit.log"
API_PID_FILE="$ROOT_DIR/.logs/uvicorn.pid"
STREAMLIT_PID_FILE="$ROOT_DIR/.logs/streamlit.pid"

if [ -f "$API_PID_FILE" ] && kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
  echo "API já está em execução (PID $(cat "$API_PID_FILE"))."
else
  nohup uvicorn meta_kpi_calc.api.app:app --app-dir src --host 127.0.0.1 --port 8000 >"$API_LOG" 2>&1 &
  echo $! > "$API_PID_FILE"
  echo "API iniciada em http://127.0.0.1:8000"
fi

if [ -f "$STREAMLIT_PID_FILE" ] && kill -0 "$(cat "$STREAMLIT_PID_FILE")" 2>/dev/null; then
  echo "Streamlit já está em execução (PID $(cat "$STREAMLIT_PID_FILE"))."
else
  nohup streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 >"$STREAMLIT_LOG" 2>&1 &
  echo $! > "$STREAMLIT_PID_FILE"
  echo "Streamlit iniciado em http://127.0.0.1:8501"
fi

echo
printf 'Logs:\n  API: %s\n  Streamlit: %s\n' "$API_LOG" "$STREAMLIT_LOG"
printf 'PIDs:\n  API: %s\n  Streamlit: %s\n' "$(cat "$API_PID_FILE")" "$(cat "$STREAMLIT_PID_FILE")"

echo
printf 'Para parar os serviços:\n  kill $(cat %s) $(cat %s)\n' "$API_PID_FILE" "$STREAMLIT_PID_FILE"
