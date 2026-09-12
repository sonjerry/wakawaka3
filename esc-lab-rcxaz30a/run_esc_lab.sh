#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if pgrep -f "raspberry_pi/main.py" >/dev/null 2>&1; then
  echo "[ESC-LAB] raspberry_pi/main.py is running."
  echo "[ESC-LAB] Stop the normal RC project first."
  exit 1
fi

if [ -x ".venv-pi/bin/python" ]; then
  PY=".venv-pi/bin/python"
elif [ -x "$HOME/repos/wakawaka3/.venv-pi/bin/python" ]; then
  PY="$HOME/repos/wakawaka3/.venv-pi/bin/python"
else
  PY="python3"
fi

IP="$(hostname -I | awk '{print $1}')"
echo "[ESC-LAB] Python: $PY"
echo "[ESC-LAB] Open: http://${IP}:8770"
exec "$PY" tools/esc_lab.py
