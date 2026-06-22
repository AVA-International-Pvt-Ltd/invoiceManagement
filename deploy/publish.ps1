# Maintainer — build and push to Docker Hub.
# Usage: .\publish.ps1
#    or: .\publish.ps1 -Tag "1.0.0"

param(
    [string]$Tag = "latest",
    [string]$Repo = "yashjeetamai/invoice-finintel"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$fullTag = "${Repo}:${Tag}"
Write-Host "Building $fullTag ..."
docker build -t $fullTag $Root

Write-Host "Pushing $fullTag ..."
docker push $fullTag

if ($Tag -ne "latest") {
    $latestTag = "${Repo}:latest"
    Write-Host "Tagging and pushing $latestTag ..."
    docker tag $fullTag $latestTag
    docker push $latestTag
}

Write-Host ""
Write-Host "Done. Account team can run:" -ForegroundColor Green
Write-Host "  docker pull $fullTag"
Write-Host "  cd deploy && .\install.ps1 -Image `"$fullTag`""
