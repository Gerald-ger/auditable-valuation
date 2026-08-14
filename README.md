# Financial-model-analyse — Stock Analysis Platform

A local website for tracking stocks, explaining price moves with news, chatting with a
local AI financial expert, and running investment-banking financial models — powered by
the methodology in [docs/financial-models-reference.md](docs/financial-models-reference.md).

## Architecture

```
React (localhost:5173)  ──►  FastAPI (localhost:8000)  ──┬─►  yfinance — quotes, history,
      │                            │                     │    news, fundamentals (15-min cache)
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
  - **indicator windows measured in trading days, not bars**, so MA50 means 50 days
    on every period (350 bars on an hourly chart). A window longer than the period
    holds is not drawn — one session cannot produce a 50-day average — and the chart
    says so;
  - chart types: **Candles / Line / OHLC**;
  - toggleable technical indicators, computed locally — **MA10/20/50** overlays,
    **volume** histogram, **RSI(14)** pane with 30/70 bands, **MACD(12,26,9)** pane. The
    maths lives in [frontend/src/indicators.js](frontend/src/indicators.js); the window
    set and the volume histogram are assembled in
    [frontend/src/components/PriceChart.jsx](frontend/src/components/PriceChart.jsx);
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
  normalised base beside the reported-year headline without choosing between them.
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

```powershell
backend\.venv\Scripts\python.exe -m pytest          # 357 tests, offline, seconds
backend\.venv\Scripts\python.exe -m pytest -m network   # live yfinance contract checks
cd frontend; npm test                                   # 46 tests
```

Of the 373 collected, 16 are `network`-marked and deselected by default.

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

Your machine: **15.6 GB RAM, Intel Iris Xe (no dedicated GPU), i7-1355U.**
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
| Import cost | `from openbb import obb` takes ~4–5 s. Never import it at module scope in the request path — every call site defers it into the function that needs it, and the symbol index is cached to disk so a warm start never pays it at all. |
| Credentials | `C:\Users\<user>\.openbb_platform\user_settings.json` (outside the repo, never committed). There is **no** `obb.account.save()` in 4.7.2 — edit that JSON directly. |

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
            store.py                  SQLite: score history, watchlist, positions, drawings
            search.py                 ticker search: local fuzzy index + Yahoo fallback
            drawings.py               geometry of user-drawn lines, for the AI context
            data/app.db               your data — gitignored
            data/ticker_index.json    cached SEC symbol list — gitignored
            tests/                    pytest suite + committed fixtures + goldens
            requirements.lock.txt     pre-OpenBB state — the rollback target
            requirements.post-openbb.txt   runtime state
            requirements-test.txt     minimal set for CI
frontend/   React (Vite) UI: Tracker, Financial Models, Scorecard, Screener, Portfolio
docs/       financial-models-reference.md (the AI's methodology playbook)
            scoring-system-design.md (scoring architecture & rationale)
            quant-review-2026-08-06.md (methodology review that drove the 08-07 fixes)
.github/workflows/ci.yml   CI on every push: ruff + pytest, oxlint + vitest + vite build
CHANGELOG.md   what changed, with measured before/after
TODOLIST.md    open work, ranked, with the trigger for each deferred item
pytest.ini     test config; network tests deselected by default
start.bat / start.ps1   one-click cold start (backend + frontend + browser)
```

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
- The DCF risk-free rate is the live US 10Y treasury yield, refreshed once per day, with a
  4.3% fallback when OpenBB or the Fed feed is unreachable. HK issuers use the same USD
  rate — the HKD peg makes it an acceptable proxy, not a correct one, and for a *CNY*
  reporter such as 0700.HK the peg argument does not apply at all. This is the one half of
  the cost-of-capital pair still unsourced; see `docs/data-sources-review.md` §7 for why
  the obvious fix is gated rather than shipped.
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
  USD 21%, otherwise 21%) and is overridable per request.
- Terminal value is 52–66% of enterprise value on the sample fixtures. Above 75% the UI
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
