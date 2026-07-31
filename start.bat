@echo off
rem Cold-starts the Stock Analysis Platform: backend + frontend + browser.
cd /d "%~dp0"

start "Backend (FastAPI :8000)" cmd /k backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --port 8000
start "Frontend (Vite :5173)" cmd /k "cd frontend && npm run dev"

echo Waiting for servers to start...
timeout /t 6 /nobreak >nul
start http://localhost:5173
