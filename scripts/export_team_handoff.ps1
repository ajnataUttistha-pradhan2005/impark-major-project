param(
    [string]$Destination = 'backups\team-handoff'
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backupRoot = if ([IO.Path]::IsPathRooted($Destination)) { [IO.Path]::GetFullPath($Destination) } else { [IO.Path]::GetFullPath((Join-Path $root $Destination)) }
$containers = @('neo4j-dev', 'impark-major-project-postgres-1', 'impark-major-project-qdrant-1')
$volumes = @(
    @{ Name = 'neo4j_dev_data'; File = 'neo4j-data.tgz' },
    @{ Name = 'impark-major-project_postgres-data'; File = 'postgres-data.tgz' },
    @{ Name = 'impark-major-project_qdrant-data'; File = 'qdrant-data.tgz' }
)
$archiveNames = @($volumes | ForEach-Object { $_.File }) + @('database-images.tar', 'image-assets.tgz', 'SHA256.txt')

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($backupRoot).Substring(0, 1))
if ($drive.Free -lt 5GB) { throw 'Less than 5 GB is free at the backup destination' }
foreach ($name in $archiveNames) {
    if (Test-Path -LiteralPath (Join-Path $backupRoot $name)) {
        throw "Refusing to overwrite existing archive: $name. Choose a new -Destination."
    }
}
foreach ($item in $volumes) {
    docker volume inspect $item.Name *> $null
    if ($LASTEXITCODE -ne 0) { throw "Required volume is missing: $($item.Name)" }
}
foreach ($name in $containers) {
    $running = docker inspect --format '{{.State.Running}}' $name
    if ($LASTEXITCODE -ne 0 -or $running -ne 'true') { throw "Required container is not running: $name" }
}
foreach ($path in @('data\image\xception_model.keras', 'data\image\features.npz', 'data\image\dataset')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $path))) { throw "Required image asset is missing: $path" }
}
docker pull alpine:3.20 | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not pull the archive helper image' }

function Stop-LocalApp([int]$port, [string]$marker) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($processId in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
        if (-not $process.CommandLine -or -not $process.CommandLine.Contains($root) -or -not $process.CommandLine.Contains($marker)) {
            throw "Port $port is owned by an unrecognized process; stop it manually before exporting"
        }
        Stop-Process -Id $processId -ErrorAction Stop
        Write-Host "Stopped IMPARK process on port $port ($processId)."
    }
}

# Verify both listeners before stopping either one.
$hadApp = $false
foreach ($entry in @(@{ Port = 3000; Marker = 'frontend' }, @{ Port = 8000; Marker = 'backend' })) {
    $listeners = @(Get-NetTCPConnection -LocalPort $entry.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($listeners.Count -gt 0) { $hadApp = $true }
    foreach ($processId in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
        if (-not $process.CommandLine -or -not $process.CommandLine.Contains($root) -or -not $process.CommandLine.Contains($entry.Marker)) {
            throw "Port $($entry.Port) is owned by an unrecognized process; no services were stopped"
        }
    }
}

$stoppedDatabases = $false
try {
    Stop-LocalApp 3000 'frontend'
    Stop-LocalApp 8000 'backend'
    Start-Sleep -Seconds 2
    docker stop $containers | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop all databases; no hot snapshot will be taken' }
    $stoppedDatabases = $true
    foreach ($name in $containers) {
        $running = docker inspect --format '{{.State.Running}}' $name
        if ($LASTEXITCODE -ne 0 -or $running -ne 'false') { throw "Container did not stop: $name" }
    }
    foreach ($item in $volumes) {
        Write-Host "Archiving $($item.Name)..."
        docker run --rm --mount "type=volume,source=$($item.Name),target=/source,readonly" --mount "type=bind,source=$backupRoot,target=/backup" alpine:3.20 tar -C /source -czf "/backup/$($item.File)" .
        if ($LASTEXITCODE -ne 0) { throw "Archive failed for $($item.Name)" }
    }
    Write-Host 'Saving database images...'
    docker image save --output (Join-Path $backupRoot 'database-images.tar') neo4j:2026.09.0 postgres:17 qdrant/qdrant:v1.13.6 alpine:3.20
    if ($LASTEXITCODE -ne 0) { throw 'Database image export failed' }
    Write-Host 'Archiving image model and dataset...'
    tar.exe -czf (Join-Path $backupRoot 'image-assets.tgz') -C $root data/image
    if ($LASTEXITCODE -ne 0) { throw 'Image asset export failed' }
    foreach ($name in $archiveNames | Where-Object { $_ -ne 'SHA256.txt' }) {
        $path = Join-Path $backupRoot $name
        if (-not (Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0) { throw "Archive missing or empty: $name" }
        if ($name.EndsWith('.tgz')) { tar.exe -tzf $path *> $null } else { tar.exe -tf $path *> $null }
        if ($LASTEXITCODE -ne 0) { throw "Archive verification failed: $name" }
    }
    $archiveNames | Where-Object { $_ -ne 'SHA256.txt' } | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath (Join-Path $backupRoot $_) -Algorithm SHA256).Hash
        "$hash  $_"
    } | Set-Content -LiteralPath (Join-Path $backupRoot 'SHA256.txt')
    Write-Host "Cold handoff verified: $backupRoot"
} finally {
    if ($stoppedDatabases) {
        docker start $containers | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Warning 'One or more database containers did not restart; inspect docker ps.' }
    } else {
        # docker stop can succeed for some containers before reporting a failure.
        foreach ($name in $containers) { docker start $name *> $null }
    }
    if ($hadApp) { & (Join-Path $PSScriptRoot 'demo.ps1') }
}
