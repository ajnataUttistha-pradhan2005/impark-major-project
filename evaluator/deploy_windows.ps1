# ==============================================================================
# IMPARK Evaluator & Observability Pipeline - Windows PowerShell Launcher
# Self-hosted, decoupled LangGraph evaluation stack (Redis, Postgres, Grafana, Worker)
# ==============================================================================

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "       IMPARK Evaluator Pipeline - Windows Local Environment         " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 1. Check Docker Daemon Status
Write-Host "[*] Checking Docker Desktop status..." -ForegroundColor Yellow
$dockerRunning = $false
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dockerRunning = $true
    }
} catch {
    $dockerRunning = $false
}

if ($dockerRunning) {
    Write-Host "[+] Docker Desktop is active." -ForegroundColor Green
    Write-Host "[*] Launching infrastructure containers (Redis, Postgres, Grafana)..." -ForegroundColor Yellow
    docker compose up -d
    
    Write-Host "`nWaiting for database healthchecks (10 seconds)..." -ForegroundColor Gray
    Start-Sleep -Seconds 10

    Write-Host "`n[+] Infrastructure services started successfully!" -ForegroundColor Green
    Write-Host "  - Grafana Dashboard: http://localhost:3000 (admin / admin)" -ForegroundColor Cyan
    Write-Host "  - PostgreSQL:        localhost:5432 (db: eval_db)" -ForegroundColor Cyan
    Write-Host "  - Redis Streams:     localhost:6379 (stream: agent-logs)`n" -ForegroundColor Cyan
} else {
    Write-Host "[!] Docker Desktop is not currently running." -ForegroundColor Yellow
    Write-Host "    If you wish to run the full Docker stack, please start Docker Desktop and re-run this script." -ForegroundColor Gray
}

# 2. Resolve Python Executable
$pythonCandidates = @(
    "$ScriptDir\..\.venv\Scripts\python.exe",
    "$ScriptDir\.venv\Scripts\python.exe",
    "python"
)
$pythonExe = $null
foreach ($cand in $pythonCandidates) {
    if ($cand -eq "python") {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $pythonExe = "python"
            break
        }
    } elseif (Test-Path $cand) {
        $pythonExe = $cand
        break
    }
}
if (-not $pythonExe) {
    $pythonExe = "python"
}

# 3. Check / Install dependencies if redis is missing
$redisTest = & $pythonExe -c "import redis; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] 'redis' package not found in $pythonExe. Installing requirements..." -ForegroundColor Yellow
    & $pythonExe -m pip install -q -r requirements.txt
}

# 4. Run Verification Test Suite
Write-Host "[*] Running Evaluator Verification Suite (Flow 1 & Flow 2)..." -ForegroundColor Yellow
& $pythonExe test_pipeline.py

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host "           Pipeline Verification Complete!                           " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
