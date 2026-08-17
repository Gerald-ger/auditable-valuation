# Launches backend (port 8000) and frontend (port 5173) in separate windows.
$root = $PSScriptRoot

# Same guard as start.bat and start.sh: fail with one readable line rather than
# spawning two windows that each die on a missing interpreter.
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "No virtualenv at $python - see the Install section of README.md."
    exit 1
}

Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root'; & '$python' -m uvicorn backend.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root\frontend'; npm run dev"
Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"
