# Running VeriAgent Why against local Zetaris on Windows (PowerShell)

Target: Alonso's PC, Zetaris already running in Docker Desktop (UI http://localhost:3000, JDBC
`jdbc:zetaris:lightning@localhost:10000`). Everything below is PowerShell. Credentials go only into
`.env` (gitignored) — never into commits, chat or screenshots.

Federation used for the demo:

| Zetaris object | Source | Views |
|---|---|---|
| datasource `veriagent_pg` | PostgreSQL 16 (Docker, port 5433) | `v_orders`, `v_returns`, `v_logistics` |
| Lightning database `veriagent_rest` | REST tables over `scripts/zetaris_rest_source.py` (port 8765) | `v_tickets`, `v_promotions` |
| SchemaStore container `veriagent` | views over both sources | all 5 `v_*` (what the agent queries) |

Local CSV files are not used: the getting-started troubleshooting guide notes Zetaris may not reach
files on your laptop (file tables need S3/Azure/GCS/HDFS paths).

## 1. Prerequisites (check once)

```powershell
python --version          # 3.11+ (3.13 tested in CI)
java -version             # needs Java 8+; if missing: winget install EclipseAdoptium.Temurin.17.JDK
git --version
docker ps                 # Zetaris containers listed
```

If `java -version` works but JPype later can't find Java, set it for the session:

```powershell
$env:JAVA_HOME = (Get-ChildItem "C:\Program Files\Eclipse Adoptium" -Directory | Select-Object -First 1).FullName
```

## 2. Clone and install

```powershell
cd C:\Users\Mariano
git clone https://github.com/AlonsoAlviraa/veriagent-why.git
cd C:\Users\Mariano\veriagent-why
git checkout feat/infrastructure
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-zetaris.txt
python -m pytest -q               # offline sanity check, should all pass
```

## 3. Start the Postgres source

Pick your own Postgres password (it only lives in `.env` and in this container):

```powershell
docker run -d --name veriagent-pg -p 5433:5432 `
  -e POSTGRES_DB=veriagent -e POSTGRES_USER=veriagent -e POSTGRES_PASSWORD=<choose-one> `
  postgres:16
```

(Re-runs: `docker start veriagent-pg`.)

## 4. Fill `.env` (you do this; nobody else sees it)

```powershell
Copy-Item .env.example .env
notepad .env
```

Set these lines (JAR stays where the Zetaris bundle put it — outside the repo):

```
ZETARIS_BACKEND=zetaris
SAMPLE_MODE=false
ZETARIS_JDBC_URL=jdbc:zetaris:lightning@localhost:10000
ZETARIS_USER=<your Zetaris login>
ZETARIS_PASSWORD=<your Zetaris password>
ZETARIS_JDBC_JAR=C:\path\to\zetaris-bundle\jdbc\ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar
ZETARIS_VIEW_PREFIX=veriagent.
VA_PG_HOST=localhost
VA_PG_PORT=5433
VA_PG_DB=veriagent
VA_PG_USER=veriagent
VA_PG_PASSWORD=<same as step 3>
VA_PG_HOST_FROM_ZETARIS=host.docker.internal
VA_REST_HOST_FROM_ZETARIS=host.docker.internal
VA_REST_PORT=8765
LLM_PROVIDER=sample
```

(`LLM_PROVIDER=nvidia` plus `NVIDIA_API_KEY` for live models; keep `sample` for a pure data test.)

## 5. Start the REST source (second window, leave it running)

```powershell
cd C:\Users\Mariano\veriagent-why
.\.venv\Scripts\Activate.ps1
python scripts\zetaris_rest_source.py
```

Windows Firewall may ask about Python: allow on private networks (Docker reaches it via host.docker.internal).

## 6. Load into Zetaris (idempotent — safe to re-run)

```powershell
python scripts\zetaris_load.py --dry-run   # prints the plan and SQL, touches nothing
python scripts\zetaris_load.py
```

If the REST tables fail on your build, fall back to a single source:
`python scripts\zetaris_load.py --no-rest` (all 5 views in Postgres).

## 7. Check

```powershell
python scripts\zetaris_check.py
```

Expect `SELECT 1 -> [{'one': 1}]`, the datasource/database lists, and every view `OK`
(v_orders 1818, v_returns 117, v_tickets 112, v_logistics 1818, v_promotions 1), then `ALL OK`.

## 8. Run the demo against Zetaris

```powershell
python run.py --input input_examples\example_1.json
```

The result's trace shows `zetaris-jdbc` as the data backend. UI (two more windows):

```powershell
python run.py --serve      # API on :8000
python run.py --ui         # UI on http://localhost:8501
```

## Troubleshooting

- `missing env: ...` — a value in `.env` is empty.
- `keep the Zetaris JDBC jar outside the repo` — point `ZETARIS_JDBC_JAR` at the bundle copy.
- `CREATE DATASOURCE` connection error — Postgres container not running, or host.docker.internal not
  resolvable from Zetaris; try your PC's LAN IP in `VA_PG_HOST_FROM_ZETARIS`.
- Count `MISMATCH` on v_tickets/v_promotions — the REST source window is not running.
