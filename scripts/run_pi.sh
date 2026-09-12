#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/raspberry_pi"
exec "$ROOT/.venv-pi/bin/python" main.py
