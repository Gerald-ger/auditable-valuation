#!/usr/bin/env bash
# Cold-starts the Stock Analysis Platform: backend + frontend + browser.
# macOS/Linux counterpart to start.bat.
#
# Unlike the Windows launcher, which opens two detached console windows, this
# keeps both servers in this terminal and shuts them down together on Ctrl-C —
# there is no cross-platform equivalent of `start "title" cmd /k` worth emulating.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="backend/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "No virtualenv at $PYTHON — see the Install section of README.md." >&2
  exit 1
fi

# uvicorn is given backend.main:app and run from the repo root, which is what
# makes the `backend` package importable. Do not add --app-dir.
"$PYTHON" -m uvicorn backend.main:app --port 8000 &
backend_pid=$!

(cd frontend && npm run dev) &
frontend_pid=$!

trap 'kill "$backend_pid" "$frontend_pid" 2>/dev/null || true' EXIT INT TERM

sleep 4
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://localhost:5173 >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open http://localhost:5173 || true
else
  echo "Open http://localhost:5173 in your browser."
fi

wait
