#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-dev i2c-tools curl
sudo raspi-config nonint do_i2c 0 || true
python3 -m venv "$ROOT/.venv-pi"
"$ROOT/.venv-pi/bin/pip" install --upgrade pip
"$ROOT/.venv-pi/bin/pip" install -r "$ROOT/requirements-pi.txt"
chmod +x "$ROOT/scripts/"*.sh "$ROOT/video/"*.sh
echo "Done. Check PCA9685 with: i2cdetect -y 1"
