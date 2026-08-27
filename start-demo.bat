@echo off
rem Cold-starts the platform in DEMO MODE: the eight committed fixtures instead
rem of a live data vendor. No API key, no network, no Ollama needed.
rem
rem Delegates to start.bat rather than copying it, so the virtualenv check, the
rem ports and the browser launch have one definition.
rem
rem setlocal, because plain `set` persists in the invoking cmd session: running
rem this from an open prompt left DEMO_MODE=1 behind, and capture_fixtures.py in
rem that same window would then have rewritten the golden fixtures from
rem themselves. Measured 2026-08-27 -- with setlocal the `call`ed script and the
rem two `start`ed windows both still see the variable, and the parent shell does
rem not. start-demo.sh never had this problem: export+exec is scoped to the child.
setlocal
set DEMO_MODE=1
call "%~dp0start.bat"
