$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $PSScriptRoot
$Python=Join-Path $Root ".venv-laptop\Scripts\python.exe"
Set-Location (Join-Path $Root "laptop")
& $Python main.py
