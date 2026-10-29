param(
    [switch]$Stop,
    [switch]$Logs,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Stop) {
    Write-Host "Stopping Agent Center..." -ForegroundColor Yellow
    & docker compose down
    exit $LASTEXITCODE
}

if ($Logs) {
    & docker compose logs -f app
    exit $LASTEXITCODE
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed. Install Docker Desktop first." -ForegroundColor Red
    exit 1
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $desktop) {
        Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
        Start-Process $desktop
    } else {
        Write-Host "Docker engine is not running. Start Docker Desktop and retry." -ForegroundColor Red
        exit 1
    }
    $deadline = (Get-Date).AddSeconds(150)
    do {
        Start-Sleep -Seconds 5
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { break }
    } while ((Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker engine did not become ready in time." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill AC_LLM_API_KEY to use a real model." -ForegroundColor Yellow
}

Write-Host "Building and starting containers..." -ForegroundColor Cyan
if ($NoBuild) {
    & docker compose up -d
} else {
    & docker compose up -d --build
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose up failed." -ForegroundColor Red
    exit 1
}

Write-Host "Waiting for http://127.0.0.1:8000/healthz ..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 3
    }
}

if (-not $ready) {
    Write-Host "Application did not become healthy. Recent logs:" -ForegroundColor Red
    & docker compose logs --tail 80 app
    exit 1
}

Write-Host ""
Write-Host "Agent Center is running." -ForegroundColor Green
Write-Host "  API docs : http://localhost:8000/docs"
Write-Host "  Health   : http://localhost:8000/healthz"
Write-Host "  MySQL    : localhost:3307 (agent / agent_pass, db agent_center)"
Write-Host "  Redis    : localhost:6380"
Write-Host "  Vector   : embedded Milvus Lite (volume milvus_lite_data)"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  docker compose ps"
Write-Host "  powershell -File scripts/start.ps1 -Logs"
Write-Host "  powershell -File scripts/start.ps1 -Stop"
