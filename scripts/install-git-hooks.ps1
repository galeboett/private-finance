$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$gitDir = Join-Path $root ".git"
$hooksDir = Join-Path $gitDir "hooks"

if (-not (Test-Path $gitDir)) {
    throw "This folder is not a git repository. Run this script from the project root after cloning."
}

New-Item -ItemType Directory -Path $hooksDir -Force | Out-Null

$sourceHook = Join-Path $PSScriptRoot "git-hooks\post-merge"
$targetHook = Join-Path $hooksDir "post-merge"
Copy-Item -Path $sourceHook -Destination $targetHook -Force

Write-Host "Installed git hook: .git/hooks/post-merge"
Write-Host "After 'git pull', the app will auto-restart when backend/frontend files change."
