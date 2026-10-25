# VeriAgent Why - demo-video launcher for Alonso's Windows PC (PowerShell). NOT run by the bot.
# Shows, in order: Nightshift pin check -> Zetaris check -> live agent run on Zetaris through Nightshift
# (planted promotion trap, example_2) -> planted-mutation verify demo (green -> red -> green) -> receipts table.
# Prereqs: Zetaris running in Docker Desktop, veriagent-pg + REST source up (zetaris_v7.ps1 -Step postgres / rest),
# Meterless Nightshift running on :8088 with the NVIDIA key set in its own app, .env filled, venv active.
# SAFETY FOR RECORDING: never open .env, the Nightshift proxy-token, or any Zetaris login file on screen.
# This script prints no secrets: tokens are read by the app and never echoed.
param([ValidateSet("pins","zetaris","run","mutate","receipts","all")][string]$Step = "all")
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Repo
$env:SAMPLE_MODE = "false"; $env:ZETARIS_BACKEND = "zetaris"; $env:LLM_PROVIDER = "nightshift"
$env:LLM_FALLBACK = "none"; $env:METERLESS_REQUIRED = "1"; $env:NIGHTSHIFT_PIN_ENFORCE = "on"
$env:VA_LOG_DIR = Join-Path $Repo "logs\demo_video"
New-Item -ItemType Directory -Force $env:VA_LOG_DIR | Out-Null

function Pins     { python -m app.nightshift; if ($LASTEXITCODE -ne 0) { throw "Nightshift pin check failed" } }
function Zetaris  { python scripts\zetaris_check.py; if ($LASTEXITCODE -ne 0) { throw "zetaris_check failed" } }
function Run      { python run.py --input input_examples\example_2.json --brief; if ($LASTEXITCODE -ne 0) { throw "run failed" } }
function Mutate   { python scripts\verify_live_demo.py --backend zetaris; if ($LASTEXITCODE -ne 0) { throw "verify demo failed" } }
function Receipts {
  python -c "import json,glob,collections,os; d=os.environ['VA_LOG_DIR']; c=collections.Counter(); [c.update([(r.get('agent') or r.get('purpose') or '-', r.get('routed_model'), r.get('ok'))]) for f in glob.glob(d+'/receipts-*.jsonl') for r in map(json.loads, open(f))]; [print(f'{n:4d}  {a:20s} {m}  ok={o}') for (a,m,o),n in sorted(c.items(), key=lambda x:-x[1])]"
}
switch ($Step) {
  "pins" { Pins } "zetaris" { Zetaris } "run" { Run } "mutate" { Mutate } "receipts" { Receipts }
  "all" { Pins; Zetaris; Run; Mutate; Receipts; Write-Host "DEMO SEQUENCE DONE (outputs in logs\demo_video)" -ForegroundColor Green }
}
