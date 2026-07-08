$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$nodeDir = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$pnpm = "C:\Users\YehMa\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd"
$port = 8000

$env:Path = "$nodeDir;$env:Path"

Write-Host "Installing frontend dependencies if needed..."
Push-Location "$root\frontend"
if (-not (Test-Path "node_modules")) {
  & $pnpm install
}
& $pnpm approve-builds --all
& $pnpm build
Pop-Location

Write-Host "Preparing backend environment..."
Push-Location "$root\backend"
if (-not (Test-Path ".venv")) {
  & $python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -e .[dev]
Pop-Location

Write-Host "Checking for an existing local backend on port $port..."
$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
  if ($process) {
    Write-Host "Stopping stale local backend process $($process.Id) ($($process.ProcessName)) on port $port..."
    Stop-Process -Id $process.Id -Force
    Start-Sleep -Milliseconds 500
  }
}

Write-Host "Starting backend at http://127.0.0.1:$port"
Push-Location "$root\backend"
& .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port $port
Pop-Location
