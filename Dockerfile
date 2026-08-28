# A single-origin container: FastAPI serves both the API and the built UI.
#
# This exists for one thing — a hosted demo. `DEMO_MODE=1` below is what makes
# that safe to expose: the eight committed fixtures answer every request, no
# credential is read, and nothing reaches a data vendor. Serving live yfinance
# data from a public host is an unresolved licensing question recorded in
# docs/data-sources-review.md §3; this image never asks it.
#
# Not verified locally. It was written on a machine with no Docker installed, so
# the first build is the first test. If it fails, it fails at build time on the
# host rather than silently at runtime — every step here either produces its
# artifact or stops.

# ── Stage 1: the frontend bundle ─────────────────────────────────────────────
# Built here rather than committed: `frontend/dist/` is gitignored, and a
# checked-in bundle is a second source of truth that drifts from `src/`.
FROM node:22-slim AS frontend

WORKDIR /build

# The manifest and lockfile first, so `npm ci` is cached until a dependency
# actually changes rather than on every source edit.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ── Stage 2: the application ─────────────────────────────────────────────────
# `requires-python` is `>=3.12` since 2026-08-28, and 3.12, 3.13 and 3.14 are all
# exercised in CI. An image has to choose one anyway, so it takes the newest — the
# configuration this is developed on, and the one the other two are checked against.
FROM python:3.14-slim

# Hugging Face Spaces runs the container as uid 1000, and this app writes:
# store.py creates `backend/data/demo.db` on first use. Owning the tree by that
# user is what keeps the first scorecard view from failing on a read-only path.
RUN useradd --create-home --uid 1000 app
USER app
ENV PATH="/home/app/.local/bin:${PATH}"

WORKDIR /home/app/src

# Requirements before source, for the same caching reason as `npm ci` above.
# The full runtime set, deliberately: openbb and its ~20 sibling packages are
# never imported under DEMO_MODE — all four import sites are inside functions
# the flag short-circuits — but installing a smaller set would mean the hosted
# environment is no longer the one the suite runs against.
COPY --chown=app:app backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app backend/ backend/
COPY --chown=app:app --from=frontend /build/dist frontend/dist

# What makes `backend` importable without a sys.path hack. The README and CI
# both do this; `uvicorn backend.main:app` from this directory depends on it.
RUN pip install --no-cache-dir --user -e .

# The layout main.py resolves against: FRONTEND_DIST is
# `Path(backend/main.py).parent.parent / "frontend" / "dist"`, so `backend/` and
# `frontend/dist/` must stay siblings. They are, above — do not flatten them.

ENV DEMO_MODE=1
ENV PYTHONUNBUFFERED=1

# 7860 is the Spaces default. A Space's README.md must carry a matching
# `app_port`; other hosts generally inject $PORT instead, in which case override
# this command rather than editing it.
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
