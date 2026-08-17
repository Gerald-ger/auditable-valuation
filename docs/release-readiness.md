# Release readiness — what works for someone else, and what does not

**Scope decision, 2026-08-17:** this project's target changed from *portfolio piece only*
(2026-08-14) to **a runnable source project** — a stranger clones it, follows the README, and
it starts on Windows, macOS or Linux. Docker images and binary releases remain out of scope.

This file is the honest inventory. Anything listed under *Deliberately not done* is a decision
with a stated restart condition, not an oversight.

---

## Done

### Packaging and imports — 2026-08-17

| | |
|---|---|
| `backend/` is a real Python package | `pyproject.toml` + `backend/__init__.py`; sibling imports rewritten to `from backend import …` across 5 modules and 12 test files |
| The `sys.path` hack is gone | removed from `backend/tests/conftest.py`; `pip install -e .` replaces it |
| Launch command | `uvicorn backend.main:app`, no `--app-dir`, run from the repo root |
| Dependency files | `requirements.post-openbb.txt` → `requirements.txt`; the pre-OpenBB rollback snapshot deleted (it is in git history and, per the old README, would not boot the app); ruff's pin moved out of the CI workflow into `requirements-test.txt` |
| CI | now runs `pip install -e .` so collection does not depend on the working directory |

**Verified:** 409 tests pass (408 before, +1 new guard), ruff clean, and `from backend import
scoring` works from an unrelated working directory — which fails without the package.

`backend/__init__.py` is empty and **must stay**. Deleting it keeps all 409 tests green (pytest
puts the repo root on `sys.path`, so `backend` still resolves as a namespace package) while
silently breaking `pip install -e .`. The test suite does not protect it.

### Making it runnable by someone else — 2026-08-17

| | |
|---|---|
| Port/CORS silent failure | fixed at the root. `frontend/vite.config.js` proxies `/api` to the backend, so the browser makes same-origin requests and CORS is not involved in development. `strictPort: true` turns a port collision into a loud startup failure. `frontend/src/api.js` now uses a relative `/api` base. |
| Cross-platform start | `start.sh` added for macOS/Linux, alongside `start.bat` / `start.ps1` |
| Node version | `engines: { node: ">=22" }` added to `frontend/package.json` — previously Node 22 existed only in prose and CI |
| Stale launch commands | the user-facing banner in `frontend/src/App.jsx` and the docstring in `backend/main.py` still printed `uvicorn main:app --app-dir backend`, which fails under the new packaging. Both fixed. |
| README | Prerequisites / Install / Run moved from line ~206 to the top; Windows and macOS/Linux install paths given equal billing; the OpenBB section no longer tells you to install a package that `requirements.txt` already pins, nor warns of a dependency downgrade that can no longer happen; FMP key setup expanded from one table cell into steps with the actual `user_settings.json` shape (schema verified against the installed `openbb_core`) |

**The old failure mode, for the record:** Vite silently moved to 5174 when 5173 was taken, while
the backend allowed exactly two origins. The page rendered normally, with no data and no error
message. That is close to undiagnosable for a first-time user, and it is why the fix is a proxy
rather than adding 5174 to the CORS list.

---

## Not done — needs the GitHub web UI

There is no `gh` CLI on the development machine, so these are manual:

- [ ] **Change the default branch from `openBB-testing` to `main`.** A visitor currently lands
      on a branch named after an experiment. `main` is 1 commit behind and needs merging first.
- [ ] **Repo description** — currently a keyword dump; should be one sentence.
- [ ] **Topics** — empty.
- [ ] **A screenshot or GIF.** The only image in the repo is `frontend/public/favicon.svg`. For
      a UI project this is the single highest-value addition to the README.

## Needs a decision

- [ ] **`.claude/agents/*` is recoverable from public git history.** Commit `32a19c3` removed
      the directory, but `7edf9cf` added it, so a clone still carries it. The content is agent
      definition markdown — **not secrets, not credentials**. Removing it means another
      `git filter-repo` history rewrite and a force-push. Recorded rather than acted on; the
      cost/benefit is a judgement call.

---

## Deliberately not done

Each carries the condition that would reopen it.

| Item | Why not | Reopen when |
|---|---|---|
| Docker / docker-compose | The install is four commands; a container mainly hides the Python 3.14 requirement rather than solving it | Someone asks for a reproducible environment, or CI needs to test the runtime set |
| Git tags, semver, GitHub Releases | There are no consumers pinning a version | Someone depends on a specific version |
| `CONTRIBUTING.md`, `SECURITY.md`, issue/PR templates | Single author, no inbound contributions | A first external issue or PR arrives |
| Relaxing Python below 3.14 | The floor is `requires-python = ">=3.14"` in `pyproject.toml`, chosen to match the only tested configuration (3.14.6 locally, 3.14 in CI) — **not** a dependency constraint. Checked against PyPI: `pandas==3.0.5` ships wheels back to cp311 and declares `>=3.11`; `numpy==2.5.1` ships back to cp312 and declares `>=3.12`. So 3.12/3.13 would plausibly work; lowering the floor honestly means running the suite there first, which is a task, not a config edit | Someone is actually blocked — then test on 3.12 and 3.13 and lower the floor to what passes |
| CI OS / version matrix | One Linux runner already catches import and logic regressions | The Windows-only launchers break, or a platform bug ships |
| Backend `.env` / env-var config | Local single-user tool; module constants are legible and the real defect was the same literal repeated in six files, which the proxy change removed | The app needs to run anywhere other than localhost |
| `index.css` split (2,033 lines), `ModelsTab.jsx` (1,033) / `ScorecardTab.jsx` (761) decomposition | Real single-contributor risks, but there are no component tests, so the diff would be unverifiable | A second contributor joins, or component tests exist |

---

## Known limitations a reader should know about

- **CI never installs `backend/requirements.txt`.** It installs the smaller
  `requirements-test.txt`. A broken runtime pin — or a missing runtime dependency such as
  `openbb` — passes CI green. The runtime set is only exercised by hand.
- **The 16 `network`-marked tests do not run in CI.** They are deselected by `pytest.ini` so the
  suite is offline and deterministic; they exist to detect yfinance changing shape, which means
  that detection only happens when someone runs them deliberately.
- **No HTTP-layer tests.** Endpoints are thin wrappers over tested functions and were smoke-
  tested live instead. `httpx` (needed by Starlette's `TestClient`) is still not installed.
- **AI streaming has never been run against a live model** on this machine — Ollama is not
  installed, so only the offline degradation path is verified. The Vite proxy pipes responses
  rather than buffering them, but progressive NDJSON delivery through the proxy is unverified
  end-to-end for the same reason.
- **`start.sh` has never been run on its target platforms.** Development is on Windows, so what
  is verified is: it parses (`bash -n`), the missing-virtualenv guard exits 1 with a pointer to
  the README, `npm --prefix frontend run dev` is a valid invocation, and the file ships mode
  `100755` with LF endings. What is *not* verified is the Ctrl-C path — a control experiment
  showed that even the minimal textbook `trap` + `kill` pattern fails to reap a background child
  under Git Bash, so this environment cannot distinguish a script bug from an MSYS signal-
  emulation artifact. The script is therefore shaped to need as little of that behaviour as
  possible: Vite runs in the *foreground* so Ctrl-C reaches it through the terminal directly,
  leaving the trap responsible only for a single backend process with no children.
- **yfinance is personal-use-only.** Running it locally for yourself is fine; hosting it or
  offering it as a service is a blocker, not a bug. See
  [data-sources-review.md](data-sources-review.md) §3 — decision taken 2026-08-14 to record it
  and keep yfinance.
- **First run is slow and says nothing about it.** The first search pays a ~4–5 s OpenBB import
  plus an SEC fetch of ~10,400 symbols, with no progress indication in the UI. If that fetch
  fails, typo-tolerant search silently does nothing until the next restart.
