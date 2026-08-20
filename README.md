# Finance Analysis Platform

A local website for tracking stocks, explaining price moves with news, chatting with a
local AI financial expert, and running investment-banking financial models — powered by
the methodology in [docs/financial-models-reference.md](docs/financial-models-reference.md).

> ### Decision support only — not certified financial advice.
>
> The caveat the app itself attaches to every scorecard, verbatim from
> [backend/scoring.py](backend/scoring.py):
>
> *"This score is a snapshot of current fundamentals, valuation and price momentum against
> heuristic healthy ranges. It is NOT a prediction or a guarantee of future returns; it does
> not model catalysts, competitive shifts, or macro regime changes. Coverage and data quality
> limits apply."*
>
> Read [Notes & limitations](#notes--limitations) before relying on any number here. Licensed
> under [AGPL-3.0](LICENSE); see [Licence and data provenance](#licence-and-data-provenance)
> for what the licence does *not* cover.

## What it looks like

![Scorecard tab: composite score, pillar breakdown and valuation range](docs/images/scorecard.png)

**Scorecard** — every company gets a 0-100 composite built from five weighted pillars, with
each metric's raw value and its score shown side by side. The weights change with the
company's classification, so a bank is not judged on the ratios that suit a software firm.
The football field underneath places today's price against DCF, comps and analyst ranges.

![Financial Models tab: a two-stage FCFF DCF with every assumption and its source, and the trust checks that test the result](docs/images/models.png)

**Financial Models** — a two-stage FCFF DCF you can audit rather than trust. Every assumption
carries the source it came from, down to the vintage of the equity risk premium. The trust
checks then turn the model on itself: how much of the value sits in the terminal year, what
exit multiple that implies, and what perpetual growth rate today's price would require —
7.3% here, against an economy that grows 4%.

![Tracker tab: price chart with indicators, SEC filing markers and news](docs/images/tracker.png)

**Tracker** — candles with moving averages, RSI and MACD, SEC filing markers on the timeline,
and the news that explains a move. Drawings persist and are fed to the AI as context.

![Screener tab: many tickers scored and ranked in one pass](docs/images/screener.png)

**Screener** — the same deterministic engine run over a watchlist, grouped by classification
so like is compared with like.

![Portfolio tab: holdings, weights and concentration](docs/images/portfolio.png)

**Portfolio** — holdings and watchlist with position weights and concentration. The positions
shown are fabricated for the screenshot.

## Prerequisites

| | |
|---|---|
| **Python 3.14** | Enforced by `requires-python = ">=3.14"` in `pyproject.toml`, so `pip install -e .` stops with a clear version message rather than failing obscurely later. The floor is deliberate but *not* dependency-imposed: it matches the only configuration this project is ever run on (3.14.6 locally, 3.14 in CI). The heaviest pins are looser than that — `pandas==3.0.5` publishes wheels back to cp311 and `numpy==2.5.1` back to cp312 — so 3.12 or 3.13 may well work. Nobody has tried, which is exactly why the declared floor does not pretend otherwise. |
| **Node 20.19+ or 22.12+** | The odd-looking floor is the toolchain's own, not a preference: Vite 8, oxlint and `@vitejs/plugin-react` all declare `^20.19.0 \|\| >=22.12.0`. Mirrored in `engines` in [frontend/package.json](frontend/package.json). npm warns rather than refuses unless you set `engine-strict`, so on 22.0–22.11 `npm install` still reports success and you find out later, if at all. Nobody has run that range — developed on 24, CI on 22 (which resolves to a 22.12+ release), so it is untested rather than known-broken. |
| Ollama | Optional. The AI features disable cleanly without it and everything else works — see [Install guidance](#install-guidance). |
| FMP API key | Optional, free tier. Without one you lose automatic peer discovery and nothing else — see [Credentials](#credentials). |

## Install

**Windows (PowerShell)**

```powershell
git clone https://github.com/Gerald-ger/finance-analysis-platform.git
cd finance-analysis-platform

python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e .
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

cd frontend; npm install; cd ..
```

**macOS / Linux**

```bash
git clone https://github.com/Gerald-ger/finance-analysis-platform.git
cd finance-analysis-platform

python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e .
backend/.venv/bin/python -m pip install -r backend/requirements.txt

(cd frontend && npm install)
```

The only difference between the two is the interpreter path — `backend\.venv\Scripts\python.exe`
on Windows, `backend/.venv/bin/python` elsewhere. Command examples further down use the Windows
form; substitute throughout. The Python and JavaScript themselves are platform-neutral, and CI
runs the whole suite on Linux.

**Why `pip install -e .`:** it puts `backend` on the path as a real package, which is what lets
`from backend import scoring` work from anywhere — a script, a notebook, a scheduled job — rather
than only from inside the directory. Without it the app still runs, but only from the repo root.

**Why it goes first:** `requires-python` is the version gate, and `-e .` is the step that reads
it. Run first, a wrong interpreter is rejected in seconds — measured on 3.11, 8.8 s to
`ERROR: Package 'finance-analysis-platform' requires a different Python: 3.11.3 not in '>=3.14'`.
Run last, you pay the whole 107-package install before that same message arrives. It needs
nothing from `requirements.txt` to build: into an empty venv it installs exactly one
distribution, itself.

**Which requirements file:** `requirements.txt` is the runtime set — pinned, and it also carries
`ruff`, so the pre-push lint below works straight from it. It does **not** carry `pytest`:
`requirements-test.txt` is the only place that lives, and it is what both CI and you install to
run the suite — see [Tests](#tests). Layering it over `requirements.txt` changes nothing else;
every other entry is already satisfied, so nothing is upgraded or downgraded. OpenBB is already
pinned in `requirements.txt`; there is nothing extra to install for it.

## Run it

| | |
|---|---|
| Windows | double-click **`start.bat`**. `.\start.ps1` does the same from PowerShell, but a default Windows install refuses to run unsigned scripts — if you get `running scripts is disabled on this system`, either use `start.bat` or run `powershell -ExecutionPolicy Bypass -File .\start.ps1`. |
| macOS / Linux | `./start.sh` — both servers run in that terminal, and Ctrl-C is meant to stop them together. That last part is **unverified**: the trap could not be exercised from this machine's Git Bash, so if a backend survives Ctrl-C, kill it by hand and please open an issue. |

or manually, in two terminals, **from the repo root**:

```powershell
# terminal 1 — backend
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000

# terminal 2 — frontend
cd frontend; npm run dev
```

Then open http://localhost:5173.

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

---

## Architecture

```
React (localhost:5173)  ──►  FastAPI (localhost:8000)  ──┬─►  yfinance — quotes, history,
      │                            │                     │    news, fundamentals (15-min cache,
      │                            │                     │    price refreshed every 60s)
      │  Tab 1: Tracker            │                     ├─►  OpenBB — 10Y treasury yield,
      │  Tab 2: Financial Models   │                     │    SEC filings, SEC symbol list,
      │  Tab 3: Scorecard          │                     │    FMP peer sets
      │  Tab 4: Screener           │
      │  Tab 5: Portfolio          ├─►  SQLite (backend/data/app.db)
      │                            │      score history · watchlist · positions · drawings
      │                            │
      │                            └──►  Ollama (localhost:11434) — local AI, optional,
      │                                   streamed as newline-delimited JSON
```

- **Header — search**: type a ticker *or* a company name and pick from the list;
  typos resolve (`microsft` → MSFT, `tencnt` → 0700.HK) so a slip cannot produce an
  empty chart. Backed by a local cache of SEC's 10,398 US symbols (fetched once through
  OpenBB, free, no key, 2–3 ms) merged with live Yahoo search, which is what reaches HK
  and other non-US listings. Watchlist, holdings and recently viewed tickers sit below as
  one-click chips.
- **Tab 1 — Tracker**: price chart for US + HK tickers (`AAPL`, `0700.HK`, …) with:
  - bars sized to the period — **1-min** for 1d, **5-min** for 5d, 30-min for 1mo,
    **hourly** for 3mo–2y, daily for 5y, weekly for max. 5y and max cannot go finer:
    Yahoo caps sub-hourly data at 60 days and hourly at 730;
  - intraday bars are drawn on a **GMT+8 clock**, one timeline for both markets: HK reads
    naturally and a US session reads 21:30–03:58, which is when a Hong Kong reader is
    actually watching it. The cost is inherent — a US trading day straddles midnight and
    so spans two calendar dates on the chart. Daily and weekly bars are dates and pass
    through untouched;
  - **indicator windows count bars**, the convention every mainstream charting platform
    uses, so MA50 is 50 minutes on the 1d chart and 50 days on the 5y one. They were
    briefly scaled to trading days instead, so that MA50 meant 50 days everywhere; that
    read well and made the short periods unusable, because a 50-day average does not
    exist inside a one-day chart at any bar size and MA, RSI and MACD simply vanished
    there. The ambiguity that scaling was avoiding is now paid for in the UI rather than
    the maths: the legend names the unit (`bars @ 1h`) and every window states the time
    it actually covers. An indicator is dropped only when the chart holds fewer bars than
    its window, and the chip says how many it needed;
  - chart types: **Candles / Line / OHLC**;
  - toggleable technical indicators, computed locally — **MA10/20/50** overlays,
    **volume** histogram, **RSI(14)** pane with 30/70 bands, **MACD(12,26,9)** pane. The
    maths lives in [frontend/src/indicators.js](frontend/src/indicators.js); the window
    set and the volume histogram are assembled in
    [frontend/src/components/PriceChart.jsx](frontend/src/components/PriceChart.jsx);
  - a **±2 SD** dispersion band (off by default), centred on the MA20 already drawn.
    These are Bollinger Bands and are deliberately not called that: `%B`, the usual
    signal read off them, is an exact affine transform of a z-score — `0.5 + z/2k`,
    which the test suite pins to ten decimal places — so a band tag says nothing beyond
    "price is *z* standard deviations from its own recent mean". The plain name
    describes the lines; the eponymous one would import a trading claim this project is
    not making. It exists because the chart had **no dispersion display at all**: price,
    MAs, RSI, MACD and volume all describe level or momentum, and none of them answers
    "is today's 2% move large for this name lately?". Two measured facts are on the
    tooltip so the band is not read as a signal: **88.5%** of closes sit inside it
    (measured over 12,461 daily bars across ten names, not the 95.4% a normal
    distribution implies, because σ is estimated in-sample from the same window),
    so tags run at roughly **28 a year**. It is not sent to the AI;
  - interaction: scroll to zoom, drag to pan, double-click (or **Reset**) to fit,
    zoom ±, **Lin / Log / %** price-scale modes, and a magnet crosshair that snaps to
    OHLC;
  - **drawing tools**: trendlines and horizontal levels, with select, drag, delete and
    clear-all. Drawings are stored per ticker in SQLite as true UTC epochs, so they
    survive a reload and stay put when the period changes. They are also read by the AI —
    [backend/drawings.py](backend/drawings.py) computes where the line sits today, its
    slope per day, how far price is from it and how many bars actually touched it
    (within 0.5%), and hands the model those figures tagged `drawn_by: "user"`. A drawing
    is a reader's assertion, not a measurement, and the context says so explicitly;
  - event markers: coloured dots mark dates with news **or SEC filings**. Hovering
    previews them, **clicking opens a panel** with links (the preview is deliberately
    click-through so it cannot flicker under the cursor). Filter chips toggle each
    category — Earnings, 8-K event, Company news, Macro news, Insider — with live
    counts; insider filings start off because they dominate the feed. Markers land where
    the event did: a story carrying a publication time sits on the bar it was published
    during, and only events that are date-only, or that fall in a gap — after the close,
    over a weekend, on a holiday — snap forward to the next bar, the first session that
    could react. Nothing is silently dropped, and the popup says which precision it has,
    so a marker on the session open is never mistaken for a timestamp. The feed
    blends **company** news with **macro/policy** headlines (Fed, inflation, elections)
    from the ticker's home-market index (S&P 500 for US, Hang Seng for HK), plus SEC
    filings for US listings; a "News behind the chart" list below shows the headlines;
  - "AI outlook" generates a past/present/future analysis; the chat box talks to your
    local AI, grounded in the financial-models reference document, live data for the
    loaded ticker, and any lines you have drawn. Note the grounding is partial: the
    reference document is truncated to the first 16,000 characters to fit a 7–8B model's
    context ([backend/ai_client.py](backend/ai_client.py)), so roughly its opening 40%
    reaches the model and the later sections never do.
- **Tab 2 — Financial Models**: pulls the company's financial reports automatically and runs
  a two-stage FCFF DCF — **1 explicit year at the forecast rate, then a 9-year fade** to
  terminal growth, the explicit stage matching the one-year horizon of the consensus that
  feeds it — with editable growth / terminal growth / WACC and a sensitivity grid, anchored
  to analyst consensus growth when available; plus ratio analysis, DuPont ROE
  decomposition, valuation multiples, and revenue trend. Every DCF shows an **audit row**
  (the beta actually used and where it came from, credit spread and interest coverage, tax
  rate, the exact FCF statement period, forecast shape), the **derivation of the terminal
  rate** against both ceilings it is held under, and **trust checks**: what share of
  enterprise value is terminal value (>75% is flagged), what exit EV/EBITDA multiple the
  terminal value implies against today's multiple, and the same check run backwards — what
  perpetual growth *today's own traded multiple* already assumes, read against long-run
  nominal GDP. A **base-year panel** shows the company's own margin history, decomposes the
  newest year exactly into an operating and a capital leg, and gives the fair value on a
  normalised base beside the reported-year headline without choosing between them. An
  **equity-bridge panel** prints the path from enterprise value to a share price term by
  term — net debt, minority interest, preferred, and investment securities the cash-flow
  forecast never counted — with associates shown at their carrying cost and deliberately
  left out of the headline. On 0700.HK those terms are 28% of enterprise value.
  Every ratio carries a **0–100 quality bar** — the same score the Scorecard computes from
  its calibrated ranges for that company type, so "is 1.0 a good current ratio?" is
  answered in place rather than left to the reader. Metrics the sector profile drops show
  a dashed "not scored for this type" bar. The revenue panel plots the **level as a line**
  (near-range baseline, so its shape is visible) above **year-on-year change as
  zero-centred bars**, because bars scaled from zero made a mature company's four years
  look identical.
- **Tab 3 — Scorecard**: deterministic 0–100 score and S/A/B/C/D tier per company, built
  from five pillars (Valuation, Quality, Health, Growth, Momentum) weighted by a sector
  library ([backend/sector_weights.py](backend/sector_weights.py) — banks, REITs,
  pre-profit companies get substituted metrics). Opens with a **computed verdict line**
  naming the strongest and weakest pillar (composed from the scores, not written by the
  AI, so it works offline and never invents a figure). Includes a valuation-range
  "football field" — one price rule across all methods, a labelled axis, and a
  `price above` / `price below` / `in range` read per method. The chart **refuses to draw
  a method that does not apply** (a bank or REIT gets a struck-out DCF row with the
  reason, not a confident wrong number), suppresses an EV/Revenue multiple whose peer
  margins are not comparable, treats analyst targets as context rather than a vote, and
  leads with a **bridge** decomposing the distance from the model's value to the price
  into named steps ending in an explicitly unexplained residual. Below it sit an editable
  peer-comparison table and an optional AI-written explanation of the score. The tab also
  shows **score history** —
  every scoring writes a dated row, charted against the price recorded at the time — and
  a **bull vs bear debate** run as three separate AI passes (bull → bear → verdict), so
  disagreement stays visible instead of being averaged into one hedged paragraph.
  Design rationale: [docs/scoring-system-design.md](docs/scoring-system-design.md).
- **Tab 4 — Screener**: paste a list of tickers, score and rank them with the same
  deterministic engine. **Ranking is grouped by company type and never crosses one** —
  two composites from different sector profiles are outputs of different formulas
  (different metric sets, pillar weights and anchor curves), so sorting them into one
  list asserted a comparison the engine never computed. A group with one member is
  listed, not ranked. Cards below 60% coverage are listed but not ranked either — a thin
  card must not take a place in a ranking it cannot support. Click a row to open its
  scorecard.
- **Tab 5 — Portfolio**: watchlist and holdings. A row with 0 shares is watch-only; add
  shares and a cost basis and it becomes a position with live P&L, weight, top-1/top-3
  concentration and a Herfindahl index. The latest stored score is joined onto each row.

All AI features degrade gracefully: until Ollama is installed the site shows an
"AI offline" notice and everything else keeps working.

### Why scores are stored

The 0–100 score is built from 28 hand-set anchor curves in
[backend/scoring.py](backend/scoring.py). Those are grounded in the methodology
reference, but they have never been calibrated against forward returns — and
[docs/scoring-system-design.md](docs/scoring-system-design.md) §5 says so explicitly.

Every score is therefore persisted with **the price at scoring time**. That one column is
what will eventually make "did S tiers actually outperform C tiers?" answerable. It needs
quarters of data, not days, and there is no backfill: point-in-time fundamentals are not
available from yfinance. Until then the score remains a plausible heuristic, not a
validated one — treat it accordingly.

Your data lives in `backend/data/app.db` and is gitignored.

## Tests

`pytest` is not in `requirements.txt` — install the test set once, then run:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-test.txt

backend\.venv\Scripts\python.exe -m pytest          # 503 tests, offline, seconds
backend\.venv\Scripts\python.exe -m pytest -m network   # live yfinance contract checks
cd frontend; npm test                                   # 100 tests
```

Of the 521 collected, 18 are `network`-marked and deselected by default.

The frontend suite runs in vitest's default `node` environment; the three component
suites opt into a DOM per file with a `@vitest-environment jsdom` docblock. Rendering is
`createRoot` + React 19's own `act` ([frontend/src/test-utils.js](frontend/src/test-utils.js),
30 lines) rather than a testing library.

CI runs on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)) and gates more
than the tests: `ruff check backend/` on the backend, and `npm run lint` (oxlint) plus
`npm run build` on the frontend. Run those two lint commands before pushing or a green
local suite will still fail CI.

`tests/test_plausibility.py` encodes the acceptance criteria written in
[docs/scoring-system-design.md](docs/scoring-system-design.md) §5.2 — "RIVN … Tier 3–5",
"no bankrupt-adjacent name outranks a mega-cap compounder". It exists because **golden
snapshots catch unintended change and are structurally blind to a wrong answer that never
changes**: RIVN scored 74/Tier A against a spec of Tier 3–5, and the golden had recorded
74/A as the *expected* value since the day it was written. Two of those tests (three cases,
one being parametrised) shipped `xfail(strict=True)` on 2026-08-10 and were unmarked the
same day when the calibration landed — a strict xfail reports the breach every run and
errors the moment it is fixed.

The suite runs entirely against seven real `get_fundamentals` payloads committed under
`backend/tests/fixtures/` (280 KB), covering the technology, bank, REIT, energy,
pre-profit and HK classification paths. Golden snapshots of every scorecard are checked
in; after a deliberate methodology change regenerate them and **review the diff — that
diff is the record of what your change did to every score**:

```powershell
$env:UPDATE_GOLDEN=1; backend\.venv\Scripts\python.exe -m pytest; $env:UPDATE_GOLDEN=''
```

Fixtures themselves are regenerated with `backend\tests\capture_fixtures.py`.
The `network`-marked tests are deselected by default and exist to tell you when
yfinance changes shape — it has already shipped two different news payloads.

## Install guidance

The model choices below are sized for **CPU-only inference on ~16 GB RAM**, no dedicated GPU.
Disk is not the constraint; RAM and CPU are.

### 1. Local AI — Ollama *(optional)*

| | |
|---|---|
| Download | https://ollama.com/download (~1 GB installer; on Windows it lands in `%LOCALAPPDATA%\Programs\Ollama`) |
| Model storage | `~/.ollama/models` — change by setting the `OLLAMA_MODELS` environment variable before first pull |
| Recommended model | `qwen2.5:7b-instruct` — ~4.7 GB disk, ~6–8 GB RAM while running. Best quality/speed balance for finance reasoning on a CPU (expect ~5–10 tokens/sec). |
| Faster fallback | `qwen2.5:3b-instruct` (~2 GB) if the 7B feels too slow — noticeably weaker analysis. |
| Avoid | Anything ≥ 13B — will swap on 16 GB RAM and crawl. |

Steps:
```powershell
# after installing the Ollama app:
ollama pull qwen2.5:7b-instruct
```
That's it — the backend polls `localhost:11434` and the website's chat + AI outlook
activate automatically (green dot in the chat panel). To use a different model, change
`MODEL` at the top of [backend/ai_client.py](backend/ai_client.py).

### 2. OpenBB Platform *(required — v4.7.2)*

**Nothing to install.** `openbb==4.7.2` and its subpackages are already pinned in
`backend/requirements.txt`, so the Install step above brought them in. This section is
background on what OpenBB does here and how to give it a key.

| | |
|---|---|
| Import cost | `from openbb import obb` takes ~4–5 s. Never import it at module scope in the request path — every call site defers it into the function that needs it, and the symbol index is cached to disk so a warm start never pays it at all. The first search, first DCF and first peer lookup after a cold start each pay it once. |
| Version note | The pinned `fastapi==0.136.3` / `uvicorn==0.40.0` are OpenBB's ceiling, not arbitrary. Raising them independently will break the install. |

### Credentials

Only one of the four OpenBB calls needs a key: `equity.compare.peers`, which uses
Financial Modeling Prep's free tier. **Skipping this is fine** — peer discovery falls back to
the built-in `PEER_SUGGESTIONS` table in [backend/comps.py](backend/comps.py) and everything
else runs unchanged.

To add one: get a free key at https://site.financialmodelingprep.com, then create
`~/.openbb_platform/user_settings.json` (on Windows, `%USERPROFILE%\.openbb_platform\`):

```json
{
  "credentials": {
    "fmp_api_key": "your key here"
  }
}
```

That file lives outside the repo and is never committed. Edit it by hand — OpenBB 4.7.2 has
no `obb.account.save()`. The other three calls (`treasury_rates`, `equity.search`,
`equity.fundamental.filings`) need no key at all.

**What OpenBB is actually used for today** — four calls, all on the free tier, all with a
fallback when the fetch fails:

| call | what it feeds | where |
|---|---|---|
| `fixedincome.government.treasury_rates` (`federal_reserve`) | US 10Y yield → CAPM in `_wacc()`; cached once per calendar day, falls back to a constant offline | [backend/data_provider.py](backend/data_provider.py) |
| `equity.fundamental.filings` (`sec`) | the SEC filing markers on the chart | [backend/data_provider.py](backend/data_provider.py) |
| `equity.search` (`sec`) | the 10,398-symbol index behind typo-tolerant search; fetched once, cached to disk for 30 days | [backend/search.py](backend/search.py) |
| `equity.compare.peers` (`fmp`) | the peer set behind peer comps and the re-levered beta | [backend/comps.py](backend/comps.py) |

So OpenBB is not an optional extra: without it you lose SEC chart depth, typo tolerance
and peer betas as well as the live risk-free rate.

**One rate does not come through OpenBB.** Since 2026-08-19 a CNY-reporting issuer — `0700.HK`
is the one in the fixture set — is discounted at China's own 10-year rather than America's,
read from ChinaBond's published CGB curve by a direct HTTP call in
[backend/data_provider.py](backend/data_provider.py). No key, one fetch per calendar day. The
ten-year is picked out by the **column header ChinaBond itself labels `10Y`** rather than by a
tenor in the URL, so a wrong tenor is not something the request can express.

**When ChinaBond does not answer** — which on this machine has meant nine failure episodes
across two days, twice going working-to-dead inside fifteen minutes — the last good reading is served
instead, labelled `cgb_10y_stored_less_spread`, for as long as the yield it came from was
published within a fortnight. That is the same freshness bound a live reading has to satisfy,
so no second judgement enters. Past it, or with nothing stored, it degrades to the US 10Y
labelled `usd_proxy` — what the platform did before any of this existed. Keeping the *currency*
right is worth more than keeping the date right: China's 10-year moves ~22bp across a year,
where the gap to the US one is ~360bp and worth 30% of Tencent's fair value.

The curve itself is fetched at runtime and never committed here — CCDC restricts redistribution
rather than access — and the one cached reading lives in `backend/data/`, which is already
outside the repository.

**Free-tier reality check** (measured 2026-08-02 with valid Tiingo + FMP free keys, verified
by raw HTTP against both vendors):

| Endpoint | Free tier | Note |
|---|---|---|
| `fixedincome.government.treasury_rates` (`federal_reserve`) | ✅ no key | **wired in** |
| `equity.search` (`sec`) | ✅ no key | **wired in** — the local symbol index |
| `equity.compare.peers` (`fmp`) | ✅ | **wired in**; works for HK too, quality is inconsistent |
| `equity.fundamental.filings` (`sec`) | ✅ no key | **wired in** — ~5 y of dated 8-K/10-Q events, US only |
| `equity.estimates.consensus`, `fundamental.metrics` (`fmp`) | ✅ | yfinance already covers these |
| `equity.price.historical` (`tiingo`) | ✅ | negligible gain over yfinance |
| **`news.company` / `news.world`** | ❌ | Tiingo `403 no permission`; FMP `402 restricted` |
| `estimates.price_target`, `fundamental.income/balance/cash` (`fmp`) | ❌ `402` | yfinance already covers these |

Historical news needs a paid plan — and paying may still not solve it: Tiingo's news API
backfills only ~7 months, and FMP Starter is US-only. **Neither covers HK news at all.**

To swap the whole data layer later: implement `OpenBBProvider` with the same six methods as
`YFinanceProvider` in [backend/data_provider.py](backend/data_provider.py) — `get_quote`,
`get_history`, `get_news`, `get_peer_snapshot`, `get_filings`, `get_fundamentals` — and swap
the last line (`provider = ...`). Nothing else in the app changes. Miss `get_filings` and
the app still runs, but every SEC marker disappears from the chart. The endpoint mapping for
every model input is documented in
[docs/financial-models-reference.md](docs/financial-models-reference.md) (Section 6); note
that its "free provider" column predates the measurements above.

---

## Project structure

```
backend/    FastAPI + yfinance data adapter (15-min TTL cache), DCF/ratio models,
            peer comps, deterministic scoring engine + sector weight library,
            async streaming Ollama client
            statements.py             reading figures off a statement — no valuation logic
            store.py                  SQLite: score history, watchlist, positions, drawings
                                      + ordered schema migrations keyed on user_version
            search.py                 ticker search: local fuzzy index + Yahoo fallback
            drawings.py               geometry of user-drawn lines, for the AI context
            data/app.db               your data — gitignored
            data/ticker_index.json    cached SEC symbol list — gitignored
            tests/                    pytest suite + committed fixtures + goldens
            requirements.txt          runtime set
            requirements-test.txt     minimal set for CI (tests + lint)
frontend/   React (Vite) UI: Tracker, Financial Models, Scorecard, Screener, Portfolio
            vite.config.js            fixed port 5173 + /api proxy to the backend
docs/       financial-models-reference.md (the AI's methodology playbook)
            scoring-system-design.md (scoring architecture & rationale)
            release-readiness.md (what is done and what is deliberately not, for running it yourself)
            quant-review-2026-08-06.md (methodology review that drove the 08-07 fixes)
.github/workflows/ci.yml   CI on every push: ruff + pytest, oxlint + vitest + vite build
CHANGELOG.md   what changed, with measured before/after
TODOLIST.md    open work, ranked, with the trigger for each deferred item
pyproject.toml packaging metadata — what makes `backend` an importable package
pytest.ini     test config; network tests deselected by default
start.bat / start.ps1   one-click cold start on Windows (backend + frontend + browser)
start.sh                the same on macOS/Linux
LICENSE        GNU AGPL-3.0
```

## Licence and data provenance

Licensed under the **GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).
Copyright © 2026 Gerald-ger.

AGPL rather than something permissive because `openbb` and `openbb-core` are themselves
`AGPL-3.0-only` and are imported into this process. The clause that matters is **§13**: if this
app is ever run as a network service, whoever runs it must offer the complete corresponding
source of the served work. Running it locally for yourself carries no such obligation.

**What the licence does not cover.** Two things in this repo are third-party material, included
under attribution rather than owned:

- `backend/tests/fixtures/` — captured Yahoo Finance responses for ten symbols, kept because
  the 503-test suite runs entirely offline against them. Provenance and capture dates in
  [backend/tests/fixtures/PROVENANCE.md](backend/tests/fixtures/PROVENANCE.md).
- `backend/market_risk_premiums.json` — three values derived from Aswath Damodaran's country
  risk premium table, reproduced with attribution and an as-of date.

**yfinance is documented personal-use-only.** Yahoo's terms prohibit automated access and
redistribution, and yfinance is an unofficial scraper of Yahoo's internal endpoints, not an
affiliated client. Running this locally for yourself is the ordinary use and the risk is low.
Hosting it, or sharing it as a service, is a blocker to resolve first — the full argument, and
why no free redistribution-clean alternative covers Hong Kong, is in
[docs/data-sources-review.md](docs/data-sources-review.md) §3.

## Notes & limitations

- **News is still ~10 stories per feed**, spanning only a few days — measured
  2026-08-06, AAPL's 20 news items covered **3 distinct dates**. Chart depth now comes
  from **SEC filings** instead (free, no key, ~5 years of history). Both
  `obb.news.company` and `obb.news.world` remain paywalled, and no paid
  plan in that list covers HK news.
  **SEC filings are US-only** — EDGAR has no CIK for `0700.HK`, so HK charts show news
  markers only (~10 dates) and the chart says so. HK event depth needs a non-OpenBB
  source (AAStocks, ET Net) and is still a separate project.
- Filing markers are regulatory events, not headlines. Form 3/4/5 insider filings are
  217 of AAPL's 278 events, so they are filtered off by default; 144, SC 13G/A and
  PX14A6G are dropped entirely as chart noise.
- Volume is share volume from yfinance. Value turnover (price × volume, the HK convention)
  is not implemented and no provider has been confirmed to supply it.
- DCF base free cash flow comes from the annual cash-flow statement (`OCF + CapEx`, both
  legs from the same period); `info["freeCashflow"]` is only a fallback because yfinance
  reports it annually for some issuers and quarterly for others. `assumptions.fcf_source`
  records which one was used.
- **That statement figure is levered, and the DCF un-levers it.** Under US GAAP interest
  paid sits inside operating cash flow, so `OCF + CapEx` is closer to free cash flow to
  equity than to FCFF — discounting it at WACC *and* subtracting net debt would charge the
  debt twice. The model adds back `interest × (1 − tax)` to reach FCFF. The same figure
  stays levered for the two FCF scoring metrics, which divide by market cap and net income
  and are correctly after interest. `assumptions.fcff_basis` names which case applied:
  interest recovered from the statements, not required (IFRS filers such as 0700.HK put
  interest in financing already), or an unverified classification where no adjustment is
  made.
- **The price is delayed, and says so.** Yahoo's free feed runs ~15 minutes behind the
  exchange — `exchangeDataDelayedBy: 15`, `quoteSourceName: "Delayed Quote"` — and that floor
  cannot be removed without a paid feed. The app used to add its own 15 on top, because the
  price rode inside the 15-minute fundamentals cache; it is now refetched on a 60-second cache,
  so the screen is ~15 minutes behind rather than ~30. The DCF audit row states the quote's
  timestamp and the vendor delay.

  **Market cap is deliberately *not* refreshed with it.** It feeds the WACC weights, so
  refreshing it would make fair value drift intraday with no filing having changed. So the
  upside moves with the price while fair value, P/E, P/B and EV/EBITDA stay as of the
  fundamentals snapshot — the audit row names which is which. The batch screener keeps the
  snapshot price throughout: a stale quote cannot reorder a ranking, and a fetch per ticker
  would roughly double a fifty-name run.
- The DCF risk-free rate is the live US 10Y treasury yield, refreshed once per day, with a
  4.3% fallback when OpenBB or the Fed feed is unreachable. HK issuers use the same USD
  rate — the HKD peg makes it an acceptable proxy, not a correct one, and for a *CNY*
  reporter such as 0700.HK the peg argument does not apply at all. This is the one half of
  the cost-of-capital pair still unsourced; see `docs/data-sources-review.md` §7 for why
  the obvious fix is gated rather than shipped.
- **The vendor's own EV multiples mixed those two currencies, and now do not.**
  `enterpriseToEbitda` and `enterpriseToRevenue` arrive from Yahoo already divided, and the
  legs are not in the same unit: enterprise value is built from market cap (trading) while
  EBITDA and revenue are statement figures (reporting). Proved on 0700.HK rather than
  assumed — `marketCap / shares` reproduces the HKD quote exactly, while `totalRevenue`
  matches the CNY statement, and `EV / totalRevenue` reproduces Yahoo's published ratio to
  four decimals. So its EV/EBITDA read **15.705× where the like-for-like figure is 14.277×**,
  overstated by the whole CNY→HKD rate. Everything the app computes itself was already
  converted; a *pre-divided* vendor ratio was the one place the mismatch arrived baked in.
  Both the subject and each peer are restated before anything is compared, because
  correcting one side of a comps table and not the other is worse than correcting neither.
- **A company's statements and its shares can be in different currencies**, and for the
  China-domiciled Hong Kong listings they are: 0700.HK reports in CNY and trades in HKD
  (so do 9988.HK and 1810.HK). Cash flows, `totalDebt` and `totalCash` follow the
  statements; price, market cap, book value and EPS follow the market. Measured against
  the quarterly statements 2026-08-10 — 9988.HK's `totalDebt` and `totalCash` match its
  own balance sheet at 1.0000 and 0.9998 — and pinned by `-m network` tests, because
  nothing in yfinance documents this split. Everything the DCF panel shows is converted
  into the **trading** currency and the panel names it. When no FX rate can be fetched the
  upside is **withheld** rather than computed across two units, the two market-cap yields
  are dropped, and Altman Z reports `n/a`; the rate is never guessed at.
- The default DCF growth is anchored to analyst forward consensus when available, falling
  back to trailing revenue growth and then to a stated default. **Nothing is truncated.** A
  figure either passes a validity range of −50% to +200% and is used exactly as published,
  or fails it and is *rejected* in favour of the next source — and the label on screen
  always names which of the four provenances produced the number. The old `[0%, 25%]` clamp
  was removed because both ends were economic judgements wearing data-hygiene clothes: the
  floor grew shrinking companies at zero and inflated XOM's fair value 15.7%, and the
  ceiling truncated a 42.6% consensus from 55 analysts on NVDA. XOM's consensus is
  **−1.9%** and is now modelled as the decline it is.
- **Terminal growth shows its derivation** rather than appearing as a bare 2.5%. It is held
  under two ceilings, both displayed whether or not they bind: long-run nominal GDP
  (nothing outgrows its economy forever) and the risk-free rate (Damodaran's cap — the
  ten-year is itself a market read of long-run nominal growth). The cap applies only to the
  platform's own default; a caller who names a rate gets that rate, because the
  reconciliation back-solves deliberately past both ceilings and capping it there would
  report "closing this gap needs 7.0% perpetual growth" as unreachable.
- **The base year is one reported period, and that is an assumption, not a neutral choice.**
  Free cash flow enters the valuation linearly, so a base year 22% below normal is a
  valuation 22% below normal — permanently, through every projected year and the terminal
  value. Measured across the fixtures, the newest reported year sits *below* that company's
  own mean FCF margin for three of the four profitable names (AAPL 0.90×, MSFT 0.78×, XOM
  0.71×; 0700.HK is the exception at 1.06×). The model still reports the filed year as the
  headline, and shows the normalised alternative beside it. The adjustment is deliberately
  **not one-way** — it moves 0700.HK down while moving MSFT and XOM up — which is what
  separates a correction from a nudge toward the market price.
- **Analyst target prices are shown and scored nowhere.** A target is a twelve-month
  forecast of where a stock will trade, not an estimate of what the business is worth, and
  published targets sit above price on average. It used to sit in the valuation pillar,
  where it also double-counted sell-side opinion: the DCF's growth input is *already*
  analyst consensus, so one source moved two of five metrics with correlated errors of the
  same sign. Removing it moved the composite −3 to +1 and no fixture changed tier. The DCF
  still consumes consensus growth — opinion counted once, and labelled.
- **Beta is measured, not read.** It is regressed from **five years of weekly returns**
  against the company's home index (`^HSI` for `.HK` listings, `^GSPC` otherwise) —
  cov/var, cross-checked against numpy's covariance and a least-squares slope. The vendor's
  own figure is kept beside it as a cross-check rather than as the input.

  Below that the older ladder is unchanged: a reported beta within `[0.3, 2.5]`, else peer
  betas **unlevered, medianed and re-levered to the company's own capital structure**
  (reference doc §1.1.2), needing at least two peers with known leverage, else the levered
  median, else 1.0. The value used and its source (`computed` / `reported` /
  `peer_median_relevered` / `peer_median` / `default`) are shown in the DCF audit row.

  This matters most where the vendor and the band disagreed. XOM's reported 0.173 failed the
  band and only one of its four peers survived it, so it fell through to a neutral **1.0** —
  and the regression puts it at **0.2888**. Correcting that alone moves XOM's fair value
  **+105%**. Note what that implies: the vendor was directionally right and the `0.3` floor
  was the problem, so the floor now clamps a *measured* value.

  **The regression also reports how well it fit, because on XOM it barely did.** A slope
  alone cannot say whether it measured anything, and the audit row used to print 0.2888 and
  AAPL's 1.1546 in the same typeface. The index explains **46%** of AAPL's week-to-week
  movement and **2.8%** of XOM's; XOM's 95% interval is **0.08 to 0.49**, which is wider than
  the estimate it brackets and moves that company's fair value from 123 to 228. So R², the
  interval, and the unclamped slope are all shown — XOM reads *used 0.30, regressed 0.2888*
  rather than presenting the clamped figure as the measurement.

  Deliberately **published rather than flagged**: a "fit too weak" threshold would be a
  constant eight fixtures cannot calibrate. R² runs 0.028, 0.055, 0.148, 0.169, then a jump
  to 0.42–0.69, so any cut in the weak range would sit between two adjacent observations
  rather than be fitted to anything. *(This read "0.028 → 0.148 with nothing in between"
  until 2026-08-19, when `0002_HK` landed at 0.055 — inside the gap the sentence rested on.
  The conclusion survives the correction; that particular evidence for it did not.)* And note
  the asymmetry it introduces — beta now carries an interval while the growth rate and equity
  risk premium do not, which does not mean those are precise.
- **Forensic checks are computed but never scored.** The Scorecard shows Altman Z,
  Piotroski F, the Sloan accrual ratio and net share issuance beside the composite, each
  with its published threshold. They stay out of the score because the composite already
  blends 28 anchor curves with no forward-return validation; adding four more would move
  every score without adding evidence. Z reports `n/a` with a reason for banks, insurers,
  REITs and utilities rather than mislabelling an asset-heavy balance sheet as distress.
- Cost of debt is the risk-free rate plus a synthetic credit spread keyed on interest
  coverage, not the flat +1.5% used previously. The equity risk premium is **per market**,
  read from a dated Damodaran snapshot (`backend/market_risk_premiums.json`) and keyed on
  the currency the discounted cash flows are reported in — United States 4.46%, Hong Kong
  5.01%, China 5.14% as of 2026-01-05, against the flat 5% that preceded it. A market with
  no entry falls back to the mature-market premium, and a missing file to the old 5%; the
  Models tab names which of the three was used.
- Corporate tax defaults to the statutory rate for the listing currency (HKD 16.5%,
  USD 21%, otherwise 21%) and is overridable per request. **A REIT is the exception**, and
  an exception in kind rather than degree: everywhere else the gap between statutory and
  what a company actually pays is tax planning, and the statutory figure is the right input
  for a debt shield because it is the marginal rate. A REIT deducts what it distributes, so
  there is almost nothing left to shield — Realty Income's own statements show **7.4%**
  effective, and that residual is its taxable subsidiaries rather than the trust. Charging
  it 21% overstated the shield and understated its WACC (6.05% against 6.58%, a fair value
  of 36.00 against 27.04). The rule keys on the same classification `dcf_applies` uses.
- Terminal value is 50–73% of enterprise value on the sample fixtures. Above 75% the UI
  flags it: at that point the perpetuity assumption, not the explicit forecast, is
  producing the answer. Cross-check with the implied exit multiple — a DCF that only works
  by exiting far below today's trading multiple is assuming compression, which is a stance
  to agree with rather than inherit. Always sanity-check with the sensitivity grid and the
  editable assumptions.
- The Scorecard is a deterministic snapshot of fundamentals, valuation and momentum
  against heuristic healthy ranges. It is not a prediction; validation covers
  consistency and plausibility, not forward returns (see docs/scoring-system-design.md §5).
  Score history is now recorded so this can eventually be tested — it has not been yet.
- **Composites from different company types are not on one scale.** Each profile scores a
  different metric set on different weights, so a bank's 71 and a pre-profit company's 60
  are outputs of two formulas, not two readings. The Screener refuses to rank across types
  for this reason, and the Portfolio tab names the profile beside every stored score.
- **The pre-profit weights were re-tuned on 2026-08-10** (quality 0.15 → 0.25, growth
  0.35 → 0.25) after RIVN scored 74/Tier A against a spec of Tier 3–5, together with a fix
  to `cash_runway_q`, which had been dividing cash by operating burn while ignoring capex —
  27.3 quarters against 8.5 on a free-cash-flow basis. RIVN now scores 60/B. Two things
  follow: the anchors are still **not** validated against forward returns, so this enforced
  a written expectation rather than adding evidence; and `score_history`'s pre-profit
  series is **discontinuous at that date** — old rows come from the old formula, there is
  no backfill, and a future calibration study has to segment across it.
- **A DCF is not shown as an answer for company types it does not fit.** Banks have no
  `CFO − CapEx` at all, and a REIT's capex is property acquisition rather than
  maintenance, so the model still returns a number (O: −63%) that means nothing. Both the
  Scorecard's valuation pillar and the Financial Models tab now say so instead.
- Free cash flow for both the DCF and the two FCF scoring metrics comes from the cash-flow
  statement. `info["freeCashflow"]` is only a fallback and raises the
  `fcf_from_info_unverified_period` flag when used, because yfinance reports it annually
  for some issuers and quarterly for others (MSFT 0.244×, GOOGL 0.309×).
- The AI never computes or changes a number. It only comments on figures already computed
  by the deterministic engine, at `temperature: 0` with a fixed seed so the same input
  gives the same commentary.
- The bull/bear debate and token streaming have **never been run against a live model** —
  Ollama is not installed here, so only the offline degradation path is verified. See
  TODOLIST.md.
- Portfolio totals sum mixed currencies at face value; there is no FX conversion. The UI
  warns when holdings span more than one currency.
- Everything runs locally; nothing is sent to any cloud service.
- **Decision support only — not certified financial advice.**
