# Account team — Windows install (Docker Desktop required).
# Usage: .\install.ps1
#    or: .\install.ps1 -Image "yashjeetamai/invoice-finintel:1.0.0"

param(
    [string]$Image = "yashjeetamai/invoice-finintel:latest",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$DeployDir = $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed." -ForegroundColor Red
    Write-Host "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is installed but not running. Start Docker Desktop, then run this script again." -ForegroundColor Red
    exit 1
}

if (-not $Image) {
    $envFile = Join-Path $DeployDir ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*IMAGE=(.+)$') { $Image = $Matches[1].Trim().Trim('"') }
        }
    }
}

if (-not $Image) {
    Write-Host "Set the image name first." -ForegroundColor Red
    Write-Host "  Or run: .\install.ps1 -Image `"yashjeetamai/invoice-finintel:latest`""
    exit 1
}

Write-Host "Pulling $Image ..."
docker pull $Image

$env:IMAGE = $Image
$env:PORT = "$Port"

Push-Location $DeployDir
try {
    docker compose up -d
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Invoice app is running." -ForegroundColor Green
Write-Host "Open: http://localhost:$Port"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  docker compose -f `"$DeployDir\docker-compose.yml`" logs -f"
Write-Host "  docker compose -f `"$DeployDir\docker-compose.yml`" stop"
Write-Host "  docker compose -f `"$DeployDir\docker-compose.yml`" down"
