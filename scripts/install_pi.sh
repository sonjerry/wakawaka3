#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/4] Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
  python3-venv \
  python3-pip \
  i2c-tools \
  curl

echo "[2/4] Enabling I2C..."
sudo raspi-config nonint do_i2c 0 || true

echo "[3/4] Creating Python virtual environment..."
rm -rf "$ROOT/.venv-pi"
python3 -m venv "$ROOT/.venv-pi"

PYTHON="$ROOT/.venv-pi/bin/python"
"$PYTHON" -m pip install --upgrade pip setuptools wheel

echo "[4/4] Installing Pi dependencies..."
"$PYTHON" -m pip install --no-cache-dir -r "$ROOT/requirements-pi.txt"

echo
echo "Dependency check:"
"$PYTHON" -m pip check
"$PYTHON" -c "from smbus2 import SMBus; print('smbus2 OK')"

echo
echo "I2C scan:"
i2cdetect -y 1 || true

echo
echo "Install complete."
echo "Expected PCA9685 address: 0x40"
echo "Run:"
echo "  ./scripts/run_pi.sh"
