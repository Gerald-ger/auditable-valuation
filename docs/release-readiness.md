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

### Local tooling removed from git history — 2026-08-17

38 `.claude/agents/*.md` files were committed in the first commit and deleted later, but a
deletion only adds a "these are gone now" entry to the chain — it does not reach back into the
commit that introduced them. Anyone who cloned the repo could still read every one of them with
a single `git show`. They were removed from the whole history with `git filter-repo` and the
result force-pushed.

The content was agent role definitions in markdown — no secrets, no credentials, no personal
data — so this was housekeeping, not an incident.

**What a rewrite does and does not do.** It removes the files from every commit going forward
from the rewrite, and it changes every commit hash after the first affected commit. It does
*not* undo the exposure: the files were public from 2026-07-31 to 2026-08-17 and anything that
cloned, forked, cached or scraped the repo in that window still has them. Treat already-published
content as published.

**Verified, not assumed: GitHub still serves the removed files.** A force-push makes old commits
unreachable from any branch; it does not make GitHub collect them. Immediately after the rewrite,
both of these still returned data for the pre-rewrite commit `7edf9cf` (a hash that no longer
exists in this repository):

```
GET repos/:owner/:repo/commits/7edf9cf
GET repos/:owner/:repo/contents/.claude/agents/<file>.md?ref=7edf9cf
```

So the rewrite works for anyone who clones, and does nothing against anyone who requests an old
SHA directly. Only GitHub Support can force garbage collection.

**Decision, 2026-08-17: stop here.** Deliberate, and taken after measuring rather than guessing:

- *Nothing sensitive is in the files.* 62,544 words of agent role-definition markdown. A scan for
  credential patterns returned 141 hits, all false positives — CSS `design tokens` and LLM
  billing `tokens`. The only API key is the placeholder `'YOUR_SEARCH_API_KEY'`. No credentials,
  no personal data, nothing about this project's systems.
- *Reading it requires already knowing the 40-character SHA.* That hash appears in no file in
  this repository, in no commit message, and in no entry of the repo's public events API. The
  one surviving route is GH Archive's BigQuery corpus of historical GitHub events, which takes a
  deliberate query aimed at this repository. Nobody arrives there by accident.
- *The one real issue is provenance, not security.* Those files are a third-party agent pack in a
  repository licensed AGPL-3.0. They are no longer in the tree, so today's licence grant does not
  reach them — a loose end in attribution, not an incident.
- *It cannot recur.* [.gitignore](../.gitignore) covers `.claude/agents/` and
  `**/.claude/settings.local.json`.

The hash is written out above on purpose. Omitting it would not make the content harder to reach
— it is in the public event archive either way — and would leave a future reader unable to check
any of this.

**Reopen if** the content turns up redistributed somewhere, or the pack's author raises a licence
claim. The options then are a GitHub Support ticket, or deleting and recreating the repository —
the latter is total and instant, and unusually cheap here: stars, forks, watchers and issues are
all zero, and the URL is unchanged by a same-name recreation. The cost is the 2026-07-31 creation
date and the traffic history.

---

## Repository settings — done 2026-08-17

Done with the `gh` CLI once it was installed and authenticated:

- [x] **Default branch is `main`.** It was `openBB-testing`, so visitors landed on a branch named
      after an experiment. `main` was fast-forwarded to the current tip (no merge commit, no
      divergence), made default, and `openBB-testing` deleted after confirming both refs pointed
      at the same commit.
- [x] **Description** rewritten from a keyword dump into a sentence describing what the project
      is. The keywords it used to carry became topics, which is where GitHub actually searches
      them.
- [x] **14 topics** set.

---

### Screenshots — done 2026-08-17

Five captures in `docs/images/`, one per tab, live in the README under *What it looks like*,
directly beneath the disclaimer so a visitor sees the product before the install steps.

They could not be automated: the tab and ticker are React state rather than URL parameters, so
a headless browser only ever reaches the Tracker tab on its default ticker. Every shot needed a
real click. If these are ever refreshed, three things are worth repeating:

- **Verify content, not filenames.** The first attempt had `portfolio.png` and `screener.png`
  holding each other's screenshot, and a later one arrived as `protfolio.png`. Both passed a
  file-exists check and both were wrong. Open each image.
- **Crop the two dense tabs.** Financial Models and Scorecard are long, and GitHub renders
  README images at about 890 px wide — a 1400 px capture lands at 63% and its body text becomes
  unreadable. They are cropped to the part that carries the argument (`models.png` ends after
  the trust checks, `scorecard.png` after the unexplained-gap line). The cut lines were chosen
  by scanning each row for text and cutting inside a blank band, not by eye. If a crop changes
  what is visible, **the caption has to change with it** — the Financial Models caption used to
  describe an equity bridge that the crop removed.
- **Keep the demo portfolio plausible.** The first version used a cost basis of 999 for XOM,
  which trades near 160, so the position showed −84% and dragged the total to −35%. On a project
  whose pitch is auditable valuation, a number that could not have happened reads as a defect.
  The published version uses 175: XOM shows −8.5% in red, the total +41.6% in green, and both
  states of the P&L styling are visible.

Positions in the screenshot are fabricated, and the README says so beneath the image.

---

### Demo mode — done 2026-08-27

`DEMO_MODE=1`, or `start-demo.bat` / `./start-demo.sh`. Serves the eight committed fixtures
instead of yfinance: no API key, no network, no Ollama, nothing to configure.

| | |
|---|---|
| Works in full | Scorecard, Financial Models, Portfolio |
| Withheld, with an on-screen notice | Tracker, Screener |
| Why withheld | the capture carries weekly closes with no OHLCV, no news items, no SEC filings, and eight *sectors* rather than a peer group. A stripped chart reads as a broken chart, so the tab is refused rather than drawn with holes in it |
| Data vintage | `2026-08-10` to `2026-08-19`, per `backend/tests/fixtures/PROVENANCE.md`. Cards carry `data_as_of`; the banner names the dates |
| Isolation | `store.DB_PATH` points at `backend/data/demo.db`, so scores, positions and drawings never reach `app.db` |
| Accuracy | given the same rate readings, identical numbers to live on all eight fixtures. Only `risk_free_source` differs, reporting `platform_default` / `*_stored_less_spread` rather than claiming a fetch |

**What it does not do is lower the barrier to *start*.** It still needs Python 3.14, the
full dependency install and Node — it removes the configuration, not the toolchain. Its
value is that it is the data path a hosted demo would need: no credentials, no vendor rate
limits, deterministic across visitors and across days. Whether to host is a separate
decision, and one this file's own note on yfinance's terms bears on.

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
| `index.css` split (2,033 lines), `ModelsTab.jsx` (1185) / `ScorecardTab.jsx` (787) decomposition — re-measured 2026-08-26 | Real single-contributor risks, but there are no component tests, so the diff would be unverifiable | A second contributor joins, or component tests exist |

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
