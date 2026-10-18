# Poora warehouse build: staging load -> tables -> dims -> fact -> quality checks -> metric views
# Chalane ka tareeqa (repo root se, Docker chal raha ho):  powershell -File sql\run_all.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Run-Sql($f) {
    Write-Host ">> $f"
    Get-Content "sql\$f" -Raw | docker compose exec -T wh psql -U wh -d wh -v ON_ERROR_STOP=1 -q
    if ($LASTEXITCODE -ne 0) { throw "$f fail hui" }
}

Write-Host ">> load_staging.py"
python sql\load_staging.py out
if ($LASTEXITCODE -ne 0) { throw "staging load fail hua (out/ mein clean CSVs hain? .env mein WH_PW hai?)" }

foreach ($f in "01_schemas.sql","02_create_tables.sql","03_load_dimdate.sql","04_load_dims.sql","05_load_fact.sql") { Run-Sql $f }

Write-Host ">> 06_quality_checks.sql"
$res = Get-Content "sql\06_quality_checks.sql" -Raw | docker compose exec -T wh psql -U wh -d wh -v ON_ERROR_STOP=1
$res
if ($res -match "FAIL") { throw "Quality check FAIL, upar dekho" }

Run-Sql "07_metrics.sql"
Write-Host "Done. Warehouse tayyar: schema dw."
