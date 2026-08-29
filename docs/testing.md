# Tests

What the suite covers, what it deliberately does not, and why some of it exists. Split out of
the README on 2026-08-28; the three commands to run it are still
[there](../README.md#tests).

[← back to the README](../README.md)

---

`pytest` is not in `requirements.txt` — install the test set once, then run:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-test.txt

backend\.venv\Scripts\python.exe -m pytest          # 762 tests, offline, seconds
backend\.venv\Scripts\python.exe -m pytest -m network   # live yfinance contract checks
cd frontend; npm test                                   # 200 tests
```

Of the 789 collected, 27 are `network`-marked and deselected by default. One more skips
unless OpenBB is installed — it checks that the settings path `comps.py` computes still
matches OpenBB’s own constant, which is unanswerable without it, so CI reports 761 and a skip.

The frontend suite runs in vitest's default `node` environment; seven component
suites opt into a DOM per file with a `@vitest-environment jsdom` docblock —
`ErrorBoundary.test.jsx`, `ModelsTab.test.jsx`, `PortfolioTab.test.jsx`,
`PriceChart.test.jsx`, `ScorecardTab.test.jsx`, `SettingsTab.test.jsx`,
`TrackerTab.test.jsx`. Rendering is
`createRoot` + React 19's own `act`
([frontend/src/test-utils.js](../frontend/src/test-utils.js), 53 lines) rather than a
testing library.

CI runs on every push ([.github/workflows/ci.yml](../.github/workflows/ci.yml)) and gates more
than the tests: `ruff check backend/` on the backend, and `npm run lint` (oxlint) plus
`npm run build` on the frontend. Run those two lint commands before pushing or a green
local suite will still fail CI.

Both jobs run on **ubuntu, Windows and macOS** with `fail-fast: false`, so one platform
failing still reports the other two. Since 2026-08-28 the backend job also runs **Python 3.12
and 3.13** on ubuntu, which is what keeps the lowered `requires-python` floor honest — five
backend legs and three frontend, eight in all. The interpreters are added on one OS rather
than on all three because what differs between them is the language, not the platform; nine
backend legs would buy the same answer three times.

Lint runs once, on ubuntu and on 3.14 — it reads the same files everywhere. So does the
coverage upload, which additionally *has* to be pinned to one interpreter: three ubuntu legs
racing to upload one artifact name is an error, not a duplicate.

**Coverage** is measured but not gated:

```powershell
backend\.venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing
cd frontend; npm run test:coverage
```

First reading, 2026-08-28: **82%** backend, **69.8%** frontend lines. There is deliberately no
threshold. A percentage target is satisfied by an assertion that cannot fail — this repo found
two of those by mutation the day before — so the number is here to locate the zeroes, not to be
hit. What it located: the deterministic engine is 96–100% covered and every layer around it is
thinner, and four frontend files are at 0% — `api.js`, `ScreenerTab.jsx`, `ChatBox.jsx`,
`Debate.jsx`. `api.js` is the interesting one: every network call goes through it and every
suite mocks it, so no test has ever executed it.

A second workflow
([.github/workflows/runtime-install.yml](../.github/workflows/runtime-install.yml)) installs
`backend/requirements.txt` — the 107-pin runtime set, which the job above never touches, since
it installs the six-entry test set instead — then imports the app and OpenBB under it. Until
2026-08-27 a broken runtime pin passed CI green and the first report would have come from
somebody who could not install this. It runs when a pin file changes and once a week rather
than on every push, because those are the only two ways the set can break.

`tests/test_plausibility.py` encodes the acceptance criteria written in
[docs/scoring-system-design.md](scoring-system-design.md) §5.2 — "RIVN … Tier 3–5",
"no bankrupt-adjacent name outranks a mega-cap compounder". It exists because **golden
snapshots catch unintended change and are structurally blind to a wrong answer that never
changes**: RIVN scored 74/Tier A against a spec of Tier 3–5, and the golden had recorded
74/A as the *expected* value since the day it was written. Two of those tests (three cases,
one being parametrised) shipped `xfail(strict=True)` on 2026-08-10 and were unmarked the
same day when the calibration landed — a strict xfail reports the breach every run and
errors the moment it is fixed.

The suite runs entirely against eight real `get_fundamentals` payloads committed under
`backend/tests/fixtures/` (297 KB — the fixtures directory as a whole is 18 files /
421 KiB), covering the technology, bank, REIT, energy, pre-profit and HK classification
paths — two HK fixtures now, `0700_HK` reporting CNY and `0002_HK` reporting HKD. Golden
snapshots of every scorecard are checked in; after a deliberate methodology change
regenerate them and **review the diff — that diff is the record of what your change did
to every score**:

```powershell
$env:UPDATE_GOLDEN=1; backend\.venv\Scripts\python.exe -m pytest; $env:UPDATE_GOLDEN=''
```

Fixtures themselves are regenerated with `backend\tests\capture_fixtures.py`.
The `network`-marked tests are deselected by default and exist to tell you when
yfinance changes shape — it has already shipped two different news payloads.

## Demo mode fidelity

Moved here from the README on 2026-08-28: it is evidence about correctness, which is what
this file is for.

**What the numbers do and do not carry.** The discount-rate sources stay honest rather than
claiming a fetch that never happened: US names report `platform_default`, and the CNY and HKD
names report `cgb_10y_stored_less_spread` / `hkgb_10y_stored_less_spread` — "the last good
reading rather than today's", which is exactly what a pinned reading is. Prices are the captured
ones, not refreshed. The one cross-currency pair these fixtures need, CNY→HKD for `0700.HK`, uses
spot on the capture date. Measured against the same engine run given those same readings,
**every number is identical on all eight** — every fair value, all 25 sensitivity cells, every
diagnostic, the equity bridge, and every pillar and composite score. The only field that moves
is the source label above, and it moves toward honesty: demo does not claim a fetch that never
happened.

**The peer-beta path does not diverge either, and it is worth saying why.** `XOM` reports a beta
of 0.173, below the credibility floor, so live mode reaches for peer snapshots to build an
unlevered peer median — and demo mode can resolve none. It makes no difference:
[`resolve_beta`](../backend/financial_models.py) puts the **regression** at the top of its ladder,
and peers are consulted only when there is no series to regress. Every fixture carries its own
5y/1wk bars, so all eight resolve `beta_source: "computed"` and the peer list is never reached.

