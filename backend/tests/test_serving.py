"""Serving the built frontend from the API process, for a single-origin deploy.

The mount is one `if` and one line, and the thing that makes it safe is not in
either of them: it is safe because it is registered *last* and because every
route this app defines is under `/api/`. A mount at `/` is a prefix match against
everything, so it is a route of last resort only for as long as both of those
hold. Neither is expressed in code that would fail if it stopped being true --
someone adding `@app.get("/healthz")` below the mount would simply find it
returning HTML, with no error anywhere.

So these are drift tests. They assert the two invariants the mount rests on,
rather than the mount itself, which is trivial.

`frontend/dist/` is gitignored and only `npm run build` creates it, so it exists
on a developer machine that has built once and does not exist on the backend CI
runner. Every test here therefore holds in both states.
"""
from __future__ import annotations

from pathlib import Path

from starlette.routing import Mount

from backend import main

REPO_ROOT = Path(__file__).resolve().parents[2]

# The paths FastAPI registers for itself before any of ours. A mount at `/`
# placed last cannot shadow them either, but they are named here so the
# "everything else is /api" test does not have to pretend they do not exist.
FASTAPI_OWN = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def test_the_build_output_is_looked_for_where_vite_writes_it():
    """`vite build` has no `outDir` override, so it writes to `frontend/dist`."""
    assert main.FRONTEND_DIST == REPO_ROOT / "frontend" / "dist"


def test_the_mount_exists_exactly_when_the_build_output_does():
    """The conditional is the point: a dev checkout has no `dist/` and must boot.

    Asserting the mount unconditionally would fail on the CI runner, which never
    runs `npm run build` in the Python job; asserting its absence would fail on
    any machine that has built once. What is invariant is that the two agree.
    """
    mounts = [r for r in main.app.routes if isinstance(r, Mount)]
    assert len(mounts) == (1 if main.FRONTEND_DIST.is_dir() else 0)


def test_the_mount_is_registered_last():
    """Starlette matches in registration order, and `/` matches every path.

    A route added after this one is unreachable. That is the failure this test
    exists to make loud, because nothing else would: the route would resolve, and
    return the SPA's HTML with a 200.
    """
    if not main.FRONTEND_DIST.is_dir():
        return
    assert isinstance(main.app.routes[-1], Mount)


def test_every_route_this_app_defines_is_under_api():
    """The other half of why the mount is safe.

    `frontend/src/api.js` requests a relative `/api`, so single-origin serving
    works only while the API keeps that prefix to itself. A route added outside
    it would be shadowed by the mount on a deployment while continuing to work
    in development, where Vite serves `/` instead -- the worst shape of bug this
    arrangement can produce, since it appears only in the environment nobody
    runs tests against.
    """
    stray = [r.path for r in main.app.routes
             if not isinstance(r, Mount)
             and r.path not in FASTAPI_OWN
             and not r.path.startswith("/api/")]
    assert stray == []
