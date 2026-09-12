#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv-pi/bin/python"
MEDIAMTX="$ROOT/.tools/mediamtx/mediamtx"
MEDIAMTX_CFG="$ROOT/video/mediamtx.yml"

if [[ ! -x "$PYTHON" ]]; then
  echo "[ERROR] Pi virtualenv not found:"
  echo "  $PYTHON"
  echo "Run first:"
  echo "  bash $ROOT/scripts/install_pi.sh"
  exit 1
fi

if [[ ! -x "$MEDIAMTX" ]]; then
  echo "[ERROR] MediaMTX is not installed:"
  echo "  $MEDIAMTX"
  echo "Run first:"
  echo "  bash $ROOT/video/install_mediamtx.sh"
  exit 1
fi

cleanup() {
  echo
  echo "[RC] stopping services..."

  if [[ -n "${MEDIAMTX_PID:-}" ]]; then
    kill "$MEDIAMTX_PID" 2>/dev/null || true
  fi

  if [[ -n "${MAIN_PID:-}" ]]; then
    kill "$MAIN_PID" 2>/dev/null || true
  fi

  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "[RC] Starting MediaMTX camera server..."
"$MEDIAMTX" "$MEDIAMTX_CFG" &
MEDIAMTX_PID=$!

sleep 1

if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
  echo "[ERROR] MediaMTX stopped during startup."
  exit 1
fi

echo "[RC] Starting Raspberry Pi control server..."
cd "$ROOT/raspberry_pi"
"$PYTHON" main.py &
MAIN_PID=$!

echo
echo "[RC] Services running"
echo "  Control : http://0.0.0.0:8765"
echo "  Camera  : http://<PI_IP>:8889/cam"
echo
echo "Press Ctrl+C to stop both."

# 종료된 프로세스가 하나라도 생기면 스크립트를 종료하고 cleanup으로 나머지도 종료.
wait -n "$MEDIAMTX_PID" "$MAIN_PID"
