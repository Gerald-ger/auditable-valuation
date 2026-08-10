# Financial-model-analyse — Stock Analysis Platform

A local website for tracking stocks, explaining price moves with news, chatting with a
local AI financial expert, and running investment-banking financial models — powered by
the methodology in [docs/financial-models-reference.md](docs/financial-models-reference.md).

## Architecture

```
React (localhost:5173)  ──►  FastAPI (localhost:8000)  ──┬─►  yfinance — quotes, history,
      │                            │                     │    news, fundamentals (15-min cache)
      │  Tab 1: Tracker            │                     ├─►  OpenBB — US 10Y treasury yield
      │  Tab 2: Financial Models   │                     │
      │  Tab 3: Scorecard          ├─►  SQLite (backend/data/app.db)
      │  Tab 4: Screener           │      score history · watchlist · positions
      │  Tab 5: Portfolio          │
      │                            └──►  Ollama (localhost:11434) — local AI, optional,
      │                                   streamed as newline-delimited JSON
```

- **Header — search**: type a ticker *or* a company name and pick from the list;
  typos resolve (`microsft` → MSFT, `tencnt` → 0700.HK) so a slip cannot produce an
  empty chart. Backed by a local cache of SEC's 10,398 US symbols (free, no key,
  2–3 ms) merged with live Yahoo search, which is what reaches HK and other non-US
  listings. Watchlist, holdings and recently viewed tickers sit below as one-click chips.
- **Tab 1 — Tracker**: price chart for US + HK tickers (`AAPL`, `0700.HK`, …) with:
  - bars sized to the period — **2-min** for 1d, **5-min** for 5d, 30-min for 1mo,
    **hourly** for 3mo–2y, daily beyond. 5y and max cannot go finer: Yahoo caps
    sub-hourly data at 60 days and hourly at 730;
  - **indicator windows measured in trading days, not bars**, so MA50 means 50 days
    on every period (350 bars on an hourly chart). A window longer than the period
    holds is not drawn — one session cannot produce a 50-day average — and the chart
    says so;
  - chart types: **Candles / Line / OHLC**;
  - toggleable technical indicators, computed locally in
    [frontend/src/indicators.js](frontend/src/indicators.js): **MA10/20/50** overlays,
    **volume** histogram, **RSI(14)** pane with 30/70 bands, **MACD(12,26,9)** pane;
  - interaction: scroll to zoom, drag to pan, double-click (or **Reset**) to fit,
    zoom ±, **Lin / Log / %** price-scale modes, and a magnet crosshair that snaps to
    OHLC;
  - event markers: coloured dots mark dates with news **or SEC filings**. Hovering
    previews them, **clicking opens a panel** with links (the preview is deliberately
    click-through so it cannot flicker under the cursor). Filter chips toggle each
    category — Earnings, 8-K event, Company news, Macro news, Insider — with live
    counts; insider filings start off because they dominate the feed. Events falling on
    non-trading days snap to the next bar, so nothing is silently dropped. The feed
    blends **company** news with **macro/policy** headlines (Fed, inflation, elections)
    from the ticker's home-market index (S&P 500 for US, Hang Seng for HK), plus SEC
    filings for US listings; a "News behind the chart" list below shows the headlines;
  - "AI outlook" generates a past/present/future analysis; the chat box talks to your
    local AI, grounded in the financial-models reference document plus live data for
    the loaded ticker.
- **Tab 2 — Financial Models**: pulls the company's financial reports automatically and runs
  a two-stage FCFF DCF — 5 explicit years at the starting growth rate, then a 5-year fade
  to terminal growth — with editable growth / terminal growth / WACC and a sensitivity
  grid, anchored to analyst consensus growth when available; plus ratio analysis, DuPont
  ROE decomposition, valuation multiples, and revenue trend. Every DCF shows an **audit
  row** (the beta actually used and where it came from, credit spread and interest
  coverage, tax rate, the exact FCF statement period, forecast shape) and **two trust
  checks**: what share of enterprise value is terminal value (>75% is flagged), and what
  exit EV/EBITDA multiple the terminal value implies against today's multiple.
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
  `price above` / `price below` / `in range` read per method — an editable
  peer-comparison table,
  and an optional AI-written explanation of the score. Also shows **score history** —
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

The 0–100 score is built from ~40 hand-set anchor curves in
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

```powershell
backend\.venv\Scripts\python.exe -m pytest          # 246 pass, 3 xfail, offline, ~2.5s
backend\.venv\Scripts\python.exe -m pytest -m network   # live yfinance contract checks
cd frontend; npm test                                   # 44 tests
```

Of the 264 collected, 15 are `network`-marked and deselected by default. The 3
expected failures are real: `tests/test_plausibility.py` encodes the acceptance
criteria written in [docs/scoring-system-design.md](docs/scoring-system-design.md) §5.2
("RIVN … Tier 3–5", "no bankrupt-adjacent name outranks a mega-cap compounder"),
and the engine does not currently meet them — RIVN scores 74/A. They are
`xfail(strict=True)`, so the violation is reported in every run and turns into an
error the moment a calibration change fixes it.

That file exists because **golden snapshots catch unintended change and are
structurally blind to a wrong answer that never changes.** The golden had recorded
RIVN at 74/A as the expected value since the day it was written.

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

## Run it

Double-click **`start.bat`** (or run `.\start.ps1` from PowerShell).

or manually, in two terminals:

```powershell
# terminal 1 — backend
backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --port 8000

# terminal 2 — frontend
cd frontend; npm run dev
```

Then open http://localhost:5173.

---

## Install guidance

Your machine: **15.6 GB RAM, Intel Iris Xe (no dedicated GPU), i7-1355U, 747 GB free disk.**
Disk is not a constraint; RAM and CPU-only inference are what size the choices below.

### 1. Local AI — Ollama *(not installed yet)*

| | |
|---|---|
| Download | https://ollama.com/download/windows (~1 GB installer, installs to `C:\Users\<user>\AppData\Local\Programs\Ollama`) |
| Model storage | `C:\Users\<user>\.ollama\models` — change by setting the `OLLAMA_MODELS` environment variable before first pull |
| Recommended model | `qwen2.5:7b-instruct` — ~4.7 GB disk, ~6–8 GB RAM while running. Best quality/speed balance for finance reasoning on your CPU (expect ~5–10 tokens/sec). |
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

### 2. OpenBB Platform *(installed — v4.7.2)*

| | |
|---|---|
| Install | `backend\.venv\Scripts\python.exe -m pip install openbb` — 41 MB / 66 wheels into the existing venv. pandas & numpy are already present, so the download is small and needs no C compiler. **Stop the servers first** or Windows file locks break the install. |
| Side effect | Downgrades `fastapi` 0.141.1 → 0.136.3 and `uvicorn` 0.52.0 → 0.40.0. Verified harmless here. Roll back with `backend\requirements.lock.txt`; the post-install state is `backend\requirements.post-openbb.txt`. |
| Import cost | `from openbb import obb` takes ~4 s. Never import it at module scope in the request path — [backend/data_provider.py](backend/data_provider.py) defers it into the function that needs it. |
| Credentials | `C:\Users\<user>\.openbb_platform\user_settings.json` (outside the repo, never committed). There is **no** `obb.account.save()` in 4.7.2 — edit that JSON directly. |

**What OpenBB is actually used for today:** the US 10-year treasury yield that feeds
CAPM in `_wacc()`, via `obb.fixedincome.government.treasury_rates(provider="federal_reserve")`
— free, no API key, cached once per calendar day, falls back to a constant when offline.

**Free-tier reality check** (measured 2026-08-02 with valid Tiingo + FMP free keys, verified
by raw HTTP against both vendors):

| Endpoint | Free tier | Note |
|---|---|---|
| `fixedincome.government.treasury_rates` (`federal_reserve`) | ✅ no key | **wired in** |
| `equity.compare.peers` (`fmp`) | ✅ | works for HK too; quality is inconsistent |
| `equity.fundamental.filings` (`sec`) | ✅ no key | 2.5 y of dated 8-K/10-Q events, US only |
| `equity.estimates.consensus`, `fundamental.metrics` (`fmp`) | ✅ | yfinance already covers these |
| `equity.price.historical` (`tiingo`) | ✅ | negligible gain over yfinance |
| **`news.company` / `news.world`** | ❌ | Tiingo `403 no permission`; FMP `402 restricted` |
| `estimates.price_target`, `fundamental.income/balance/cash` (`fmp`) | ❌ `402` | yfinance already covers these |

Historical news needs a paid plan — and paying may still not solve it: Tiingo's news API
backfills only ~7 months, and FMP Starter is US-only. **Neither covers HK news at all.**

To swap the whole data layer later: implement `OpenBBProvider` with the same five methods as
`YFinanceProvider` in [backend/data_provider.py](backend/data_provider.py) — `get_quote`,
`get_history`, `get_news`, `get_peer_snapshot`, `get_fundamentals` — and swap the
last line (`provider = ...`). Nothing else in the app changes. The endpoint mapping for
every model input is documented in
[docs/financial-models-reference.md](docs/financial-models-reference.md) (Section 6); note
that its "free provider" column predates the measurements above.

---

## Project structure

```
backend/    FastAPI + yfinance data adapter (15-min TTL cache), DCF/ratio models,
            peer comps, deterministic scoring engine + sector weight library,
            async streaming Ollama client
            store.py                  SQLite: score history, watchlist, positions
            data/app.db               your data — gitignored
            tests/                    pytest suite + committed fixtures + goldens
            requirements.lock.txt     pre-OpenBB state — the rollback target
            requirements.post-openbb.txt   runtime state
            requirements-test.txt     minimal set for CI
frontend/   React (Vite) UI: Tracker, Financial Models, Scorecard, Screener, Portfolio
docs/       financial-models-reference.md (the AI's methodology playbook)
            scoring-system-design.md (scoring architecture & rationale)
CHANGELOG.md   what changed, with measured before/after
TODOLIST.md    open work, ranked, with the trigger for each deferred item
pytest.ini     test config; network tests deselected by default
start.bat   one-click cold start (backend + frontend + browser)
```

## Notes & limitations

- **News is still ~10 stories per feed**, spanning only a few days — measured
  2026-08-06, AAPL's 20 news items covered **3 distinct dates**. Chart depth now comes
  from **SEC filings** instead (free, no key, ~5 years: AAPL has 278 events over 140
  dates). Both `obb.news.company` and `obb.news.world` remain paywalled, and no paid
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
- The DCF risk-free rate is the live US 10Y treasury yield, refreshed once per day, with a
  4.3% fallback when OpenBB or the Fed feed is unreachable. HK issuers use the same USD
  rate — the HKD peg makes it an acceptable proxy, not a correct one.
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
- The default DCF growth is anchored to analyst forward consensus when available
  (falling back to trailing revenue growth). Note this input does a lot of work: XOM's
  consensus forward revenue growth is 0%, which drives its result more than any other
  assumption.
- **Beta is not trusted blindly.** yfinance reported 0.173 for XOM, which alone moved its
  DCF upside by ~79 points. A reported beta is used only within `[0.3, 2.5]`; otherwise
  peer betas are **unlevered, medianed and re-levered to the company's own capital
  structure** (reference doc §1.1.2) — a raw peer median carried the peers' balance
  sheets rather than the target's. Needs at least two peers with known leverage; without
  that it falls back to the levered median, then to 1.0. The value used and its source
  (`reported` / `peer_median_relevered` / `peer_median` / `default`) are shown in the DCF
  audit row. The band catches implausible readings, not merely wrong ones — and
  yfinance's betas are broken sector-wide for energy (SHEL −0.218, BP −0.212), which is
  why the two-peer minimum exists.
- **Forensic checks are computed but never scored.** The Scorecard shows Altman Z,
  Piotroski F, the Sloan accrual ratio and net share issuance beside the composite, each
  with its published threshold. They stay out of the score because the composite already
  blends ~40 anchor curves with no forward-return validation; adding four more would move
  every score without adding evidence. Z reports `n/a` with a reason for banks, insurers,
  REITs and utilities rather than mislabelling an asset-heavy balance sheet as distress.
- Cost of debt is the risk-free rate plus a synthetic credit spread keyed on interest
  coverage, not the flat +1.5% used previously. The equity risk premium is still a flat 5%
  for every market and period.
- Corporate tax defaults to the statutory rate for the listing currency (HKD 16.5%,
  USD 21%, otherwise 21%) and is overridable per request.
- Terminal value is 51–66% of enterprise value on the sample fixtures. Above 75% the UI
  flags it: at that point the perpetuity assumption, not the explicit forecast, is
  producing the answer. Cross-check with the implied exit multiple — a DCF that only works
  by exiting far below today's trading multiple is assuming compression, which is a stance
  to agree with rather than inherit. Always sanity-check with the sensitivity grid and the
  editable assumptions.
- The Scorecard is a deterministic snapshot of fundamentals, valuation and momentum
  against heuristic healthy ranges. It is not a prediction; validation covers
  consistency and plausibility, not forward returns (see docs/scoring-system-design.md §5).
  Score history is now recorded so this can eventually be tested — it has not been yet.
- **Composites from different company types are not on one scale, and one open failure
  proves it.** RIVN scores 74 ("A — Solid") against AAPL's 67, because the
  `pre_profit_growth` profile weights the pillar it fails at 15% (quality 10: operating
  margin −50%) and the pillar it aces at 35%. The design doc's own acceptance criteria
  say a pre-profit name belongs in Tier 3–5; `tests/test_plausibility.py` records the
  breach. The Screener refuses to rank across types for exactly this reason — the
  Portfolio tab shows stored scores side by side and does not.
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
