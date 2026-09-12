#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/.tools/mediamtx/mediamtx" "$ROOT/video/mediamtx.yml"
