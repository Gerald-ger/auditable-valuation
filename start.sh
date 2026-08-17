#!/usr/bin/env bash
# Cold-starts the Stock Analysis Platform: backend + frontend + browser.
# macOS/Linux counterpart to start.bat.
#
# Shape: the backend runs in the background and Vite runs in the FOREGROUND.
# That is deliberate. Ctrl-C then reaches Vite directly through the terminal, so
# the one process with a child of its own (npm -> vite) needs no reaping, and the
# trap only has to deal with the single backend process. Backgrounding both meant
# killing a subshell whose npm child could outlive it, and an orphaned Vite still
# holding port 5173 is now a hard startup failure rather than a silent drift to
# 5174 — see frontend/vite.config.js.
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
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM

# Detached so it cannot block startup; it outlives nothing important.
(
  sleep 4
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:5173 >/dev/null 2>&1
  elif command -v open >/dev/null 2>&1; then
    open http://localhost:5173
  else
    echo "Open http://localhost:5173 in your browser."
  fi
) &

# Foreground on purpose — see the note at the top. Ctrl-C stops Vite, the trap
# then stops the backend, and the script exits.
npm --prefix frontend run dev
