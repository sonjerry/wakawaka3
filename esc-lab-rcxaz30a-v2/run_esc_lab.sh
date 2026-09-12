#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if pgrep -f "raspberry_pi/main.py" >/dev/null 2>&1; then
  echo "[ESC-LAB] Normal RC server is running. Stop scripts/run_pi.sh first."
  exit 1
fi

PROJECT_ROOT="$(cd "$ROOT/.." && pwd)"
if [ -x "$PROJECT_ROOT/.venv-pi/bin/python" ]; then
  PY="$PROJECT_ROOT/.venv-pi/bin/python"
elif [ -x "$HOME/repos/wakawaka3/.venv-pi/bin/python" ]; then
  PY="$HOME/repos/wakawaka3/.venv-pi/bin/python"
else
  PY="python3"
fi

IP="$(hostname -I | awk '{print $1}')"
echo "[ESC-LAB] Open: http://${IP}:8770"
exec "$PY" tools/esc_lab.py
