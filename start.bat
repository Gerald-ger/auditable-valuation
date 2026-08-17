@echo off
rem Cold-starts the Stock Analysis Platform: backend + frontend + browser.
cd /d "%~dp0"

rem Checked before launching anything. Without it a double-click opens two windows
rem that each fail with a raw interpreter error, which is a worse first impression
rem than the one line below. start.sh has had this check; these two had not.
if not exist "backend\.venv\Scripts\python.exe" (
    echo No virtualenv at backend\.venv\Scripts\python.exe - see the Install section of README.md.
    pause
    exit /b 1
)

start "Backend (FastAPI :8000)" cmd /k backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
start "Frontend (Vite :5173)" cmd /k "cd frontend && npm run dev"

echo Waiting for servers to start...
timeout /t 6 /nobreak >nul
start http://localhost:5173
