# Financial-model-analyse — Stock Analysis Platform

A local website for tracking stocks, explaining price moves with news, chatting with a
local AI financial expert, and running investment-banking financial models — powered by
the methodology in [docs/financial-models-reference.md](docs/financial-models-reference.md).

## Architecture

```
React (localhost:5173)  ──►  FastAPI (localhost:8000)  ──┬─►  yfinance — quotes, history,
      │                            │                     │    news, fundamentals
      │  Tab 1: Tracker            │                     └─►  OpenBB — US 10Y treasury yield
      │  Tab 2: Financial Models   │
      │  Tab 3: Scorecard          └──►  Ollama (localhost:11434) — local AI, optional
```

- **Tab 1 — Tracker**: price chart for US + HK tickers (`AAPL`, `0700.HK`, …) with:
  - periods from intraday **1d** (15-min bars) and **5d** (hourly bars) up to **max**;
  - chart types: **Candles / Line / OHLC**;
  - toggleable technical indicators, computed locally in
    [frontend/src/indicators.js](frontend/src/indicators.js): **MA10/20/50** overlays,
    **volume** histogram, **RSI(14)** pane with 30/70 bands, **MACD(12,26,9)** pane;
  - news integration: gold dots mark dates with news; hovering pops up the stories near
    that date, and a "News behind the chart" list below shows every story. The feed
    blends **company** news with **macro/policy** headlines (Fed, inflation, elections)
    from the ticker's home-market index (S&P 500 for US, Hang Seng for HK), tagged and
    deduplicated;
  - "AI outlook" generates a past/present/future analysis; the chat box talks to your
    local AI, grounded in the financial-models reference document plus live data for
    the loaded ticker.
- **Tab 2 — Financial Models**: pulls the company's financial reports automatically and runs
  a 5-year FCFF DCF (editable growth / terminal growth / WACC, with a sensitivity grid,
  anchored to analyst consensus growth when available), ratio analysis, DuPont ROE
  decomposition, valuation multiples, and revenue trend.
- **Tab 3 — Scorecard**: deterministic 0–100 score and S/A/B/C/D tier per company, built
  from five pillars (Valuation, Quality, Health, Growth, Momentum) weighted by a sector
  library ([backend/sector_weights.py](backend/sector_weights.py) — banks, REITs,
  pre-profit companies get substituted metrics). Includes a valuation-range "football
  field" (DCF vs peer multiples vs analyst targets), an editable peer-comparison table,
  and an optional AI-written explanation of the score. Design rationale:
  [docs/scoring-system-design.md](docs/scoring-system-design.md). Validation:
  `backend\.venv\Scripts\python.exe backend\test_scoring.py`.

All AI features degrade gracefully: until Ollama is installed the site shows an
"AI offline" notice and everything else keeps working.

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
backend/    FastAPI + yfinance data adapter, DCF/ratio models, peer comps,
            deterministic scoring engine + sector weight library, Ollama client
            requirements.lock.txt      pre-OpenBB state — the rollback target
            requirements.post-openbb.txt   current state
frontend/   React (Vite) UI: Tracker, Financial Models, and Scorecard tabs
docs/       financial-models-reference.md (the AI's methodology playbook)
            scoring-system-design.md (scoring architecture & rationale)
CHANGELOG.md   what changed, with measured before/after
TODOLIST.md    open work, ranked, with the trigger for each deferred item
start.bat   one-click cold start (backend + frontend + browser)
```

## Notes & limitations

- News is limited to the ~10 most recent stories per feed (company + market index),
  so hover-news is sparse on older dates. **OpenBB does not fix this on the free tier** —
  both `obb.news.company` and `obb.news.world` are paywalled (see the table above), and no
  paid plan in that list covers HK news. The free workaround under evaluation is SEC
  filings as dated US events; HK would need a non-OpenBB source.
- Volume is share volume from yfinance. Value turnover (price × volume, the HK convention)
  is not implemented and no provider has been confirmed to supply it.
- DCF base free cash flow comes from the annual cash-flow statement (`OCF + CapEx`, both
  legs from the same period); `info["freeCashflow"]` is only a fallback because yfinance
  reports it annually for some issuers and quarterly for others. `assumptions.fcf_source`
  records which one was used.
- The DCF risk-free rate is the live US 10Y treasury yield, refreshed once per day, with a
  4.3% fallback when OpenBB or the Fed feed is unreachable. HK issuers use the same USD
  rate — the HKD peg makes it an acceptable proxy, not a correct one.
- The default DCF growth is anchored to analyst forward consensus when available
  (falling back to trailing revenue growth); WACC uses CAPM with heuristic inputs and a
  flat credit spread. A 5-year FCFF fade structurally undervalues high-growth mega-caps —
  large negative upside on those names is the method's stance, not a data error. Always
  sanity-check with the sensitivity grid and the editable assumptions.
- The Scorecard is a deterministic snapshot of fundamentals, valuation and momentum
  against heuristic healthy ranges. It is not a prediction; validation covers
  consistency and plausibility, not forward returns (see docs/scoring-system-design.md §5).
- Everything runs locally; nothing is sent to any cloud service.
- **Decision support only — not certified financial advice.**
