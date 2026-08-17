# Launches backend (port 8000) and frontend (port 5173) in separate windows.
$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root'; & '$root\backend\.venv\Scripts\python.exe' -m uvicorn backend.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$root\frontend'; npm run dev"
Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"
