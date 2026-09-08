#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Ambiente Python ausente. Rode: make setup"
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm ausente. Instale Node 20+ para executar o frontend."
  exit 1
fi
if [[ ! -d "$PROJECT_ROOT/frontend/node_modules" ]]; then
  echo "Dependências do frontend ausentes. Rode: cd frontend && npm install"
  exit 1
fi

mkdir -p "$PROJECT_ROOT/.run" "$PROJECT_ROOT/runtime"
cd "$PROJECT_ROOT/api-tractian/api"
"$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$PROJECT_ROOT/.run/industrial.log" 2>&1 &
INDUSTRIAL_PID=$!
cd "$PROJECT_ROOT"
PYTHONPATH=backend/src "$PYTHON_BIN" -m uvicorn tractian_agent.api.main:app --host 127.0.0.1 --port 8001 > "$PROJECT_ROOT/.run/backend.log" 2>&1 &
BACKEND_PID=$!

cleanup() {
  kill "$INDUSTRIAL_PID" "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Industrial : http://127.0.0.1:8000/docs"
echo "Backend    : http://127.0.0.1:8001/docs"
echo "Frontend   : http://127.0.0.1:5173"
cd "$PROJECT_ROOT/frontend"
npm run dev

