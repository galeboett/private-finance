param(
    [switch]$Background,
    [switch]$SkipBuild,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$nodeDir = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$pnpm = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd"
$port = 8000

if (-not (Test-Path $python)) {
    $python = "python"
}

if (Test-Path $nodeDir) {
    $env:Path = "$nodeDir;$env:Path"
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
    & $pnpm approve-builds --all
    & $pnpm build
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
