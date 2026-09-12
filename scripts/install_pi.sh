#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo apt-get update
sudo apt-get install -y \
  python3-venv \
  python3-pip \
  python3-dev \
  i2c-tools \
  curl

sudo raspi-config nonint do_i2c 0 || true

rm -rf "$ROOT/.venv-pi"
python3 -m venv "$ROOT/.venv-pi"

PYTHON="$ROOT/.venv-pi/bin/python"

"$PYTHON" -m pip install --upgrade pip setuptools wheel

# Python 3.13+ on 64-bit Raspberry Pi must use Adafruit's prebuilt lgpio wheel.
PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
ARCH="$(uname -m)"

if [[ "$PYVER" == "3.13" || "$PYVER" == "3.14" || "$PYVER" == "3.15" ]]; then
  if [[ "$ARCH" == "aarch64" ]]; then
    "$PYTHON" -m pip install --no-cache-dir "adafruit-lgpio==0.2.2.0"
  fi
fi

"$PYTHON" -m pip install --no-cache-dir -r "$ROOT/requirements-pi.txt"

echo
echo "Pi install complete."
"$PYTHON" -m pip check
"$PYTHON" -c "import lgpio; print('lgpio OK')"
"$PYTHON" -c "import board, busio; print('Blinka OK')"
"$PYTHON" -c "from adafruit_pca9685 import PCA9685; print('PCA9685 OK')"
echo
echo "Check PCA9685 on I2C bus with:"
echo "  i2cdetect -y 1"
