# ==============================================================================
# IMPARK Evaluator & Observability Pipeline - Windows PowerShell Launcher
# Self-hosted LLM-as-a-Judge (gemma4:e4b) + Arize Phoenix + Redis Streams
# ==============================================================================

param (
    [switch]$Worker,
    [switch]$Demo,
    [string]$Query = ""
)

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
    
    Write-Host "`nWaiting for database healthchecks (5 seconds)..." -ForegroundColor Gray
    Start-Sleep -Seconds 5

    # Ensure phoenix database and table exist inside PostgreSQL
    try {
        docker exec -i eval-postgres psql -U postgres -d postgres -c "SELECT 'CREATE DATABASE phoenix' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')\gexec" 2>&1 | Out-Null
    } catch {}
    try {
        docker exec -i eval-postgres psql -U postgres -d phoenix -c "CREATE TABLE IF NOT EXISTS agent_evaluations (id SERIAL PRIMARY KEY, trace_id VARCHAR(64), span_id VARCHAR(64), user_input TEXT, agent_output TEXT, retrieved_context TEXT, graph_retrieval_time_ms DOUBLE PRECISION, tool_selection_accuracy DOUBLE PRECISION, groundedness DOUBLE PRECISION, hallucination_rate DOUBLE PRECISION, judge_reasoning TEXT, raw_payload JSONB, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);" 2>&1 | Out-Null
    } catch {}

    Write-Host "`n[+] Infrastructure services started successfully!" -ForegroundColor Green
    Write-Host "  - Arize Phoenix UI:  http://localhost:6006" -ForegroundColor Cyan
    Write-Host "  - PostgreSQL DB:     127.0.0.1:5433 (db: phoenix, user: postgres)" -ForegroundColor Cyan
    Write-Host "  - Redis Stream:      127.0.0.1:6379 (stream: phoenix-agent-traces)" -ForegroundColor Cyan
    Write-Host "  - Judge Model:       gemma4:e4b (via local Ollama at http://localhost:11434)`n" -ForegroundColor Cyan
} else {
    Write-Host "[!] Docker Desktop is not currently running." -ForegroundColor Yellow
    Write-Host "    Pipeline will run with in-memory fallbacks. To run with live persistent containers, start Docker Desktop.`n" -ForegroundColor Gray
}

# 2. Check Ollama Status
$ollamaOnline = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) { $ollamaOnline = $true }
} catch {}

if ($ollamaOnline) {
    Write-Host "[+] Local Ollama is ONLINE (ready for gemma4:e4b judge execution)." -ForegroundColor Green
} else {
    Write-Host "[!] Local Ollama is not currently active at http://localhost:11434." -ForegroundColor Yellow
    Write-Host "    To use gemma4:e4b for LLM-as-a-Judge, start Ollama ('ollama serve') and pull 'gemma4:e4b'." -ForegroundColor Gray
    Write-Host "    The evaluation engine will use factual token-grounding verification until Ollama is started.`n" -ForegroundColor Gray
}

# 3. Resolve Python Executable
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

# 4. Check / Install dependencies if redis or requests is missing
$depsTest = & $pythonExe -c "import redis, requests; print('OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Core dependencies missing in $pythonExe. Installing requirements.txt..." -ForegroundColor Yellow
    & $pythonExe -m pip install -q -r requirements.txt
}

# 5. Execute Desired Pipeline Mode
if ($Query) {
    Write-Host "[*] Evaluating Live Agent Turn for Query: '$Query'..." -ForegroundColor Yellow
    & $pythonExe phoenix_pipeline.py --query $Query
} elseif ($Demo) {
    Write-Host "[*] Executing Phoenix LLM-as-a-Judge Pipeline Verification..." -ForegroundColor Yellow
    & $pythonExe phoenix_pipeline.py --demo
} else {
    Write-Host "[*] Launching Continuous Idle-Aware Evaluation Judge Worker (0.0% Idle CPU)..." -ForegroundColor Yellow
    Write-Host "    Listening on Redis Streams: 'phoenix-agent-traces', 'my_stream', 'agent-logs'" -ForegroundColor Gray
    Write-Host "    The judge sleeps in kernel space and wakes up sequentially when an agent turn completes." -ForegroundColor Gray
    Write-Host "    Press Ctrl+C to stop the worker.`n" -ForegroundColor Gray
    & $pythonExe phoenix_pipeline.py --worker
}
$pipelineExitCode = $LASTEXITCODE

if ($pipelineExitCode -ne 0 -and $pipelineExitCode -ne 130) {
    Write-Host "`n=====================================================================" -ForegroundColor Red
    Write-Host "           Pipeline Execution Exited with code: $pipelineExitCode     " -ForegroundColor Red
    Write-Host "=====================================================================" -ForegroundColor Red
    exit $pipelineExitCode
}
