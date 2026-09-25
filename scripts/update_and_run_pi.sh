#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(git -C "$ROOT" branch --show-current)" != "main" ]]; then
  echo "[ERROR] Check out the main branch before updating the Pi." >&2
  exit 1
fi

echo "[RC] Updating main from origin..."
git -C "$ROOT" pull --ff-only origin main

echo "[RC] Starting Pi services..."
exec bash "$ROOT/scripts/run_pi.sh"
