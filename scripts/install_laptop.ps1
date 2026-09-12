$ErrorActionPreference="Stop"
$Root=Split-Path -Parent $PSScriptRoot
$Venv=Join-Path $Root ".venv-laptop"
if(-not(Test-Path $Venv)){py -3 -m venv $Venv}
$Python=Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements-laptop.txt")
Write-Host "Done. Edit config\laptop.yaml and config\input.yaml."
