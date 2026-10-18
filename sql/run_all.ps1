# Poora warehouse build (local): out/ CSVs -> clean schema -> mart (dims, fact, RFM) -> quality checks -> metric views
# Chalane ka tareeqa (repo root se, Docker chal raha ho):  powershell -ExecutionPolicy Bypass -File sql\run_all.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Run-Sql($f) {
    Write-Host ">> $f"
    Get-Content "sql\$f" -Raw | docker compose exec -T wh psql -U wh -d wh -v ON_ERROR_STOP=1 -q
    if ($LASTEXITCODE -ne 0) { throw "$f fail hui" }
}

Write-Host ">> load_staging.py"
python sql\load_staging.py out
if ($LASTEXITCODE -ne 0) { throw "load fail hua (out/ mein clean CSVs hain? .env mein WH_PW hai? pip install psycopg2-binary?)" }

foreach ($f in "01_schemas.sql","02_dims.sql","03_fact.sql") { Run-Sql $f }

Write-Host ">> 04_checks.sql"
$res = Get-Content "sql\04_checks.sql" -Raw | docker compose exec -T wh psql -U wh -d wh -v ON_ERROR_STOP=1
$res
if ($res -cmatch "FAIL") { throw "Quality check FAIL, upar dekho" }

Run-Sql "05_metrics.sql"
Write-Host "Done. Warehouse tayyar: schema mart."

