# ==============================================================================
# IMPARK Evaluator & Observability Pipeline - Windows PowerShell Launcher
# Self-hosted LLM-as-a-Judge (gemma4:e4b) + Arize Phoenix + Redis Streams
# ==============================================================================

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "   IMPARK Phoenix LLM-as-a-Judge Pipeline - Windows Environment      " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Standard Environment Configuration
$env:EVAL_POSTGRES_PORT = "5433"
$env:POSTGRES_PORT = "5433"
$env:POSTGRES_HOST = "127.0.0.1"
$env:POSTGRES_DB = "phoenix"
$env:REDIS_HOST = "127.0.0.1"
$env:REDIS_PORT = "6379"
$env:REDIS_STREAM = "phoenix-agent-traces"
$env:AGENT_MODEL = "gemma4:e4b"
$env:EVAL_MODEL = "gemma4:e4b"
$env:PHOENIX_ENDPOINT = "http://localhost:6006"

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
    Write-Host "[*] Launching infrastructure containers (Redis, Postgres, Arize Phoenix)..." -ForegroundColor Yellow
    docker compose up -d --remove-orphans
    
    Write-Host "`nWaiting for database healthchecks (10 seconds)..." -ForegroundColor Gray
    Start-Sleep -Seconds 10

    # Ensure phoenix database exists inside PostgreSQL
    try {
        docker exec -i eval-postgres psql -U postgres -c "SELECT 'CREATE DATABASE phoenix' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec" 2>&1 | Out-Null
    } catch {}

    Write-Host "`n[+] Infrastructure services started successfully!" -ForegroundColor Green
    Write-Host "  - Arize Phoenix UI:  http://localhost:6006" -ForegroundColor Cyan
    Write-Host "  - PostgreSQL DB:     127.0.0.1:5433 (db: phoenix, user: postgres)" -ForegroundColor Cyan
    Write-Host "  - Redis Stream:      127.0.0.1:6379 (stream: phoenix-agent-traces)" -ForegroundColor Cyan
    Write-Host "  - Judge Model:       gemma4:e4b (via local Ollama at http://localhost:11434)`n" -ForegroundColor Cyan
} else {
    Write-Host "[!] Docker Desktop is not currently running." -ForegroundColor Yellow
    Write-Host "    Pipeline will run with in-memory fallbacks. To run with live persistent containers, start Docker Desktop." -ForegroundColor Gray
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
    Write-Host "[ERROR] Python executable not found. Please activate your virtual environment." -ForegroundColor Red
    exit 1
}

Write-Host "[+] Using Python: $pythonExe" -ForegroundColor Green

# 3. Check / Install dependencies if redis or phoenix is missing
$depsTest = & $pythonExe -c "import redis, requests; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Core dependencies missing in $pythonExe. Installing requirements.txt..." -ForegroundColor Yellow
    & $pythonExe -m pip install -q -r requirements.txt
}

# 4. Run Phoenix Pipeline End-to-End Evaluation
Write-Host "[*] Executing Phoenix LLM-as-a-Judge Evaluation Pipeline..." -ForegroundColor Yellow
& $pythonExe phoenix_pipeline.py
$pipelineExitCode = $LASTEXITCODE

if ($pipelineExitCode -ne 0) {
    Write-Host "`n=====================================================================" -ForegroundColor Red
    Write-Host "           Pipeline Execution FAILED (Exit Code: $pipelineExitCode)   " -ForegroundColor Red
    Write-Host "=====================================================================" -ForegroundColor Red
    exit $pipelineExitCode
}

Write-Host "`n=====================================================================" -ForegroundColor Green
Write-Host "   Pipeline Verified! Open Arize Phoenix: http://localhost:6006       " -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
