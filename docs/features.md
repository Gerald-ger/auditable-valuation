# Features, tab by tab

What each of the six tabs does and why it does it that way. Split out of the README on
2026-08-28; the architecture diagram it belongs under is still
[there](../README.md#architecture).

[← back to the README](../README.md)

---

- **Header — search**: type a ticker *or* a company name and pick from the list;
  typos resolve (`microsft` → MSFT, `tencnt` → 0700.HK) so a slip cannot produce an
  empty chart. Backed by a local cache of SEC's 10,398 US symbols (fetched once through
  OpenBB, free, no key, 2–3 ms) merged with live Yahoo search, which is what reaches HK
  and other non-US listings. Watchlist, holdings and recently viewed tickers sit below as
  one-click chips.
- **Tab 1 — Tracker**: price chart for US + HK tickers (`AAPL`, `0700.HK`, …) with:
  - bars sized to the period — **1-min** for 1d, **5-min** for 5d, **hourly** for 1mo,
    **4-hour** for 3mo, **daily** for 6mo/1y/2y, **weekly** for 5y and max. Daily rather
    than hourly from 6mo up because the indicators are daily-line conventions and the
    chart counts *bars*: a one-year chart at 1h drew a fourteen-**hour** RSI under the
    label RSI(14), and an MA50 spanning 7.7 sessions instead of fifty days. Three
    measured Yahoo limits bound the rest — sub-hourly data is last-60-days only, hourly
    is last-730-days, and a monthly response is capped at 500 bars, which is why `max`
    is weekly rather than monthly (at monthly it would start XOM in 1985 instead of
    1962, silently);
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
    maths lives in [frontend/src/indicators.js](../frontend/src/indicators.js); the window
    set and the volume histogram are assembled in
    [frontend/src/components/PriceChart.jsx](../frontend/src/components/PriceChart.jsx);
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
    [backend/drawings.py](../backend/drawings.py) computes where the line sits today, its
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
    context ([backend/ai_client.py](../backend/ai_client.py)), so roughly its opening 21.2%
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
  **The DCF is not the only model here.** A bank has no `CFO - CapEx` and a REIT's capital
  expenditure is acquisition rather than maintenance, so those types get the model that fits,
  chosen from the same classification the scorecard uses: **excess return** for banks and
  insurers (book equity plus the present value of the return-on-equity spread over the cost of
  equity, with the spread and the payout ratio the terminal phase implies both printed as the
  assumption they are), and a **two-stage dividend discount computed per share** for REITs -
  per share because REITs issue equity to buy property, so on `O` the aggregate dividend
  compounds at 17.22% against 4.43% per share. Both carry editable assumptions through
  `POST /api/stock/{ticker}/intrinsic`, and both may **refuse**: `O`'s cost of equity regresses
  to 6.20% against a 7.30% pre-tax cost of debt, and a model that discounts a shareholder's
  cash flow at less than the lender ahead of them reports nothing rather than a number. The
  inputs are rendered above that refusal, not below it, so the refusal is arguable.
- **Tab 3 — Scorecard**: deterministic 0–100 score and S/A/B/C/D tier per company, built
  from five pillars (Valuation, Quality, Health, Growth, Momentum) weighted by a sector
  library ([backend/sector_weights.py](../backend/sector_weights.py) — banks, REITs,
  pre-profit companies get substituted metrics). Opens with a **computed verdict line**
  naming the strongest and weakest pillar (composed from the scores, not written by the
  AI, so it works offline and never invents a figure). Includes a valuation-range
  "football field" — one price rule across all methods, a labelled axis, and a
  `price above` / `price below` / `in range` read per method. The chart **refuses to draw
  a method that does not apply** (a bank or REIT gets a struck-out DCF row with the
  reason, not a confident wrong number) while drawing the model that *does* apply beside
  it - an excess-return or dividend-discount bar quartiled from its own sensitivity grid,
  so "the DCF does not fit here" and "there is no valuation here" stay different
  sentences, suppresses an EV/Revenue multiple whose peer
  margins are not comparable, treats analyst targets as context rather than a vote, and
  leads with a **bridge** decomposing the distance from the model's value to the price
  into named steps ending in an explicitly unexplained residual. Below it sit an editable
  peer-comparison table and an optional AI-written explanation of the score. The tab also
  shows **score history** —
  every scoring writes a dated row, charted against the price recorded at the time — and
  a **bull vs bear debate** run as three separate AI passes (bull → bear → verdict), so
  disagreement stays visible instead of being averaged into one hedged paragraph.
  Design rationale: [docs/scoring-system-design.md](scoring-system-design.md).
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
- **Tab 6 — API Key**: the one credential this platform reads. Saving makes one real call to
  FMP **first**, and writes `~/.openbb_platform/user_settings.json` only if the key comes back
  working — so trying a key out cannot cost you the one you already have. Read-modify-write:
  anything else in that file, including other providers' credentials, survives untouched, and
  the previous version is kept as `user_settings.json.bak`. Withheld in demo mode — a key
  would change nothing there, and the machine storing it may not be yours.

All AI features degrade gracefully: until Ollama is installed the site shows an
"AI offline" notice and everything else keeps working.
