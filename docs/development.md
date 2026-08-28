# Hosting and development

Running this somewhere other than your own machine, and the two things about the dev loop that
are easy to get wrong. Split out of the README on 2026-08-28.

[← back to the README](../README.md)

---

## Hosting it

`docker build -t finance-analysis . && docker run -p 7860:7860 finance-analysis` serves the
whole app — API and UI — from **one process on one port**, with `DEMO_MODE=1` baked in.

That flag is what makes it safe to expose. The eight committed fixtures answer every request,
no credential is read, and nothing reaches a data vendor: serving *live* yfinance data from a
public host is an unresolved licensing question, recorded in
[docs/data-sources-review.md](data-sources-review.md) §3, and this image never asks it.

The backend serves `frontend/dist` itself when that directory exists, mounted after every
route. Nothing else was needed, because [frontend/src/api.js](../frontend/src/api.js) already
requests a relative `/api` — so a single-origin deployment has no second origin and no CORS
handshake at all. In development the directory does not exist and Vite serves the UI instead,
so the mount is simply absent.

**One caveat if you put it on the public internet.** This app is local-first and has no notion
of a session, so every visitor shares one database — anything saved in **Portfolio** is visible
to everyone on that instance until it restarts. `deploy/huggingface/` carries the two files a
Hugging Face Space needs, and says so on the page itself — **note that Hugging Face gated
Docker Spaces behind PRO in 2026**, so those two files are for a paid account. The `Dockerfile`
at the root needs no particular host; anything that builds a container will run it.

*The container has not been built on this machine, which has no Docker installed. Every step in
it either produces its artifact or fails at build time; none of them can fail quietly at run
time. It is written, not verified.*

## Development server

Both modes, not just the one above.

**The dev server owns port 5173 and will not move.** Vite is configured with `strictPort`, so a
port collision fails loudly at startup rather than sliding to 5174 — which used to leave the page
rendering normally with no data and no error, because the backend's CORS list named 5173 only.
The browser now talks to `/api` on its own origin and Vite proxies that to port 8000, so CORS is
not involved in development at all. Serving `dist/` from anywhere other than `npm run preview`
means supplying your own reverse proxy for `/api`.

**The backend does not hot-reload — restart it after changing any `backend/*.py`.** Vite
handles the frontend, so a JSX edit appears immediately and a Python edit does not, which is
the asymmetry that makes this easy to forget. The symptom is silence rather than an error: a
field added after the server booted is simply absent from responses, and a panel that reads
it renders nothing, which looks exactly like a feature that was never built.

`--reload` is **not** recommended here. Tried 2026-08-14: WatchFiles logged
`detected changes in 'backend\main.py'. Reloading...`, the replacement worker never started,
and the old process kept serving — with the log claiming it had reloaded. It also leaves an
orphaned child holding port 8000 after the parent dies, so the next start fails with
`WinError 10048` and the port has to be freed by hand.

Instead the app tells you. `GET /api/health` returns `source_changed_since_start`, a digest of
`backend/*.py` captured at import and re-checked per call, and the page shows a banner when it
flips. The digest reads text rather than bytes so a line-ending change — `git checkout` on this
repo rewrites LF as CRLF — does not raise a false alarm.
