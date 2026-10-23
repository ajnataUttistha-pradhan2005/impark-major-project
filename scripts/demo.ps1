param(
    [switch]$SkipDocker,
    [switch]$SkipWarmup,
    [switch]$DevFrontend,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend'
$logs = Join-Path $root 'data'
$backendUrl = 'http://127.0.0.1:8000'
$frontendUrl = 'http://127.0.0.1:3000'

if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) { throw 'Create .env from .env.example and configure the local services first.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment missing. Create .venv and install the backend dependencies first.' }
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\.bin\next.cmd'))) { throw 'Frontend dependencies missing. Run npm ci in frontend first.' }
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$preflightArgs = @((Join-Path $root 'scripts\demo_preflight.py'))
if (-not $SkipDocker) { $preflightArgs += '--local-docker' }
& $python @preflightArgs
if ($LASTEXITCODE -ne 0) { throw 'Demo preflight failed. Correct .env before starting any containers.' }

function Test-Endpoint([string]$url) {
    try {
        $result = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
        return $result.StatusCode -eq 200
    } catch { return $false }
}

function Wait-Endpoint([string]$url, [string]$name, [int]$seconds, $process) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint $url) { Write-Host "Ready: $name"; return }
        if ($process -and $process.HasExited) { throw "$name exited during startup. Check data/demo-$name.err.log." }
        Start-Sleep -Seconds 2
    }
    throw "$name did not become ready at $url within $seconds seconds."
}

function Get-ListenerPid([int]$port) {
    $line = netstat -ano -p tcp | Where-Object { $_ -match "^\s*TCP\s+127\.0\.0\.1:$port\s+.*\s+LISTENING\s+(\d+)\s*$" } | Select-Object -First 1
    if ($line -and $line -match 'LISTENING\s+(\d+)\s*$') { return [int]$Matches[1] }
    return $null
}

function Wait-ContainerHealthy([string]$name, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        $health = docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $name 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Container $name is missing. Inspect docker compose ps." }
        if ($health -eq 'healthy' -or $health -eq 'running') { Write-Host "Ready: $name ($health)"; return }
        if ($health -eq 'unhealthy' -or $health -eq 'exited') { throw "Container $name is $health. Inspect docker logs $name." }
        Start-Sleep -Seconds 2
    }
    throw "Container $name did not become ready. Inspect docker logs $name."
}

if ($Restart) {
    foreach ($entry in @(@{ Port = 8000; Marker = 'backend' }, @{ Port = 3000; Marker = 'frontend' })) {
        $listenerPid = Get-ListenerPid $entry.Port
        if (-not $listenerPid) { continue }
        $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid").CommandLine
        if (-not $command -or -not $command.Contains($root) -or -not $command.Contains($entry.Marker)) {
            throw "Port $($entry.Port) is held by an unrecognized process. Stop it manually."
        }
        Stop-Process -Id $listenerPid -ErrorAction Stop
        Write-Host "Stopped existing IMPARK $($entry.Marker) process ($listenerPid)."
    }
    Start-Sleep -Seconds 2
}

if (-not $SkipDocker) {
    docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable. Start Docker Desktop, or use -SkipDocker for external stores.' }
    $neo4j = docker container inspect neo4j-dev --format '{{.State.Running}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The local Neo4j container neo4j-dev is missing. Run scripts/restore_team_handoff.ps1 on a fresh teammate machine, or use -SkipDocker with an external Neo4j.' }
    if ($neo4j -ne 'true') { docker start neo4j-dev | Out-Null; if ($LASTEXITCODE -ne 0) { throw 'Could not start neo4j-dev.' } }
    Push-Location $root
    try {
        docker compose --profile stores up -d postgres qdrant
        if ($LASTEXITCODE -ne 0) { throw 'Could not start PostgreSQL and Qdrant.' }
    } finally { Pop-Location }
    Wait-ContainerHealthy 'impark-major-project-postgres-1' 120
    Wait-Endpoint 'http://127.0.0.1:6333/healthz' 'Qdrant' 120 $null
    # Docker reports a container as running before Neo4j accepts connections.
    # Wait here so a cold demo launch does not fail backend startup.
    Wait-Endpoint 'http://127.0.0.1:7474/' 'Neo4j HTTP' 120 $null
}

$backendProcess = $null
if (-not (Test-Endpoint "$backendUrl/health")) {
    if (Get-ListenerPid 8000) { throw 'Port 8000 is occupied by a service that does not answer /health.' }
    # backend.__main__ selects the Windows-compatible asyncio selector loop.
    $backendProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'backend') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'demo-backend.out.log') -RedirectStandardError (Join-Path $logs 'demo-backend.err.log')
}
try { Wait-Endpoint "$backendUrl/health" 'backend' 120 $backendProcess }
catch { throw "$($_.Exception.Message) Check data/demo-backend.err.log. If it says a database migration or search generation is missing, run the explicit migrate/sync setup commands." }

$frontendProcess = $null
if (-not (Test-Endpoint $frontendUrl)) {
    if (Get-ListenerPid 3000) { throw 'Port 3000 is occupied by another service.' }
    if (-not $DevFrontend -and ($Restart -or -not (Test-Path -LiteralPath (Join-Path $frontend '.next\BUILD_ID')))) {
        Push-Location $frontend
        try { npm run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } }
        finally { Pop-Location }
    }
    $env:BACKEND_URL = $backendUrl
    $mode = if ($DevFrontend) { 'dev' } else { 'start' }
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $frontendProcess = Start-Process -FilePath $npm -ArgumentList @('run', $mode) -WorkingDirectory $frontend -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'demo-frontend.out.log') -RedirectStandardError (Join-Path $logs 'demo-frontend.err.log')
}
try { Wait-Endpoint $frontendUrl 'frontend' 90 $frontendProcess }
catch { throw "$($_.Exception.Message) Check data/demo-frontend.err.log and run npm ci in frontend if dependencies are missing." }

if (-not $SkipWarmup) {
    Push-Location $root
    try { & $python (Join-Path $root 'scripts\demo_warmup.py'); if ($LASTEXITCODE -ne 0) { throw 'Warmup failed. Review the message above.' } }
    finally { Pop-Location }
}

Write-Host "IMPARK demo ready: $frontendUrl (API: $backendUrl/docs)"
