# Changelog

Notable changes to the Stock Analysis Platform. Newest first.

Format note: entries record *what changed and why it mattered*, with the measured
before/after where a change moved numbers the UI displays.

---

## 2026-08-07 (c) — GMT+8 clock, 1-minute bars, chart drawings

### Fixed

- **The chart showed UTC, which matched neither the exchange nor the reader.**
  yfinance returns exchange-local timestamps and the backend converts them to
  epochs correctly, but lightweight-charts renders an epoch as UTC and has no
  timezone setting. Measured: AAPL's 09:30 ET open drew as **13:30**, and
  0700.HK's 09:30 HKT open drew as **01:30**. Intraday bars are now shifted to
  **GMT+8** at the chart boundary (`charttime.js`), one clock for every market.
  Daily and weekly bars are date strings and pass through untouched — a US daily
  bar dated 2026-08-06 is that session, not a moment to be shifted.
  Consequence, stated in the UI: a US session runs **21:30 → 03:59** in GMT+8 and
  therefore spans two calendar dates. Inherent to the choice, not a defect.

### Changed

- **1-day charts use 1-minute bars** (was 2m): 390 bars, the finest Yahoo serves
  and its most rate-limit-prone feed. No indicator behaviour changes — day-based
  windows already exceeded a single session at 2m.

### Added

- **Trendline and horizontal-level drawing tools.** lightweight-charts@5.2.0
  ships *no* drawing tools (checked: `TrendLine`/`DrawingTool`/`LineTool` — zero
  matches), only the primitive API, so the renderer, hit-testing, drag handles
  and pixel↔price/time conversion are all custom (`drawingPrimitive.js`).
  Draw, select, drag either endpoint, delete, clear. While a tool is active or a
  handle is held, the chart's own pan/zoom is switched off so the canvas does not
  fight the cursor for the gesture.
  Persisted in SQLite per ticker as **true UTC epochs**, never chart-space time,
  so a drawing survives a change of display timezone. `store.py`, `main.py`
- **The local AI can read your drawings** — through the deterministic engine, not
  by looking at pixels. `drawings.py` computes the price on the line today, its
  slope per day, distance from current price, and how many bars came within 0.5%
  of it; the AI receives those figures and comments on them. Every drawing is
  tagged `drawn_by: "user"` and the context block says in words that these are
  the reader's assertions rather than engine output — without that the model
  would discuss a hand-drawn level as though the system derived it, which is the
  one thing the AI in this app must never do.
  **Unverified end-to-end:** Ollama is still not installed, so the geometry is
  tested offline but no model has ever consumed it. See `TODOLIST.md`.

### Tests

153 offline (was 140): 13 new in `test_drawings.py` covering line extrapolation
beyond the drawn segment, degenerate (vertical) trendlines, touch counting at the
0.5% tolerance, and the user-assertion labelling that keeps a drawn level from
reading as a computed one.

---

## 2026-08-07 (b) — Ticker search, finer chart bars, day-based indicators

### Added

- **Typo-tolerant search box with a clickable result list**, replacing the bare
  text input that sent whatever you typed straight to yfinance — one wrong
  character produced an empty chart and no explanation.
  Two tiers, merged on one relevance scale (`search.py`):
  - **local**: SEC EDGAR's symbol/name list via `obb.equity.search(provider="sec")`
    — 10,398 US symbols, free, no key, cached to disk for 30 days. Fuzzy-matched
    with difflib. **2–3 ms** warm.
  - **remote**: `yf.Search`, the only route to Hong Kong and other non-US names.
  Ranking is tiered so an exact symbol always wins, but a remote hit outranks a
  local *name* match — the measured failure being that "tencent" matched Tencent
  **Music** (a US listing) while 0700.HK, the wanted answer, fell off the list.
  - Latency work: a first pass took **1.85 s** on "microsft" scanning all 10,398
    rows twice. Bucketing fuzzy candidates by first character plus difflib's own
    `real_quick_ratio`/`quick_ratio` prefilters brought the local tier to 2–3 ms.
    The trade-off is stated in the code: a typo *in the first character* is not
    corrected.
  - `enable_fuzzy_query=True` on the Yahoo call, which is **off by default**.
    With it off Yahoo returns nothing at all for `microsft` or `tencnt`; with it
    on both resolve (and `tencnt` -> 0700.HK), and the call gets *faster* —
    1645 ms -> 278 ms, because the no-match path is the slow one. A 3 s timeout
    keeps a slow lookup from stalling a per-keystroke dropdown.
- **One-click chips** under the search box for watchlist/holdings (new
  `/api/portfolio/tickers` — deliberately separate from `/api/portfolio`, which
  prices every position live) and recently viewed tickers (`recents.js`,
  localStorage).

### Changed

- **Chart bars are much finer up to 2 years** (`PERIOD_INTERVALS` in `main.py`).
  Measured against live Yahoo responses, because these are hard API limits:

  | period | was | now | bars |
  |---|---|---|---|
  | 1d | 15m | **2m** | 195 |
  | 5d | 60m | **5m** | 390 |
  | 1mo | 1d | **30m** | 299 |
  | 3mo / 6mo / 1y / 2y | 1d | **1h** | 441 / 868 / 1,749 / 3,487 |
  | 5y / max | 1d | 1d / 1wk | — |

  **5y and max cannot go finer.** Sub-hourly data is capped at the last 60 days
  (3mo at 30m returns *zero* bars) and hourly at 730 days (5y at 1h returns
  *zero* bars). `/history` now falls back to daily rather than rendering an
  empty chart when a name has no intraday history.

- **Indicator windows are now measured in trading days, not bars.** Every period
  in `indicators.js` counted bars, so finer candles silently redefined every
  indicator: on 1h bars "MA50" was a 50-bar ≈ **7.2-trading-day** average, and
  RSI(14) was ≈ 2 days. This already affected the 1d/5d tabs before this change;
  serving intraday bars up to 2y would have spread it across the whole chart.
  `/history` now returns a measured `bars_per_day` — derived from the data, not
  hard-coded, because Hong Kong's session is shorter than New York's — and
  `barsForDays()` converts. MA50 on a 1y hourly chart is now a 350-bar average,
  which is 50 trading days, as the label says.

  Consequence, stated plainly: a window that needs more history than the period
  holds is **not drawn**, because a 50-day average does not exist inside one
  session. On 1d and 5d no moving average is available; on 1mo, MA10 and MA20
  are, MA50 is not. The chart says which and why rather than drawing a
  differently-meaning line under the same label.

### Tests

140 offline (was 119): 21 new covering search ranking, typo tolerance, remote
failure degradation, the period->interval contract (including the two zero-bar
limits above), and `bars_per_day`.

---

## 2026-08-07 — Comparability, beta methodology, forensic checks

Acts on the priorities in [docs/quant-review-2026-08-06.md](docs/quant-review-2026-08-06.md)
§6 and four defects found reading the code afterwards. Every figure below was
measured against the seven committed fixtures with the risk-free rate pinned.

### Fixed

- **The Screener ranked across company types, which is not a defined comparison.**
  `score_batch` sorted every card by `composite_score` regardless of
  classification, and the UI numbered the result 1..N. Two composites from
  different profiles are outputs of different formulas: the profiles score
  different metric sets (RIVN's valuation pillar was one metric, AAPL's four),
  weight the pillars differently (G is 35% for pre-profit and 10% for a bank),
  score some shared metrics on different anchor curves (`RELAXED_ND_EBITDA`),
  and renormalize around whichever pillars had coverage.
  **Measured:** holding every pillar score fixed and changing *only* the weights
  to one common ruler moved three of seven positions — RIVN 2nd→6th, JPM 4th→2nd,
  O 7th→4th. Ranking is now grouped by classification and never crosses one;
  single-member groups are marked `comparable: false` and left unranked.
  On the default seven-ticker input only `technology` has two members, so the
  tab now shows plainly that there was almost no valid ranking in it.
  `main.py:score_batch`, `ScreenerTab.jsx`

- **The classifier read the one field the codebase had already rejected.**
  `classify()` chose `pre_profit_growth` off `info["freeCashflow"]`, which
  yfinance reports annually for some issuers and for a single quarter for others
  (MSFT 16.4B vs 67.0B on the statement, 0.24×). That field decides the
  *profile*, and the profile decides the whole model — a misroute changes every
  metric and weight, not one number. Now takes the period-verified statement FCF
  the rest of the app uses. **No fixture changes classification**; this closes a
  latent hazard rather than a live wrong answer. `sector_weights.py`, `scoring.py`

- **The football field drew the DCF bar from the sensitivity grid's corners.**
  The reference doc (§5.2) specifies the 25th–75th percentile; the code took
  min/max, which is the compounded worst and best case of two assumptions moved
  together. **Measured widths:** AAPL 55.27→26.73, MSFT 132.95→64.00, XOM
  30.26→14.42, O 32.50→14.31, 0700.HK 330.00→149.08. The width was load-bearing:
  0700.HK read `in range` only because of the corners and reads `price below`
  against the interquartile band. `comps.py`

- **The Momentum pillar contained a metric that opposed the other three.**
  `price_vs_200dma`, `range_52w_pos` and `rel_52w_change` all reward price going
  up; `analyst_upside` rewards price being *below* a target, so a rally raised
  three and lowered one and they partly cancelled. It is a valuation signal and
  now sits in the Valuation pillar for every profile. **Measured:** momentum
  moves up to 18 points (0700.HK 42→24), composite −3 to +1, AAPL crosses B→A
  (64→67). `sector_weights.py`

- **`ffo_yield` is not NAREIT FFO** — it is net income plus total D&A, with no
  deduction for gains on property sales. yfinance exposes no gain-on-sale-of-real-
  estate row at all, so the correct figure cannot be built from this source. The
  computation is unchanged (candidate adjustments scored 69–77 against 71 on O,
  ~0.5 composite points) but cards that score it now carry `ffo_yield_is_proxy`
  instead of implying a precision the data cannot support. `scoring.py`

### Changed

- **Peer betas are unlevered before the median and re-levered to the target**,
  per reference doc §1.1.2 — previously a raw levered median, which imported the
  peers' balance sheets along with their business risk:
  `Bu = Bl / (1 + (1-Tc)·D/E)`, then re-levered at the target's own D/E. Needs
  each peer's leverage, so `get_peer_snapshot` now carries `total_debt` (free —
  same `info` call). Degrades in order: re-levered median → levered median (when
  too many peers lack leverage) → neutral 1.0, and the result is held inside the
  same credibility band as a reported beta. `beta_source` records which path ran.
  This is the [Simply Wall St](https://github.com/SimplyWallSt/Company-Analysis-Model)
  spec item with the best evidence-per-hour; their published ERP and 5-year-average
  risk-free rate are **not** done (the free `treasury_rates` call returns only
  1 year — 249 rows, mean 4.27% vs spot 4.63%). Their terminal-growth-equals-10Y
  rule was deliberately **not** adopted: at a 4.6% yield it sets terminal growth
  above long-run nominal GDP, which reference doc §1.1.3 forbids.
  `financial_models.py`, `comps.py`, `data_provider.py`, `main.py`

### Added

- **Forensic checks panel** on the Scorecard: Altman Z, Piotroski F, Sloan
  accrual ratio, net share issuance — the four highest-evidence, lowest-cost
  gaps against GuruFocus, all computable from statements already fetched.
  **Displayed, never scored.** The composite already blends ~40 anchor curves
  that have never been validated against forward returns; four more unvalidated
  curves would move every score without adding evidence. Each row prints its
  published threshold so the reader applies it.
  Applicability is explicit rather than silent: Z returns `n/a` with a reason for
  banks and insurers (no working-capital or sales term) **and for REITs and
  utilities** — the O fixture scores 1.08, Altman's "distress" band, for an
  investment-grade REIT covering interest 2.0×, because Z's sales/assets and
  working-capital terms read an asset-heavy levered balance sheet as failure.
  Altman's Z'' variant covers those and is not implemented. `forensics.py`

### Tests

119 offline (was 94): 21 new in `test_forensics.py`, 5 new unlever/re-lever cases
in `test_valuation.py`. Golden snapshots regenerated — the diff is the record of
the pillar move and is reproduced above.

---

## 2026-08-06 (d) — Readability: ratio quality bars, revenue trend, scorecard verdict

Verified in a real browser over CDP.

### Fixed

- **The revenue trend chart could not show what it was for.** Bars were drawn as
  `revenue / max`, and because a mature company's revenue barely moves, every bar
  came out nearly the same length: AAPL's four years spanned **92.1%–100%** of the
  width — a 7.9pp visual difference for a real 8.6% change. XOM was worse: its
  revenue *fell* (−16.0%, +1.4%, −4.5%) and the bars did not show it at all.
  Truncating the bar axis would have made the difference visible by overstating
  it — a bar's length is its value — so the form changed instead, per the
  dataviz method (trend over time → line; above/below a baseline → diverging bar):
  - **level** is now a line with a near-range baseline, which is legitimate for a
    line and makes the shape readable;
  - **year-on-year change** gets its own zero-centred diverging bars, where the
    real spread lives.
  Every year's absolute revenue is still printed beside its bar, so no value is
  reachable only by hovering.

- **Revenue axis labels pointed at the wrong heights.** First pass placed the
  min/max labels at the top and bottom of the plot box while the line was inset
  by its padding. They are now pinned to the actual plotted y positions.

- **The football field's price marker was drawn inside every row**, so it read as
  a per-row tick rather than one reference. It is now a single rule spanning the
  plot with a value tag, plus a labelled min/mid/max axis and a per-method
  verdict (`price above` / `price below` / `in range`). The verdict wording is
  spelled out because "above" alone did not say *what* was above what.

### Added

- **Quality bars on every ratio.** The Financial Models tab showed raw numbers
  with no indication of whether they were good — the reader had to know from
  memory that a 1.0 current ratio is mediocre. Each ratio now carries the 0–100
  score the scorecard already computes from its calibrated anchor curves, as a
  small colour-banded bar. **No new thresholds were invented** — it reuses the
  engine covered by the golden tests, so the two tabs cannot disagree about the
  same number. Metrics a company's sector profile drops (EV/EBITDA for a bank)
  render a dashed "not scored for this type" bar rather than an empty gap.
  Measured on AAPL: EV/EBITDA 27.2 → **7**, operating margin 32.6% → **100**,
  current ratio 1.0 → **50**. `ModelsTab.jsx`

- **A computed verdict line on the Scorecard**, above the pillars: e.g. "Mixed
  overall at 64/100. Quality is the strongest pillar (82), valuation the weakest
  (22)." Deliberately composed from the pillar scores rather than written by the
  LLM — it must work with Ollama offline, never state a figure the engine did not
  produce, and say the same thing every time. It also names any pillar excluded
  from the composite and flags sub-HIGH confidence.

- `scoreColor` moved into `format.js` and shared, replacing the copy that lived
  in `ScorecardTab` — the Models tab needed the same banding and two definitions
  would have drifted.

### Changed

- The DCF panel title said "5-year FCFF", which stopped being true when the model
  became two-stage. It now reads "two-stage FCFF" and states the actual shape
  from the payload (`5 explicit years + 5-year fade`).
- Opening the Financial Models tab now also fetches `/api/score` (cached, so
  near-free) and therefore records a score-history row. Harmless — history is
  upserted once per ticker per UTC day, so it is the same row the Scorecard tab
  would have written.

### Not done (deliberately)

Two options offered and not chosen: expanding pillar metric detail by default,
and grouping the Scorecard into sections. Both left as-is.

---

## 2026-08-06 (c) — Chart: SEC event markers, volume axis, click-to-open, interactions

Verified in a real browser (headless Chrome driven over CDP), not by inspection.

### Fixed

- **Volume was drawn against the price axis.** The histogram sat on a hidden
  `priceScaleId: 'vol'` overlaid on the price pane, so the only visible axis
  beside 34M–132M volume bars was the *price* scale reading ~310. The data was
  never wrong — verified `auto_adjust=True` does not alter Volume and the API
  serves the true figures (AAPL 2026-07-06 = 53,590,000). Volume now has its own
  pane and its own scale, so it cannot be misread.
  *Known cosmetic limit:* in a pane this short lightweight-charts renders only
  the last-value badge (`49.18M`) and no intermediate ticks. Tried a custom
  price formatter to force them; it changed the badge format but produced no
  ticks either, so it was reverted rather than left as unexplained complexity.
  The value is readable from the badge and the hover legend.

- **News dots flashed and could not be clicked.** The popup was rendered under
  the cursor with `pointer-events: auto`. Hovering it took the mousemove away
  from the chart, the chart reported "cursor left", the popup unmounted, the
  chart got the cursor back, and it re-mounted — forever. Split into a
  `pointer-events: none` hover **preview** that cannot steal the cursor, and a
  **click-to-pin** panel that is the interactive one, with a close button.
  *Verified over CDP:* preview stayed visible on **20/20** jitter samples on the
  marker (the flash test), a click produced a pinned panel with a live link
  (`sec.gov/Archives/edgar/data/320193/...-index.htm`), and the panel survived
  the cursor moving away.

- **Markers only appeared on exact date matches.** A marker was drawn only where
  a bar's date equalled a news date, while the popup used a ±3-day window — so
  the dots and the popup disagreed, and any event on a non-trading day produced
  no dot at all. Events are now snapped to the next trading bar on or after
  their date (clamped to the last bar for events dated after it, e.g. today's
  news against yesterday's close), and both the dot and the lookup use that
  same bar.

### Added

- **SEC filings as chart events**, because the real cause of "only 2 dots" was
  the data, not the chart: yfinance returns 20 news items for AAPL spanning
  **3 distinct dates**, of which 2 fell inside the chart range. The chart was
  already drawing every dot it had. New `provider.get_filings()` (SEC via
  OpenBB — free, no key) adds **278 events across 140 distinct dates back to
  2021** for AAPL. Measured on a 5-year chart: **142 dot-bars, or 62 with
  insider filings off by default**, against 2 before.
  Filing types are mapped to categories (`10-K/10-Q → earnings`,
  `8-K → material`, `3/4/5 → insider`) and everything else — 144, SC 13G/A,
  PX14A6G — is dropped as chart noise.
  **US-only:** EDGAR has no CIK for HK listings, so `.HK` tickers return `[]`
  without paying a round-trip to fail, and the UI says so rather than leaving
  it unexplained.

- **`GET /api/stock/{ticker}/events`** — news + filings merged, with per-category
  counts and a `filings_supported` flag. Deliberately separate from `/news`:
  the AI context keeps consuming headlines only, because 217 Form 4 filings
  would crowd a 7B model's prompt out of the stories that explain a price move.

- **Marker type filter** — one chip per category with its live count; clicking
  toggles it. Insider filings (217 of 278 for AAPL) start **off**. Markers live
  in their own effect, so toggling a filter no longer rebuilds the chart and
  throws away your zoom.

- **Standard chart interactions**: magnet crosshair (snaps to OHLC), Lin/Log/%
  price-scale modes, zoom in/out buttons, Reset, and double-click-to-fit.
  Scroll-to-zoom and drag-to-pan already worked but were undocumented — the
  caption now says so.

### Verified, no change needed

Volume figures themselves: `auto_adjust=True` leaves Volume untouched, and the
served values match the source exactly.

---

## 2026-08-06 (b) — Valuation accuracy: beta, two-stage DCF, credit spread, jurisdiction tax

All measured on the committed fixtures with the risk-free rate pinned to 4.3% so
the before/after is not contaminated by treasury drift.

### Fixed

- **An unvetted beta was the single largest error in the whole valuation.**
  `_wacc()` trusted `info["beta"]` with only an `or 1.0` guard for `None`.
  yfinance reports **0.173 for XOM** — implausible for an oil major — which
  produced WACC 5.11% and made the stock look 33.9% undervalued. Sensitivity
  measured across the plausible range:

  | beta | WACC | fair value | upside |
  |---|---|---|---|
  | 0.17 (reported) | 5.11% | 203.02 | **+33.9%** |
  | 0.60 | 7.13% | 111.23 | −26.6% |
  | 0.90 | 8.53% | 83.69 | −44.8% |
  | 1.10 | 9.47% | 71.41 | −52.9% |

  A **79-point swing in upside from one field.** New `resolve_beta()` keeps a
  reported beta only inside `[0.3, 2.5]`, otherwise substitutes the median of the
  peers' betas, otherwise 1.0. The chosen beta, its source and the raw reported
  value are all returned so the substitution is auditable.
  *Live impact:* XOM upside **+32.8% → −55.7%**, scorecard 75 → **69**
  (`dcf_upside_pct` metric 84 → 0). `backend/financial_models.py`

- **Peer-median beta does not rescue the case that motivated it — and now says
  so.** Measured across sectors, peer betas are usually fine (AAPL 4/4 usable,
  JPM 4/4, KO 4/4, 0700.HK 3/4) but **yfinance's energy betas are broken
  sector-wide**: XOM's peers return CVX 0.488, COP 0.123, SHEL **−0.218**,
  BP **−0.212**. Only one clears the credibility band, and 0.488 is still
  implausible. A median of one observation is not a median, so `MIN_PEER_BETAS = 2`
  makes those cases fall through to the neutral 1.0 default rather than
  laundering a single bad number as "peer evidence".

- **Every company paid an identical cost of debt.** `cost_of_debt = rf + 0.015`
  was flat, so a net-cash issuer and a highly levered REIT were charged the same.
  Measured: all seven fixtures returned `cost_of_debt_after_tax = 0.046`,
  identical to four decimal places. Replaced with a synthetic-rating ladder keyed
  on interest coverage (EBIT / interest). *Live impact:* MSFT (55.4× coverage)
  and XOM (69.4×) pay 0.6%, O (2.04×) pays 3.0% — after-tax Kd 4.13% vs 6.03%.

- **Hong Kong issuers were taxed at the US 21%.** `tax_rate_for()` now resolves
  the statutory rate from the listing currency (HKD 16.5%, USD 21%); yfinance does
  not forward a country field through the `get_fundamentals` whitelist, so currency
  is the proxy. The same rate now feeds NOPAT in the `roic` metric, which had also
  been hardcoded at 21%. *Impact is small and was measured before being
  prioritised:* 0700.HK fair value 490.16 → 488.30 in isolation (0.4%), because tax
  only scales the debt leg and debt is 9% of that capital structure. 0700.HK
  `roic` metric 95 → 96.

- **FCF and net income could still drift apart.** `_statement_fcf()` and the
  net-income lookup scanned for their periods independently — they happened to
  agree on all seven fixtures, but nothing enforced it, which is how the FCF bug
  fixed earlier today arose in the first place. `_statement_fcf()` now returns
  `(period, value)` and `fcf_conversion` pins net income to that exact period via
  the new `_value_at()`, dropping the metric (with a
  `fcf_conversion_period_mismatch` flag) rather than computing a mixed-basis
  ratio. When FCF falls back to `info["freeCashflow"]` there is no verified period,
  so conversion is not computed at all.

### Changed

- **Two-stage DCF: 5 explicit years + 5 fade years, replacing a single 5-year
  fade.** The old shape compressed a durable compounder's entire growth phase into
  five years. *Measured (fair value, upside):* MSFT 179.89 → **319.49**
  (−63.1% → −34.5%), AAPL 112.68 → **143.99** (−63.8% → −53.7%), 0700.HK
  490.16 → **628.44** (+1.8% → +30.5%), O 19.29 → **23.18**.

  It also fixed the terminal-dominance problem as a by-product, which was not the
  stated goal: **terminal value fell from 72–88% of enterprise value to 51–66%**
  (XOM 88% → 51%, AAPL 72% → 55%, MSFT 73% → 60%), because ten explicit years
  capture value the perpetuity used to absorb.

- **DCF trust diagnostics** are now returned and shown in the Financial Models
  tab: `terminal_value_share` (with a >75% warning line, the conventional
  threshold above which the perpetuity rather than the forecast is driving the
  answer) and `implied_exit_ev_ebitda` — what multiple the terminal value assumes
  the market pays in year 10, next to today's multiple. This is the check that
  explains the mega-cap results: AAPL's DCF implies exiting at **8.5×** EBITDA
  against **27.2×** today, MSFT **5.0×** against **18.9×**. The model's negative
  verdict is an assumption of severe multiple compression, now visible instead of
  buried. The panel also surfaces the beta and its source, the credit spread and
  coverage, the tax rate, and the exact FCF period used.

- **Peer discovery falls back to FMP.** `suggest_peers()` keeps the curated map
  first — FMP is measurably worse where a curated list exists (UPS → HWM, GD, MMM)
  — and uses `obb.equity.compare.peers(provider="fmp")` only for the rest.
  Verified working on the free tier and it covers HK. *Impact:* ASML went from no
  peers to `MU, AMD, CSCO, AMAT` and its football field from 2 bars to 3.
  Successes are cached for the process lifetime; failures are not, matching the
  `risk_free_rate` convention. `backend/comps.py`

- `dcf_valuation()` stays a **pure function**. Peer betas are resolved by the
  caller and injected, and `main._peer_betas()` only fetches when the reported
  beta is already implausible — so the common path makes no extra network calls,
  the offline test suite stays offline, and the AI endpoints resolve it inside
  `asyncio.to_thread` rather than on the event loop.

### Score re-basing

Regenerating the golden snapshots moved three of seven fixtures. Every other
score is byte-identical.

| Ticker | Composite | Cause |
|---|---|---|
| XOM | 75 → **69** | beta 0.173 → 1.0; `dcf_upside_pct` 84 → 0 |
| 0700.HK | 73 → **75** | two-stage DCF + HK tax; `dcf_upside_pct` 52 → 82, `roic` 95 → 96 |
| MSFT | 72 → **72** | `dcf_upside_pct` 0 → 7 (valuation 31 → 33) |
| AAPL, JPM, O, RIVN | unchanged | AAPL's upside improved −63.8% → −53.7% but is still past the −40% anchor floor, so the metric stays 0 |

### Verified, no change needed

Checked against the fixtures before assuming a problem existed:
`Interest Expense` is reported **positive** by yfinance, so interest coverage was
never sign-flipped; the four DuPont inputs already resolve to one period on all
seven fixtures; `sharesOutstanding` agrees with `marketCap / price` to within
0.01% (RIVN 0.27%), so per-share fair value was never distorted; and
`revenue_cagr_3y` genuinely spans 3 years on every fixture.

### Still open

- The beta credibility band catches extremes, not a plausible-but-wrong 0.45.
- `EQUITY_RISK_PREMIUM` is still a flat 5% for every market and period, and HK
  issuers still discount at the US 10Y.
- XOM's growth input is 0% (analyst consensus), which does more work in its
  −55.7% result than the beta fix does. Growth sourcing was not in scope here.

---

## 2026-08-06 (a) — Score history, screener, portfolio; scoring FCF fix; async AI

### Fixed

- **The scorecard was still using the FCF source the DCF fix rejected.**
  The 2026-08-02 entry below fixed `dcf_valuation()` to read free cash flow from the
  cash-flow statement, but `scoring.py` was never updated and kept reading
  `info["freeCashflow"]` for **both** `fcf_yield` (valuation pillar) and
  `fcf_conversion` (quality pillar). Re-measured 2026-08-06, the field is still a
  single quarter for some issuers and annual for others: MSFT **0.244×**, GOOGL
  **0.309×**, 0700.HK 0.684×, XOM 0.875×, AAPL 1.091× of the annual statement.
  Worse, `fcf_conversion` divided that possibly-quarterly figure by net income taken
  from the *annual* income statement — a mixed-basis ratio, not a conversion rate.
  `extract_metrics()` now uses `_statement_fcf()` first and falls back to
  `info["freeCashflow"]` only when the statement lacks both legs, raising a new
  `fcf_from_info_unverified_period` flag when it does.
  *Impact* (fixtures, risk-free rate pinned): MSFT `fcf_conversion` metric score
  **7 → 30** and `fcf_yield` **21 → 38**, composite 70 → **72**; 0700.HK composite
  68 → **72** (valuation 46 → 59, quality 80 → 85); XOM 72 → **74**; AAPL 65 → **64**.
  Verified period alignment: `_statement_fcf` and the net-income lookup resolve to
  the same period on all six fixtures. MSFT's resulting 0.501 conversion is real —
  FY26 net income $133.7 B against $67.0 B FCF. `backend/scoring.py`,
  `docs/scoring-system-design.md`

- **Scorecard drew a full-width bar for pillars excluded from the composite.**
  `ScorecardTab` branched only on `data.score === null`, but a pillar can carry a
  real score *and* `insufficient: true`, in which case the composite drops it. A
  pillar could read 97 while contributing nothing. It now renders the score struck
  through with the availability percentage and an explicit "excluded from the
  composite" note. `frontend/src/components/ScorecardTab.jsx`

- **AI replies were not reproducible.** Ollama defaults to `temperature 0.8`, so the
  same question produced a different answer each time — next to a deterministic
  scoring engine. Now `temperature: 0`, fixed `seed`, `top_p: 1`.
  `backend/ai_client.py`

### Added

- **Score history (SQLite).** Every `/api/score/{ticker}` and every screener row
  upserts one row per ticker per UTC day into `backend/data/app.db`, storing the
  composite, all five pillars, tier, confidence, coverage — and **the price at
  scoring time**. That price column is the point: the anchor tables in `scoring.py`
  are hand-set heuristics that `docs/scoring-system-design.md` §5 admits are
  validated for consistency, not forward returns. Nothing was previously recorded,
  so the question could not even be asked. New `GET /api/score/{ticker}/history`
  and a composite-vs-price chart on the Scorecard tab. `backend/store.py`

- **Screener tab** — paste a list, score and rank it with the same deterministic
  engine. `POST /api/score/batch` (max 50 tickers, 4-way concurrent fetch,
  duplicates merged). Per `docs/scoring-system-design.md` §4.3, cards below 60%
  coverage are returned but marked `rankable: false` and excluded from the ordering
  rather than silently taking a place they cannot support. Measured: 6 tickers in
  5.1 s on a cold cache.

- **Portfolio tab** — watchlist and holdings with cost basis, live pricing,
  unrealized P&L, weights, top-1/top-3 concentration and a Herfindahl index. A row
  with 0 shares is a watchlist entry. The latest stored score is joined onto each
  row. `GET/POST/DELETE /api/portfolio*`

- **Bull vs bear debate** — `POST /api/ai/debate/{ticker}` runs three separate
  passes (bull → bear → verdict), each seeing the previous, instead of asking one
  model to hold all three views at once. The verdict is instructed not to split the
  difference and to name what would change its mind.

- **pytest suite, 57 tests, fully offline.** Replaces the hand-run
  `backend/test_scoring.py` assert script. Seven real `get_fundamentals` payloads are
  committed to `backend/tests/fixtures/` (280 KB), chosen to cover technology,
  bank, REIT, energy, pre-profit and HK paths plus MSFT as the FCF regression case.
  Golden snapshots of every card are checked in; regenerate deliberately with
  `UPDATE_GOLDEN=1` and review the diff. Verified the snapshots actually fail when
  the FCF fix is reverted (5 of 7 fixtures break; JPM and O correctly do not use FCF
  metrics). Live provider-contract tests are marked `network` and deselected by
  default. `backend/tests/`, `pytest.ini`

- **CI** — `.github/workflows/ci.yml`: ruff + pytest on Python 3.14, and
  oxlint + vite build for the frontend. `backend/requirements-test.txt` keeps the CI
  install to pytest/yfinance/pandas rather than the full 107-package runtime set.

### Changed

- **All AI endpoints stream.** `ai_client` moved from synchronous `requests` to
  `aiohttp`, and chat, outlook, narrative and debate are now `async def` returning
  newline-delimited JSON. Previously a 60–180 s CPU reply parked a uvicorn threadpool
  worker with a 300 s timeout and the UI showed nothing until it finished. Every
  blocking yfinance call inside an async endpoint goes through `asyncio.to_thread`,
  so moving to `async def` did not relocate the stall onto the event loop.
  Verified: `/api/health` takes 2.22 s alone and 2.23 s while a stream is running
  (the 2 s is the Ollama connect timeout itself), and three concurrent streams
  complete in 3.9 s versus 3.5 s for one. **No new dependency** — `aiohttp` 3.14.3
  was already present via OpenBB, and installing pytest shifted no versions.
  `AIUnavailable` becomes a terminal stream event rather than an HTTP error, because
  by the time the model fails the response headers are long gone.

- **TTL cache (15 min) on `get_fundamentals` and `get_peer_snapshot`.** One scorecard
  page load previously fetched the same ticker twice (`/api/score` plus
  `/api/stock/../comps`) on top of four peer snapshots. `get_quote` is deliberately
  left uncached — a live tracker must stay live. Measured: 2.57 s cold, 0.0000 s
  warm. `TODOLIST.md` deferred this until "the first FMP-backed endpoint entering the
  request path"; batch screening is the equivalent trigger, since it multiplies the
  repeat fetches by N. `backend/data_provider.py`

- `full_analysis()` is now wrapped by `_guard` on `/api/stock/{ticker}/analysis`, so a
  model-layer exception returns 502 with a message instead of a bare 500.

### Known gaps — deliberately not addressed here

- **The bull/bear debate and all streaming output are unverified end-to-end.** Ollama
  is not installed on this machine (`localhost:11434` unreachable), so only the
  offline path was exercised: all four AI endpoints emit a well-formed
  `ai_unavailable` event and the UI renders it. Token-level streaming, debate
  staging and reply quality have never been observed running.
- `_statement_fcf()` and the net-income lookup scan for their periods
  independently. They align on all seven fixtures and the golden tests will catch
  drift, but alignment is not enforced by construction.
- The methodology reference is still hard-truncated at 16,000 characters
  (`ai_client._reference_excerpt`), so the back half of a 1,087-line document never
  reaches the model. Retrieval instead of truncation is still open.
- Portfolio totals sum mixed currencies at face value with no FX conversion; the UI
  warns when holdings span more than one currency.

---

## 2026-08-02 — OpenBB installed; DCF correctness fixes

### Fixed

- **Momentum pillar was silently dropped from every scorecard.**
  `get_fundamentals()` whitelists the `info` fields it forwards, and five momentum
  inputs were missing: `twoHundredDayAverage`, `fiftyTwoWeekLow`, `fiftyTwoWeekHigh`,
  `52WeekChange`, `SandP52WeekChange`. Only 1 of pillar M's 4 metrics survived, so
  `available_fraction` (0.25) fell below the 0.4 threshold, `insufficient` was set, and
  the pillar's **15% weight was redistributed away** on every company.
  The bar shown in the UI came from `analyst_upside` alone and was badly unrepresentative
  — 0700.HK displayed momentum **97** while down 13.6% over 52 weeks.
  Verified all five fields are present for US and HK tickers alike.
  *Impact:* coverage 89–92% → **100%**, zero missing metrics. Composite moved −5 to +3;
  AAPL and KO crossed B → A. `backend/data_provider.py`

- **DCF base free cash flow could be off by 4x.**
  `dcf_valuation()` preferred `info["freeCashflow"]`, which yfinance reports annually for
  some issuers and quarterly for others — MSFT returned 16.4 B against a statement figure
  of 67.0 B (0.24x), rescaling the whole valuation. The statement is now the primary
  source and `info["freeCashflow"]` the fallback, recorded in `assumptions.fcf_source`.
  Added `_statement_fcf()`, which takes both legs from the **same** period; the previous
  fallback used two independent `_latest()` lookups and could pair this year's operating
  cash flow with last year's CapEx.
  *Impact:* MSFT fair value 37.57 → **166.50**; NVDA 25.84 → **50.59**;
  0700.HK 341.07 → **462.05** (upside −28.2% → −2.8%, scorecard 68 → 71).
  `backend/financial_models.py`

- **Risk-free rate was a hardcoded 4.3%**, ~38 bp stale against the actual US 10Y (4.68%).
  `_wacc()` now calls `data_provider.risk_free_rate()`, and reports the rate used in
  `assumptions.risk_free_rate`. `backend/financial_models.py`, `backend/data_provider.py`

- Provider interface was documented as "four methods" in both the module docstring and the
  README; it is **five** — omitting `get_peer_snapshot` would break the comps table and
  football field. `backend/data_provider.py`, `README.md`

### Added

- `risk_free_rate(fallback)` in `backend/data_provider.py` — US 10Y treasury yield via
  `obb.fixedincome.government.treasury_rates(provider="federal_reserve")`. Free, no API
  key. Cached once per calendar day; **failures are not cached**, so it resumes live rates
  as soon as connectivity returns. Sanity band `0 < rate < 0.25` guards against a provider
  switching to percent units. The `openbb` import is deferred into the function: backend
  startup stays at 1.3 s and only the first request that runs a DCF pays the ~4 s import.

- `backend/requirements.lock.txt` — 43 packages, the pre-OpenBB state. This is the rollback
  target if the `fastapi`/`uvicorn` downgrade ever causes trouble.
- `backend/requirements.post-openbb.txt` — 107 packages, the current state.

### Changed

- **OpenBB Platform 4.7.2 installed** into the existing venv: 41 MB, 66 wheels, no sdists
  (so no C compiler needed), on Python 3.14.6. Downgraded `fastapi` 0.141.1 → 0.136.3 and
  `uvicorn` 0.52.0 → 0.40.0; `pandas`, `numpy`, `pydantic` and `yfinance` were untouched.
  Verified after install: `pip check` clean, backend serves `/api/health` and
  `/api/score/AAPL`, `wacc_override` still honoured, football field intact, zero 500s.

- README corrected on three points that were **factually wrong**:
  the install size (~2 GB → 41 MB), the claim that OpenBB fixes sparse historical news
  (false on the free tier), and the claim that value turnover "becomes available with
  OpenBB" (unverified, now stated as not implemented).

### Investigated — no code change

- **Historical news is paywalled on both free tiers.** Verified by raw HTTP against each
  vendor, bypassing OpenBB: Tiingo `403 {"detail":"You do not have permission to access
  the News API"}`, FMP `402 Restricted Endpoint: not available under your current
  subscription`. Both keys are valid — the same keys return `200` on
  `tiingo/daily/AAPL/prices` and `fmp/stable/stock-peers`. **403/402 is a plan-entitlement
  refusal, not an authentication failure**; a bad key returns 401, which never occurred.
  Matches both vendors' published pricing (Tiingo News ✗ on free; FMP news starts at
  Starter $22/mo).

- **Caching layer deliberately deferred.** Installing OpenBB consumes no API quota, so it
  was not a prerequisite, and a cache actively obstructs integration debugging — you edit
  provider code, refresh, and get stale results. The correct trigger is the first
  FMP-backed endpoint going into the request path. See `TODOLIST.md`.

---

## 2026-07-31 — Initial platform

- FastAPI backend + React (Vite) frontend, three tabs: Tracker, Financial Models, Scorecard.
- yfinance data adapter behind a five-method `provider` interface.
- 5-year FCFF DCF with sensitivity grid, ratio analysis, DuPont decomposition, peer comps,
  football-field valuation ranges.
- Deterministic 0–100 scoring engine with a sector weight library and coverage-aware
  pillar weighting.
- Optional local AI (Ollama) for chat, outlook and scorecard narration — degrades to an
  "AI offline" state when absent.
