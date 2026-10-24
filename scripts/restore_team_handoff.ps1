param(
    [string]$Source = 'backups\team-handoff',
    [switch]$ResetTargetVolumes,
    [switch]$SkipStart,
    [switch]$VerifyOnly
)

# Restore a *cold* export made by export_team_handoff.ps1. This script never
# silently overlays an initialized database volume.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$sourcePath = if ([IO.Path]::IsPathRooted($Source)) { [IO.Path]::GetFullPath($Source) } else { [IO.Path]::GetFullPath((Join-Path $root $Source)) }
$envPath = Join-Path $root '.env'
$items = @(
    @{ Volume = 'neo4j_dev_data'; Archive = 'neo4j-data.tgz' },
    @{ Volume = 'impark-major-project_postgres-data'; Archive = 'postgres-data.tgz' },
    @{ Volume = 'impark-major-project_qdrant-data'; Archive = 'qdrant-data.tgz' }
)
$containers = @('neo4j-dev', 'impark-major-project-postgres-1', 'impark-major-project-qdrant-1')
$archives = @($items | ForEach-Object { $_.Archive }) + @('database-images.tar', 'image-assets.tgz')

function Require-Exit([string]$message) {
    if ($LASTEXITCODE -ne 0) { throw $message }
}

function Env-Value([string]$name) {
    if (Test-Path "Env:$name") { return (Get-Item "Env:$name").Value }
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match "^\s*$name\s*=" } | Select-Object -Last 1
    if (-not $line) { return '' }
    return (($line -split '=', 2)[1].Trim()).Trim('"').Trim("'")
}

if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw "Handoff folder not found: $sourcePath" }

foreach ($name in $archives + @('SHA256.txt')) {
    $path = Join-Path $sourcePath $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -eq 0) {
        throw "Missing or empty handoff file: $name"
    }
}
$expectedNames = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $sourcePath 'SHA256.txt')) {
    $match = [regex]::Match($line, '^([0-9a-fA-F]{64})\s+(.+)$')
    if (-not $match.Success) { throw 'Invalid SHA256.txt format.' }
    $expectedNames[$match.Groups[2].Value.Trim()] = $match.Groups[1].Value
}
foreach ($name in $archives) {
    if (-not $expectedNames.ContainsKey($name)) { throw "SHA256.txt has no entry for $name" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $sourcePath $name)).Hash
    if ($actual -ne $expectedNames[$name]) { throw "Checksum mismatch: $name. Do not restore this transfer." }
    if ($name.EndsWith('.tgz')) {
        $entries = @(tar.exe -tzf (Join-Path $sourcePath $name))
        Require-Exit "Cannot read archive: $name"
        foreach ($entry in $entries) {
            if ($entry -match '(^/|^[A-Za-z]:|(^|/)\.\.(/|$))') { throw "Unsafe archive path in $name" }
            if ($name -eq 'image-assets.tgz' -and $entry -notmatch '^\.?/?data/image(/|$)') {
                throw "Image archive contains a path outside data/image: $entry"
            }
        }
    }
}
Write-Host 'Handoff files and SHA-256 checksums verified.'
if ($VerifyOnly) { return }

if (-not (Test-Path -LiteralPath $envPath)) { throw 'Create .env with the original database credentials before restoring.' }
if ((Env-Value 'COMPOSE_PROJECT_NAME') -ne 'impark-major-project') {
    throw 'Set COMPOSE_PROJECT_NAME=impark-major-project in .env so restored PostgreSQL/Qdrant volumes are mounted.'
}
$username = Env-Value 'NEO4J_USERNAME'
$password = Env-Value 'NEO4J_PASSWORD'
if (-not $username -or -not $password) { throw 'Set NEO4J_USERNAME and NEO4J_PASSWORD in .env to the credentials of the exported graph.' }
foreach ($name in @('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB')) {
    if (-not (Env-Value $name)) { throw "Set $name in .env to the credentials of the exported PostgreSQL volume." }
}

docker info --format '{{.ServerVersion}}' *> $null
Require-Exit 'Docker Desktop Linux engine is unavailable. Start Docker Desktop first.'

if ($ResetTargetVolumes) {
    Write-Host 'ResetTargetVolumes selected: removing only the three named IMPARK containers and volumes.'
    foreach ($name in $containers) {
        $exists = (docker container ls -a -q --filter "name=^/${name}$"); if ($exists) { $LASTEXITCODE = 0 } else { $LASTEXITCODE = 1 }
        if ($LASTEXITCODE -eq 0) { docker rm -f $name | Out-Null; Require-Exit "Could not remove container $name" }
    }
    foreach ($item in $items) {
        $volExists = (docker volume ls -q --filter "name=^$($item.Volume)$"); if ($volExists) { $LASTEXITCODE = 0 } else { $LASTEXITCODE = 1 }
        if ($LASTEXITCODE -eq 0) { docker volume rm $item.Volume | Out-Null; Require-Exit "Could not remove volume $($item.Volume)" }
    }
}

foreach ($name in $containers) {
    $exists = (docker container ls -a -q --filter "name=^/${name}$"); if ($exists) { $LASTEXITCODE = 0 } else { $LASTEXITCODE = 1 }
    if ($LASTEXITCODE -eq 0) { throw "Container $name already exists. Use a fresh Docker setup or explicitly pass -ResetTargetVolumes after backing up any data in it." }
}
foreach ($item in $items) {
    $volExists = (docker volume ls -q --filter "name=^$($item.Volume)$"); if ($volExists) { $LASTEXITCODE = 0 } else { $LASTEXITCODE = 1 }
    if ($LASTEXITCODE -eq 0) {
        # Refuse even a seemingly empty existing volume: a container may be initializing it.
        throw "Volume $($item.Volume) already exists. Use a fresh setup or -ResetTargetVolumes after backing up its data."
    }
}

docker image load --input (Join-Path $sourcePath 'database-images.tar') | Out-Null
Require-Exit 'Could not load database Docker images.'
foreach ($item in $items) {
    docker volume create $item.Volume | Out-Null
    Require-Exit "Could not create volume $($item.Volume)"
    docker run --rm --mount "type=volume,source=$($item.Volume),target=/target" --mount "type=bind,source=$sourcePath,target=/backup,readonly" alpine:3.20 tar -C /target -xzf "/backup/$($item.Archive)"
    Require-Exit "Could not restore $($item.Archive)"
    Write-Host "Restored $($item.Volume)"
}
tar.exe -xzf (Join-Path $sourcePath 'image-assets.tgz') -C $root
Require-Exit 'Could not restore data/image assets.'

# The Docker image uses this value only to configure/check the initial auth;
# the restored data volume retains its original users and database contents.
docker create --name neo4j-dev --publish '127.0.0.1:7474:7474' --publish '127.0.0.1:7687:7687' --mount 'type=volume,source=neo4j_dev_data,target=/data' --env "NEO4J_AUTH=$username/$password" neo4j:2026.09.0 | Out-Null
Require-Exit 'Could not create neo4j-dev container.'

if (-not $SkipStart) {
    docker start neo4j-dev | Out-Null
    Require-Exit 'Could not start neo4j-dev.'
    Push-Location $root
    try {
        docker compose --profile stores up -d postgres qdrant
        Require-Exit 'Could not start restored PostgreSQL/Qdrant containers.'
    } finally { Pop-Location }
}
Write-Host 'Restore complete. Verify all three stores, then run scripts/demo.ps1.'
Write-Host 'Do not run search_admin sync on this restored projection unless its generation is stale or you intend to rebuild it.'
