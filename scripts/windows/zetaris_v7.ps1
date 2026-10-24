# VeriAgent Why - V7 priority 1 runbook for Alonso's Windows PC (PowerShell, Docker Desktop).
# NOT run by the bot: the box cannot reach this PC. Run step by step; each step stops on error.
# Prereqs: Zetaris already running in Docker Desktop (UI http://localhost:3000, JDBC localhost:10000),
# Python 3.11+, Java 8+, git. Credentials live only in .env (gitignored) - never typed into chat.
#
# Usage (from the repo root, venv active):
#   .\scripts\windows\zetaris_v7.ps1 -Step all        # or: prereq | postgres | rest | load | check | demo | record
param([ValidateSet("prereq","postgres","rest","load","check","demo","record","all")][string]$Step = "all")
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Repo

function Prereq {
  python --version; java -version; docker ps --format "{{.Names}}"
  if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - fill it (docs/RUN_WINDOWS.md step 4), then re-run." -ForegroundColor Yellow; notepad .env; exit 1 }
  foreach ($k in "ZETARIS_JDBC_JAR","ZETARIS_USER","ZETARIS_PASSWORD","VA_PG_PASSWORD") {
    if (-not (Select-String -Path .env -Pattern "^$k=.+" -Quiet)) { throw "$k is empty in .env" }
  }
  pip install -r requirements.txt -r requirements-zetaris.txt
  python -m pytest -q tests/test_verify_receipts.py   # offline: mutate a row -> red
}

function Postgres {
  # Reads the PG password from .env without printing it.
  $pw = ((Select-String -Path .env -Pattern "^VA_PG_PASSWORD=(.+)$").Matches[0].Groups[1].Value).Trim('"')
  if (docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch "veriagent-pg" -Quiet) { docker start veriagent-pg | Out-Null }
  else { docker run -d --name veriagent-pg -p 5433:5432 -e POSTGRES_DB=veriagent -e POSTGRES_USER=veriagent -e "POSTGRES_PASSWORD=$pw" postgres:16 | Out-Null }
  Start-Sleep 5; docker exec veriagent-pg pg_isready -U veriagent
}

function Rest {
  # Second federated source; must stay up during load, check, demo and recording.
  Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$Repo'; .\.venv\Scripts\Activate.ps1; python scripts\zetaris_rest_source.py"
  Start-Sleep 3; (Invoke-WebRequest -UseBasicParsing http://localhost:8765/v_tickets).StatusCode
}

function Load  { python scripts\zetaris_load.py --dry-run; python scripts\zetaris_load.py }
function Check { python scripts\zetaris_check.py; if ($LASTEXITCODE -ne 0) { throw "zetaris_check failed" } }

function Demo {
  # green -> mutate Postgres row -> RED through Zetaris -> restore -> green. Exit 0 only if all receipts say backend=zetaris.
  python scripts\verify_live_demo.py --backend zetaris
  if ($LASTEXITCODE -ne 0) { throw "verify demo failed" }
}

function Record {
  # Collect the JSONL traces of this session for the repo (secret scan runs before any commit).
  $out = "logs\zetaris_session_$(Get-Date -Format yyyyMMdd_HHmm)"
  New-Item -ItemType Directory -Force $out | Out-Null
  Get-ChildItem logs\trace-verify-demo-*.jsonl | Copy-Item -Destination $out
  python scripts\secret_scan.py
  Write-Host "Traces in $out. Review, then: git add -f $out; git commit -m 'Zetaris live session traces'" -ForegroundColor Green
}

switch ($Step) {
  "prereq" { Prereq } "postgres" { Postgres } "rest" { Rest } "load" { Load } "check" { Check } "demo" { Demo } "record" { Record }
  "all" { Prereq; Postgres; Rest; Load; Check; Demo; Record }
}
