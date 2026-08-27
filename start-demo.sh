#!/usr/bin/env bash
# Cold-starts the platform in DEMO MODE: the eight committed fixtures instead of
# a live data vendor. No API key, no network, no Ollama needed.
#
# Delegates to start.sh rather than copying it, so the virtualenv check, the
# Ctrl-C trap and the browser launch have one definition.
set -euo pipefail
cd "$(dirname "$0")"

export DEMO_MODE=1
exec ./start.sh
