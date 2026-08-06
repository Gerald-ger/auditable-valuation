# TODO

Open work, ranked. Each item records the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated.

Status: 🔴 open bug · 🟡 improvement · 🔵 decision needed · ⚪ deliberately deferred

---

## Now

### 🔴 The debate, streaming and every AI reply are unverified end-to-end

Ollama has never been installed on this machine, so `localhost:11434` has never
answered. What *is* verified: all four AI endpoints (`/ai/chat`, `/ai/predict`,
`/score/../narrative`, `/ai/debate`) return a well-formed `ai_unavailable` NDJSON
event, the UI renders it, and nothing hangs or 500s.

What has **never been observed**: token-level streaming, the bull → bear → verdict
staging, whether a 7B model on CPU produces a usable debate at all, and how long
three sequential passes actually take (estimate: 3–9 minutes, untested).

**Trigger: install Ollama.** `ollama pull qwen2.5:7b-instruct`, then run the debate on
AAPL and time it. If three passes are unbearable on CPU, the fix is to make the stage
list configurable rather than to abandon the adversarial structure.

### 🟡 Score history is empty until you use the app

The calibration record starts accumulating from first use — there is no backfill,
because scoring a past date would need point-in-time fundamentals that yfinance does
not expose. A meaningful read on "did S tiers outperform C tiers" needs quarters, not
days. Nothing to do now except use it.

**Trigger: ~2 quarters of rows.** Then write the calibration query (join each score to
the price N months later, bucket by tier) and find out whether the anchor tables in
`scoring.py` mean anything.

### 🔵 The beta credibility band catches extremes, not merely wrong values

`resolve_beta` rejects a beta outside `[0.3, 2.5]`. That caught XOM's 0.173, but a
plausible-looking 0.45 for an oil major would pass straight through. And because
yfinance's energy betas are broken sector-wide (CVX 0.488, COP 0.123, SHEL −0.218,
BP −0.212), peer substitution cannot rescue that sector either — XOM falls through
to the neutral 1.0 default.

**Options:** accept it (the audit row shows the beta and its source, and beta is
inspectable); add a sector-median beta table as a third tier; or compute beta from
price history directly, which is the only real fix and needs 2–5 years of weekly
returns for the stock and its index.

### 🟡 Commit the pending work

The 2026-08-06 changes (score history, screener, portfolio, scoring FCF fix, async AI,
pytest suite, CI, and the valuation-accuracy set) are unreviewed by git.

---

## Next

### 🟡 The methodology reference is truncated, not retrieved

[backend/ai_client.py](backend/ai_client.py) does `text[:16000]` on a 1,087-line
document, so everything past roughly the first 40% never reaches the model — including
§6 (endpoint mapping) and §7.1 (the model-priority matrix). "Grounded in the
methodology" is therefore only true of the opening sections.

**Fix:** chunk the document and select sections by keyword against the user's question.
**Trigger: after Ollama is installed** — worth measuring whether the 7B model even uses
the excerpt it already gets before building retrieval for it.

### 🟡 Growth sourcing is doing more work than anything else in the DCF

XOM's `growth_rate_year1` is **0.0%**, taken from analyst forward consensus, and it
drives the −55.7% result more than the beta correction does. The input is capped at
25% and floored at 0%, so a company in consensus decline is modelled as flat forever
through stage 1. Cyclicals are exactly where a single-year consensus figure is least
meaningful.

**Trigger: before trusting DCF upside on any cyclical.** Options: use a multi-year
consensus average, use the 3-year revenue CAGR for cyclicals specifically (the
sector profile already knows which they are), or widen the floor to allow decline.

### 🟡 Portfolio totals ignore FX

Holdings in USD and HKD are summed at face value. The UI warns when more than one
currency is present, but the total is wrong, not merely imprecise.
**Trigger: actually holding both.** Needs a rate source; `obb.currency` is free.

### 🟡 Cosmetic

- [frontend/src/components/ModelsTab.jsx:128](frontend/src/components/ModelsTab.jsx#L128) —
  `dcf.upside_pct >= 0` is `true` when the value is `null`, so an unavailable upside renders
  green.
- [backend/scoring.py:176](backend/scoring.py#L176) — `equity_multiplier = None` is
  overwritten on the next line.
- `assumptions.fcf_source` and `assumptions.risk_free_rate` are returned by the API but not
  surfaced in the DCF panel; showing them would make the valuation auditable at a glance.
- `ScorecardTab` has an `exhaustive-deps` lint warning on `loadComps` (pre-existing).
- A non-existent ticker in the screener returns a row with 0% coverage rather than
  landing in `failed`, because yfinance returns an empty payload instead of raising.
  The row is greyed and unranked, so it is honest, just not obvious.

---

## Decisions needed (not bugs — your call)

### 🔵 HK stocks are benchmarked against the S&P 500

`rel_52w_change = 52WeekChange − SandP52WeekChange` treats every ticker as US.
0700.HK (−13.6%) is scored against the S&P (+18.3%) for a −31.9% relative reading.
[docs/scoring-system-design.md:89](docs/scoring-system-design.md#L89) specifies this
formula and flags a sector-ETF-relative upgrade as future work.
**Options:** keep as "relative to global equity", or benchmark HK names to `^HSI`
(costs one extra fetch). Investment judgement, not correctness.

### 🔵 HK stocks still use the USD risk-free rate, and ERP is flat 5% everywhere

The tax rate is fixed (HKD → 16.5%), but `_wacc()` still applies the US 10Y to HK
issuers and `EQUITY_RISK_PREMIUM = 0.05` is constant across every market and period.
The HKD peg makes the risk-free proxy defensible; a flat global ERP is a simplification
with no such excuse. A HKD government-bond yield and a per-market ERP would be the
correct inputs.

### 🔵 HK charts still have almost no event markers

SEC filings gave US tickers ~5 years of dated events (AAPL: 278 events, 140 dates),
but EDGAR has no CIK for HK listings, so `0700.HK` falls back to the ~10 news dates
yfinance provides. The chart states this rather than looking broken.

**Options:** accept the asymmetry; scrape HKEX news/announcements (they publish a
filings feed, but it is not in OpenBB and would need its own adapter); or drop event
markers for HK entirely so the gap is not implied to be a bug.

### 🟡 Volume pane shows no intermediate axis ticks

Volume now has its own pane and scale, so it can no longer be misread against the
price axis — but lightweight-charts renders only the last-value badge (`49.18M`) in
a pane that short, not tick labels. A custom price formatter was tried and reverted:
it changed the badge format without producing ticks. The value is legible from the
badge and the hover legend, so this is cosmetic.

**Fix if it matters:** a taller volume pane, or a hand-drawn axis overlay.

### 🔵 Historical news — pay, work around, or drop

Measured 2026-08-02 (details in `CHANGELOG.md`):

| Option | Cost | Depth | HK |
|---|---|---|---|
| Tiingo paid | plan-dependent | ~7 months backfill only | ❌ |
| FMP Starter | $22/mo billed annually | unknown, untested | ❌ US-only |
| **SEC filings** (`provider="sec"`) | **$0, no key** | **2.5 y** (AAPL: 200 filings, 8-K/10-Q/Form 4) | ❌ US-only |
| status quo (yfinance) | $0 | ~10 recent stories | ~same |

**No option on this list solves HK news.** That needs a non-OpenBB source (AAStocks,
ET Net, or similar) and is a separate project.

SEC filings are the only free improvement, but they are a **new feature, not a data-source
swap** — 8-K/10-Q are regulatory events, not headlines, and the chart's COMPANY/MACRO tags
would need a third category. Decide whether you want that before it gets built.

---

## Done

### ✅ 2026-08-06 (c) — price chart

Verified in a real browser over CDP, not by inspection. Details in `CHANGELOG.md`.

- **Volume read against the price axis** — the data was correct all along; the
  histogram was overlaid on the price pane with a hidden scale. Volume now has its
  own pane and axis.
- **News dots flashed and were unclickable** — the popup sat under the cursor and
  fought the chart for mouse events. Now a click-through preview plus a click-to-pin
  panel; verified stable on 20/20 jitter samples with a working SEC link.
- **Only 2 dots** — the chart was already drawing everything it had; yfinance gives
  AAPL 3 distinct news dates. SEC filings added 278 events over 140 dates, so a 5-year
  chart went from 2 markers to 142 (62 with insider filings off).
- **Markers required an exact date match** — events on non-trading days produced no
  dot, and the ±3-day popup window disagreed with the dots. Both now snap to the same
  next-trading-bar.
- **No filtering** — per-category chips with live counts; toggling no longer rebuilds
  the chart and loses your zoom.
- **Thin interaction set** — added magnet crosshair, Lin/Log/%, zoom ±, Reset and
  double-click-to-fit.

### ✅ 2026-08-06 (b) — valuation accuracy

Measured before/after in `CHANGELOG.md`.

- **Unvetted beta** — XOM's reported 0.173 swung its upside 79 points. `resolve_beta`
  now bands the reported value and substitutes a peer median (min. 2 credible peers).
- **Flat credit spread** — every issuer paid `rf + 1.5%`. Now a synthetic-rating
  ladder on interest coverage; MSFT 0.6% vs O 3.0%.
- **Single 5-year fade** — replaced with two-stage 5+5. Also cut terminal value from
  72–88% of EV to 51–66%.
- **Terminal value invisible** — now reported with a >75% warning, alongside the
  implied exit EV/EBITDA vs today's multiple.
- **HK taxed at 21%** — now 16.5% via listing currency, in both WACC and ROIC.
- **FCF / net-income period drift** — `_statement_fcf` returns its period and
  `fcf_conversion` is pinned to it.
- **Peers limited to 21 tickers** — FMP fallback behind the curated map; ASML went
  from 0 peers to 4 and its football field from 2 bars to 3.

Checked and found **not** broken, so left alone: interest-expense sign, DuPont period
alignment, `sharesOutstanding` vs `marketCap/price`, and the `revenue_cagr_3y` window.

### ✅ 2026-08-06 (a)

- **Scorecard used the FCF source the DCF fix rejected** — `fcf_yield` and
  `fcf_conversion` read `info["freeCashflow"]` (a single quarter for MSFT/GOOGL). Now
  statement-first with a fallback flag. See `CHANGELOG.md` for measured impact.
- **Scorecard hid that a pillar was excluded from the composite** — `ScorecardTab` now
  branches on `data.insufficient`, not just `score === null`.
- **No caching** — 15-minute TTL on `get_fundamentals` / `get_peer_snapshot`;
  `get_quote` left live. 2.57 s cold → 0.0000 s warm.
- **`full_analysis()` was not guarded** — now wrapped, returns 502 with a message.
- **Local AI blocked a threadpool worker for up to 300 s** — all AI endpoints are async
  and stream NDJSON; blocking calls go through `asyncio.to_thread`.
- **No CI** — ruff + pytest + oxlint + vite build on push and PR.
- **No memory** — SQLite score history with the price at scoring time.
- **No screening** — Screener tab and `POST /api/score/batch`.
- **No portfolio layer** — Portfolio tab with weights, P&L and concentration.
- **Single-perspective AI** — bull → bear → verdict debate.
- **Irreproducible AI** — `temperature: 0`, fixed seed.

---

## Deliberately not doing

### ⚪ Full `get_fundamentals` migration to OpenBB

The `info` dict carries ~42 fields that yfinance returns in one call. OpenBB has no
equivalent single endpoint — it would take `equity.profile` + `fundamental.metrics` +
`price.quote` + `estimates.consensus` stitched together, with different field names
throughout, and `fundamental.income/balance/cash` are `402` on the FMP free tier anyway.
High risk, no measured gain. yfinance stays the fundamentals source.

### ⚪ `get_history` migration to Tiingo

Works on the free tier, but returns materially the same bars as yfinance for this app's
purposes. No reason to spend the quota.

### ⚪ Rewriting the curated peer map

FMP peers are worse than the curated list where the list exists (see above). Keep both.

### ⚪ HTTP-layer (TestClient) tests

Starlette's `TestClient` needs `httpx`, which is not installed, and the OpenBB install
already demonstrated that adding packages to this venv can shift `fastapi`/`uvicorn`
versions. The endpoints are thin wrappers over tested functions; they were smoke-tested
live instead. Revisit if the endpoint layer grows real logic.
