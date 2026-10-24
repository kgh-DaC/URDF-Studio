# Windows PowerShell launcher. Usage:  .\run.ps1            (port 8000)
#                                      .\run.ps1 -Port 8080
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
if (-not $env:ANTHROPIC_API_KEY) {
    Write-Host "ANTHROPIC_API_KEY not set: generation is disabled; validation/viewer/samples still work." -ForegroundColor Yellow
}
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port $Port
