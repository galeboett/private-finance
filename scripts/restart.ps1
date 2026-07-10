param(
    [switch]$Background,
    [switch]$SkipBuild,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$port = 8000

# Tools resolve from PATH so any collaborator can run this from a clean machine.
# Optional overrides: PF_PYTHON, PF_PNPM, PF_NODE_DIR environment variables.
$python = if ($env:PF_PYTHON) { $env:PF_PYTHON } else { "python" }
$pnpm = if ($env:PF_PNPM) { $env:PF_PNPM } else { "pnpm" }

if ($env:PF_NODE_DIR -and (Test-Path $env:PF_NODE_DIR)) {
    $env:Path = "$($env:PF_NODE_DIR);$env:Path"
}

if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
    throw "Python was not found on PATH. Install Python 3.11+ or set the PF_PYTHON environment variable."
}

$useNpmFallback = $false
if (-not (Get-Command $pnpm -ErrorAction SilentlyContinue)) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "pnpm was not found; falling back to npm."
        $pnpm = "npm"
        $useNpmFallback = $true
    }
    else {
        throw "Neither pnpm nor npm was found on PATH. Install Node.js (https://nodejs.org) or set PF_PNPM."
    }
}

function Stop-BackendOnPort {
    param([int]$ListenPort)

    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) {
        return
    }

    $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Stopping backend process $($process.Id) ($($process.ProcessName)) on port $ListenPort..."
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 500
    }
}

if (-not $SkipBuild) {
    Write-Host "Building frontend..."
    Push-Location "$root\frontend"
    if (-not (Test-Path "node_modules")) {
        & $pnpm install
    }
    if (-not $useNpmFallback) {
        & $pnpm approve-builds --all
    }
    & $pnpm run build
    Pop-Location
}

if (-not $SkipDeps) {
    Write-Host "Preparing backend environment..."
    Push-Location "$root\backend"
    if (-not (Test-Path ".venv")) {
        & $python -m venv .venv
    }
    & .\.venv\Scripts\python.exe -m pip install -e .[dev]
    Pop-Location
}

Stop-BackendOnPort -ListenPort $port

$uvicorn = Join-Path $root "backend\.venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    throw "Backend virtual environment is missing. Run .\run.ps1 once to create it."
}

Write-Host "Starting backend at http://127.0.0.1:$port"

if ($Background) {
    Start-Process -FilePath $uvicorn -ArgumentList @("app.main:app", "--host", "127.0.0.1", "--port", "$port") -WorkingDirectory (Join-Path $root "backend") -WindowStyle Hidden
    Write-Host "Backend started in the background."
    return
}

Push-Location "$root\backend"
& $uvicorn app.main:app --host 127.0.0.1 --port $port
Pop-Location
