# The Hugging Face Space's build. Copy this file, and the README.md beside it,
# into the Space repo — not into this one.
#
# Why the Space is a separate repo rather than a push of this one: a Docker Space
# is configured by YAML front matter at the top of its README.md, and GitHub
# renders front matter as a table above everything else. Putting it in this
# repo's README would park a config block above the project title, on the one
# page every visitor sees. So the Space carries its own two files and clones the
# code, and this repository stays as it reads today.
#
# It clones `main`, so rebuilding the Space is how it picks up new work. Pin it
# by changing the branch to a tag — `--branch v0.1.0` — if a fixed demo is ever
# wanted; the *numbers* are already fixed by demo mode either way.
#
# This mirrors the Dockerfile at the root of the application repo. Kept separate
# rather than shared because a Docker build can only see its own context, and
# the Space's context is these two files.

# ── Stage 1: clone, and build the frontend ───────────────────────────────────
FROM node:22-slim AS frontend

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/Gerald-ger/finance-analysis-platform /src

WORKDIR /src/frontend
RUN npm ci && npm run build


# ── Stage 2: the application ─────────────────────────────────────────────────
# 3.14 is `requires-python` in pyproject.toml and the only configuration the
# suite has run on.
FROM python:3.14-slim

# Spaces runs the container as uid 1000, and the app writes: store.py creates
# `backend/data/demo.db` on first use.
RUN useradd --create-home --uid 1000 app
USER app
ENV PATH="/home/app/.local/bin:${PATH}"

WORKDIR /home/app/src

# `backend/` and `frontend/dist/` must stay siblings: main.py resolves
# FRONTEND_DIST as `Path(backend/main.py).parent.parent / "frontend" / "dist"`.
COPY --from=frontend --chown=app:app /src/pyproject.toml ./
COPY --from=frontend --chown=app:app /src/backend backend/
COPY --from=frontend --chown=app:app /src/frontend/dist frontend/dist

# The full runtime set. openbb and its siblings are never imported under
# DEMO_MODE, but installing less would mean the hosted environment is no longer
# the one the test suite runs against.
RUN pip install --no-cache-dir --user -r backend/requirements.txt \
 && pip install --no-cache-dir --user -e .

# The flag that makes this safe to expose: the eight committed fixtures answer
# every request, no credential is read, and nothing reaches a data vendor.
ENV DEMO_MODE=1
ENV PYTHONUNBUFFERED=1

# Must match `app_port` in the Space's README.md front matter.
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
