# Changelog

Notable changes to the Stock Analysis Platform. Newest first.

Format note: entries record *what changed and why it mattered*, with the measured
before/after where a change moved numbers the UI displays.

---

## 2026-08-14 (f) — the price is as fresh as the feed allows, and says how fresh

Backend **402 → 408 passing** (16 network-deselected), frontend 46.

### Changed

- **The price is refetched on a 60-second cache instead of riding the 15-minute fundamentals
  cache.** Measured: `/analysis` returned 441.0 twice seconds apart while the uncached `/quote`
  said 441.2, because the price sat inside `get_fundamentals`'s TTL. Stacked on Yahoo's own
  15-minute delay that put the valuation screen up to **~30 minutes** behind the market. It is
  now ~15 — the vendor's floor — and `/analysis` and `/quote` agree.

  Five places read the price and all five read the same two `info` fields, so one refresh point
  fixed the DCF upside, the football-field price rule, the gap bridge, the momentum metrics and
  the score history with no call-site changes.

  60 seconds rather than uncached because one page view fires several endpoints at once — a
  Scorecard load hits `/score`, `/peers` and `/comps` — so this is one quote fetch per view
  instead of three or four, while staying far inside the delay it exists to work around.
  `get_quote` remains uncached; the Tracker depends on that.

### Added

- **`price_as_of` and `price_delayed_by_minutes` in the DCF assumptions**, rendered in the audit
  row. Both are the vendor's own figures, forwarded rather than estimated. The price was the
  denominator of the headline upside and the only input on that screen carrying no provenance,
  while beta, FCF, the equity premium and the FX rate all state theirs.

### Not done, deliberately

- **Market cap is not refreshed with the price.** It feeds the WACC weights, so refreshing it
  would make fair value drift intraday with no filing having changed — a valuation that will not
  reproduce minute to minute. Leaving it also keeps P/E, P/B, EV/EBITDA and `fcf_yield` mutually
  consistent as of one snapshot rather than half-refreshed. Pinned by a test: two different
  prices must leave `fair_value_per_share` and `wacc` identical while `upside_pct` moves.
- **The batch screener keeps the snapshot price.** A stale quote cannot reorder a ranking, and a
  fetch per ticker would roughly double the network work of a fifty-name run.
- **Yahoo's 15 minutes stays.** `docs/data-sources-review.md` already records that no free
  source clears it for HKEX.

### Fixed

- **The refresh copies rather than mutates.** `get_fundamentals` output is TTL-cached and shared
  between requests, so writing a price into it would hand a later caller statements and a price
  from different fetches with nothing saying so. Asserted directly, and mutation-checked by
  making it mutate, which fails that test alone.

---

## 2026-08-14 (e) — the app notices when the backend is running old code

Backend **399 → 402 passing** (16 network-deselected), frontend 46.

### Added

- **`source_changed_since_start` on `GET /api/health`**, and a banner when it flips. A digest
  of `backend/*.py` is captured at import and re-checked per call.

  This exists because the equity-bridge panel shipped at 14:17 against a backend started at
  13:28, so the API never returned `diagnostics.equity_bridge`, the panel correctly rendered
  `null`, and the result was indistinguishable from a feature that had never been built —
  diagnosed by hand, for the third time in one day. `ErrorBoundary` already told the reader to
  suspect a stale backend; now the app says it before anything looks broken.

- **`/health` replaces `/ai/status` as the frontend's poll.** It already carried the same AI
  block, so one 30-second timer now answers both questions instead of adding a second.

### Fixed

- **The digest reads text, not bytes.** A byte hash looked correct and was wrong on Windows:
  measured 2026-08-14, `git checkout` restored `sector_weights.py` with **252 CRLF** where the
  running process had loaded LF, so the guard reported a stale server for a file `git status`
  called unmodified. A banner nobody can clear is a banner people learn to ignore. Pinned by a
  test, and mutation-checked by reverting to `read_bytes()`, which fails it.

### Not done, deliberately

- **`--reload` is not recommended, and the README now says why.** Tried here first: WatchFiles
  logged `detected changes in 'backend\main.py'. Reloading...`, the replacement worker never
  started, and the old process kept serving — *with the log claiming it had reloaded*, which is
  worse than no reload at all. It also orphaned a child holding port 8000 after the parent was
  killed, so the next start failed with `WinError 10048` and the socket had to be freed by
  hand. The health flag does the job without pretending to fix it.

---

## 2026-08-14 (d) — the equity bridge carries four of its five terms

Backend **389 → 399 passing** (16 network-deselected), frontend 46.

### Changed

- **The EV→equity bridge implements the identity its own reference document states.**
  `docs/financial-models-reference.md:38` specifies
  `EV − Net Debt − Minority Interest − Preferred + Non-operating Assets`. The model
  implemented one term; `dcf_valuation` never read the balance sheet. Three are now read
  from the newest balance-sheet date, and the fourth is reported without being adopted.

  | | now | was | minority interest | marked securities |
  |---|---|---|---|---|
  | **0700.HK** | **498.67 (+3.6%)** | 427.75 (−11.1%) | −11.23 | **+82.11** |
  | AAPL | 140.00 (−55.0%) | 134.67 (−56.7%) | 0 | +5.33 |
  | MSFT | 269.64 (−44.7%) | (−45.7%) | 0 | +4.89 |
  | XOM | 157.30 (+3.7%) | 158.98 (+4.8%) | −1.75 | +0.07 |
  | O | 36.00 (−42.6%) | (−42.8%) | −0.73 | +0.86 |

  Tencent's verdict reverses **without any assumption entering the headline**, because the
  635bn of securities is already carried at fair value in the filing. Two directions across
  the set (Tencent up, XOM down), and no tier moved.

- **Associates and joint ventures are shown and excluded.** 348.7bn, +45.06/share on
  0700.HK, printed beside the headline as `fair_value_including_associates` and kept out of
  it — the same treatment the normalised base year already gets. Cost is neither a market
  value nor a floor, and the filing does not say which way it errs.

### Added

- **An equity-bridge panel on the Models tab.** Before this, a grep of `frontend/src/` for
  `totalDebt`, `balance_sheet`, `minority`, `associate` or `invest` returned **zero hits** —
  the reader could not see a single balance-sheet line anywhere in the product, and none of
  the 27 existing caveat strings mentioned what the valuation leaves out. The panel prints
  every term with its per-share effect and how it is carried. A company with nothing to
  bridge gets one line saying so, rather than silence that reads as "nothing was checked".

### Fixed

- **A consistency trap in the making.** `net_debt` was subtracted at four separate places —
  the headline, the WACC × terminal-growth grid, the growth sweep and the normalised base
  year. A bridge applied to some of them would have printed a sensitivity table whose centre
  cell disagreed with the fair value directly above it. Both grids now assert that their
  centre cell *is* the headline; mutation-checked by reverting one site, which fails that
  test and nothing else.

- **No cross-year fallback in the new reads.** `_value_at`, not `_latest`. MSFT reports
  `Long Term Equity Investment` at 2025-06-30 and nothing at 2026-06-30, so `_latest` would
  have carried a year-old balance into today's valuation — the period-drift defect that
  produced FY2025 EBIT over FY2023 interest once already. A vanished row reads nil and is
  named; a row never reported is silently nil, because flagging that would warn on all seven
  fixtures and train the reader to ignore warnings.

### Not done, deliberately

- **Associates are not marked.** Adding them at carrying cost would flip Tencent a second
  time on a number the filing does not support.
- **`comps.ev_implied` still uses the one-term bridge** (`comps.py:222`), so peer-multiple
  bars and the DCF bar on the same football field now differ in basis by ~71/share on
  0700.HK. Changing it moves every peer bar on every company and every verdict read off
  them, which is a different blast radius; logged in `TODOLIST.md` with the next
  football-field change as its trigger.

---

## 2026-08-14 (c) — beta and relative strength are measured, not read

Backend **373 → 389 passing** (16 network-deselected), frontend 46.

### Changed

- **Beta is regressed from price history instead of read from the vendor.** New
  `backend/market_series.py` runs cov/var over five years of weekly returns against the
  home index — `^HSI` for `.HK` tickers, `^GSPC` otherwise — cross-checked to 1e-9 against
  numpy's covariance and a least-squares slope. It sits above the existing ladder; the peer
  and reported tiers keep their old order, so a history outage restores exactly the previous
  behaviour rather than a third one. The vendor figure stays on screen as a cross-check.

  | | was | now | composite | fair value |
  |---|---|---|---|---|
  | XOM | 1.0 *(neutral default)* | **0.2888** → 0.30 | 70 → **74** | **+103%** |
  | 0700.HK | 0.745 *(vendor)* | **1.3192** | 73 → **70** | −34% |
  | AAPL | 1.086 | 1.1546 | 65 → 65 | −4.6% |
  | MSFT | 1.099 | 1.1412 | 71 → 71 | −3.0% |

  Two directions, and no tier moved. XOM's +103% is the size of an error that was already
  there: a neutral 1.0 standing in for a company whose measured beta is 0.29.

- **Relative strength is measured against the index the company actually trades on.**
  `rel_52w_change` benchmarked every ticker to the S&P 500. Both legs are now computed from
  weekly closes; 0700.HK reads −23.79% against the Hang Seng where the S&P gave −45.15%.
  Falls back to the old vendor scalars when bars are unavailable, and flags it.

- **`_ttl_cached` now keys on every argument, not just the ticker.** It was fine while every
  cached method took nothing else. Caching `get_history` on the old key would have served
  the chart's 1y hourly bars to the beta regression's 5y weekly request, or the reverse.

### Added

- `backend/tests/fixtures/bars/` — weekly closes for the seven fixtures plus both indices,
  144 KB. `capture_fixtures.py` gained `--bars-only` / `--fundamentals-only`, because
  regenerating the statements refetches live data and would move every pinned figure with it.

### Fixed

- **A UI message that became an accusation.** `ModelsTab` printed "(reported X, **not
  credible**)" whenever beta came from anywhere but the vendor. Once a measured beta can
  outrank a perfectly credible vendor one, "we had something better" and "your data is
  untrustworthy" stop being the same statement. The backend now reports
  `beta_reported_credible` and the UI says "vendor X", adding "not credible" only when the
  band actually rejected it.
- **`.src-tag.peer_median_relevered` had no style.** The class is the whole source string, so
  `.peer_median` never matched it — that tag has rendered unstyled since the re-levering tier
  was added. Pre-existing; fixed here because the same rule needed a `.computed` variant.

### Corrected

- **A stale figure I propagated.** Three documents stated 0700.HK's relative reading as
  −31.9% (from −13.6% and +18.3%). Those were live figures from an earlier date; yesterday's
  data-sources review copied them from `TODOLIST.md` without re-measuring. Computed from the
  committed bars it is **−23.79%** against the Hang Seng, or −45.15% against the S&P.
- **"yfinance's energy betas are broken" was wrong.** The regression says they were
  directionally right — XOM's vendor 0.173, measured 0.2888 and peers at 0.488 / 0.123 all
  agree the correlation is genuinely very low. What was broken is `BETA_MIN = 0.3`, which
  rejected every one of those readings and substituted a number nobody measured. The floor
  now binds on a *measured* value, which is logged as an open calibration question.

---

## 2026-08-14 (b) — the equity risk premium is sourced, and the data layer is audited

Backend **366 → 373 passing** (16 network-deselected), frontend 46.

### Changed

- **The equity risk premium is per market instead of a flat 5%.** `EQUITY_RISK_PREMIUM =
  0.05` was one number for every market and every year, with no source and no date — the
  largest remaining hardcoded constant in the model. It is replaced by Damodaran's published
  country table, vendored dated at `backend/market_risk_premiums.json`.

  | Market | was | now | effect on fair value |
  |---|---|---|---|
  | United States | 5.00% | **4.46%** | AAPL +9.2%, MSFT +9.8%, XOM +9.2% |
  | Hong Kong | 5.00% | **5.01%** | ~nil |
  | China (0700.HK reports CNY) | 5.00% | **5.14%** | 0700.HK **−1.8%** |

  It moves US valuations up and Tencent's down. That two-directional result is what makes it
  a correction rather than price tuning, and a test pins it so a future snapshot update
  cannot quietly make it one-way.

  Keyed on `financialCurrency`, deliberately unlike `tax_rate_for`, which keys on the
  trading currency: tax follows the filing jurisdiction, a discount rate follows the money.
  0700.HK trades HKD and reports CNY, so it is priced off China's premium.

  Vendored rather than fetched — the data changes twice a year, so a parser on the request
  path would be fragile for no benefit and would put a network call inside the offline test
  suite. The Models tab now names which of the three sources a valuation used
  (`damodaran_<date>` / `mature_market` / `platform_default`).

- **Golden scores.** One line moved: 0700.HK's `dcf_upside_pct` 82 → 80. Every other name is
  anchor-clipped at the −40 floor and unchanged; no composite and no tier moved.

### Added

- **`docs/data-sources-review.md`** — what the platform's numbers are actually made of.
  Records that there is effectively *one* data source rather than four, the three occasions
  this codebase has already proven that source wrong, a gap table saying which needs a free
  source can and cannot close, and the two fixes that need no new source at all (beta from
  price history, HK momentum against `^HSI`).

- **The yfinance licence position**, newly recorded as an open decision. It is
  personal-use-only and Yahoo's terms prohibit redistribution, which is fine locally and is a
  **blocker to resolve before the app is hosted or shared**. Kept for now because no free
  source covers Hong Kong fundamentals — FMP's free plan is US-only and Finnhub's
  international coverage is paid.

### Fixed

- **A test that stopped measuring its own subject.**
  `test_correcting_the_currency_also_corrects_the_wacc_weights` builds its comparison by
  flipping `financialCurrency`, which now also selects the ERP — so it was no longer
  isolating the capital-structure weighting effect it is named for. The premium is pinned
  across both runs there now. A genuine side effect of this change, caught by the suite.

### Not done, deliberately

- **The risk-free rate stays the US 10Y for every issuer**, and after measurement that is a
  decision rather than a backlog item. China's ten-year runs ~1.70% against the US 4.30%
  (−260bp) while China's country risk premium is only 0.91pp, so the legs do not cancel as
  `TODOLIST.md` had hoped — sourcing the rate would roughly *double* Tencent's valuation.
  A second problem also surfaced: discounting CNY flows at a CNY rate and converting at
  **spot** ignores interest-rate parity, which implies a low-rate currency trades at a
  forward premium. Today's treatment is wrong in a named way; the naive fix would be wrong
  in an unnamed way. Gated until spot-versus-forward is settled in writing.

---

## 2026-08-14 — the DCF bar carries its third assumption, and radius gets a rule

Backend **357 → 366 passing** (16 network-deselected), frontend 46.

### Changed

- **The football-field DCF bar now spans the base year as well as the rates.** The bar
  stressed WACC and terminal growth through the sensitivity grid and the starting growth
  rate through `growth_sensitivity` — three rate assumptions, and none of them the level
  those rates are applied to. `_dcf_band` now unions `fair_value_normalised` in, so the bar
  shows what the company's own multi-year average margin implies alongside what its newest
  filed year implies. Fair value is homogeneous of degree one in base FCF, so a level error
  there is permanent and undamped; it was the largest assumption the bar did not carry.

  Fires on two of four fixtures (risk-free pinned at 4.3%), and in both directions across
  the set, which is what distinguishes a band from a thumb on the scale:

  | | reported | normalised | bar before | bar after |
  |---|---|---|---|---|
  | XOM | 71.75 | 102.17 | 59.25–86.35 | **59.25–102.17** |
  | MSFT | 248.51 | 321.75 | 211.58–290.97 | **211.58–321.75** |
  | AAPL | 129.29 | 144.27 | 109.76–151.89 | unchanged, already inside |
  | 0700.HK | 663.32 | **628.00** | 561.47–781.62 | unchanged, already inside |

  The basis string names `+ base year` only when it moved an edge, following the rule the
  growth sweep's one-sided wording already set. The midpoint tick still marks the
  reported-year answer: this is a union, not a substitution.

- **Corner radius is four tokens instead of twelve values.** `--r-tag: 4px`,
  `--r-control: 6px`, `--r-surface: 10px`, `--r-pill: 999px` over 31 of 42 declarations.
  Visible movement is small and deliberate: four chips 5 → 6px, five surfaces 8 → 10px.
  `.tier-badge` (14px), `.chat-msg` (12px), `:focus-visible` and the concentric
  `.ff-track` / `.ff-bar` pair are kept as specials with the reasoning written beside them.

### Fixed

- **Ten "radii" that were really `height / 2`.** `.pillar-track` and `.pillar-fill` are 8px
  tall at 4px, `.ff-envelope` 6px at 3px, the scrollbar thumb 8px at 4px — pills expressed
  as numbers. The earlier audit had counted them as radius choices, and the three-token
  plan it produced would have flattened them into squircles. They now use `--r-pill`, which
  is pixel-identical for the exact halves and imperceptibly rounder for `.quality-*` and the
  3px swatches, already over-rounded past their own half-height.

### Not done, deliberately

- **The cyclical headline swap stays declined**, now on measurement rather than principle.
  XOM's FCF margins run 14.65 → 9.99 → 9.05 → **7.29%**, monotonically down, where MSFT,
  AAPL and 0700.HK oscillate: the four-year window holds a trend, not a cycle, so its mean
  is a lagged trend rather than a mid-cycle estimate. Separately, `SECTOR_MAP` routes
  `basic materials` to `industrials`, so no clean cyclical classification exists to key on.
  The scoring objection turned out to be nearly empty — `dcf_upside_pct` is anchor-clipped
  at −40, so XOM's metric moves 0 → 9 of 100 and the composite stays 70, tier A — but the
  two findings above stand. The bar union above takes the part of the value that costs no
  assumption. Full reasoning in `TODOLIST.md`.

---

## 2026-08-13 — the football field triangulates, and the base year stops being free

Backend **254 → 357 passing** (16 network-deselected), frontend 44 → 46. Two questions
answered: what the valuation chart is actually claiming when its bars disagree, and what
the DCF assumes by taking one filed year as its starting point.

### Changed

- **The growth clamp is gone.** `[0%, 25%]` was two economic judgements dressed as data
  hygiene. The floor grew shrinking companies at zero — fourteen analysts put XOM at
  −2.3%, and flooring it inflated fair value **15.7%**. The ceiling truncated a **42.6%**
  consensus from 55 analysts on NVDA. Replaced by a validity range of −50% to +200% that
  **rejects** a corrupt figure rather than truncating a genuine one, with the provenance
  labelled either way, so no number on screen is untraceable.

- **The explicit stage went 5 years to 1**, with a 9-year fade after it. The growth figure
  is a *one-year* consensus; holding it flat for five invented four years nobody forecast.
  Measured: AMD's 72.1% consensus compounded free cash flow **15.1×** over five flat years
  before any fade began, which is why its fair value ran from −81.4% clamped to +33.6%
  unclamped. One year at the forecast rate then a linear fade gives **7.2× on NVDA against
  13.5×** for the old plateau — most of the conservatism the cap was reaching for, without
  discarding a basis point of observed data. This is what let the ceiling go; the ceiling
  existed to survive the plateau, not to express a view about growth.

- **`analyst_upside` is no longer scored in any pillar.** It divided *someone's forecast of
  price* by price, while every other valuation metric divides a reported figure or the
  platform's own model. Worse, `dcf_valuation` already takes its growth from analyst
  consensus, so one source moved two of five V metrics with correlated errors of the same
  sign. The scoring curve also anchored 0% upside at **45/100**, i.e. near-neutral, against
  published targets that sit above price structurally — the seven fixtures scored a mean of
  **69** against a centred 50. Removed from scoring, kept on screen as labelled context,
  matching what the football field already did. Composite moved **−3 to +1**; no fixture
  changed tier.

- **Terminal growth shows its derivation** instead of appearing as a bare 2.5%, held under
  two displayed ceilings: long-run nominal GDP, and the risk-free rate per Damodaran. The
  cap applies **only** to the platform's default — a caller naming a rate gets that rate,
  because `solve_for_fair_value` sweeps past both ceilings on purpose and capping it there
  would report "closing this gap needs 7.01% perpetual growth" as unreachable, which is the
  most useful sentence the reconciliation produces.

### Added

- **The base year is now shown as the assumption it is.** Free cash flow enters the
  valuation linearly, so a base year 22% below normal is a valuation 22% below normal —
  permanently, through every projected year *and* the terminal value. Measured across the
  fixtures, the newest reported year sits below that company's own mean FCF margin for
  three of the four profitable names: **AAPL 0.90×, MSFT 0.78×, XOM 0.71×**, with 0700.HK
  the exception at 1.06×. Taking whatever period the vendor reported last is therefore a
  one-directional bias, and unlike the terminal-growth band it does not wash out across
  names — it penalises whoever is mid-investment or mid-cycle, corrupting exactly the
  cross-name ranking a screener exists for.

  `base_year_context` decomposes the base year **exactly** — `FCF/revenue = CFO/revenue −
  capex/revenue`, no residual and no assumption — so the panel separates a business
  *spending more* from one *earning less*. MSFT is the case it exists for: capex ran 13.3%
  → 18.1% → 22.9% → **34.9%** of revenue over four years while operating cash *rose* 41.3%
  → 55.1%. The reported year stays the headline; the normalised figure sits beside it and
  the platform explicitly declines to choose, because whether that capex wave ends is a
  forecast about the world, not a figure in the accounts.

  **The direction is the whole argument.** Normalisation moves 0700.HK *down* (+29.8% →
  +22.9% upside) while moving MSFT (−49.0% → −34.0%) and XOM (−52.7% → −32.6%) up. A change
  that narrowed every gap to the market price would be a price tracker, not a model, and a
  test pins both directions so a future change cannot quietly make it one-way.

- **The football field refuses to draw what does not apply.** The DCF bar is gated on
  `sector_weights.dcf_applies`, the same rule the scorer uses, so a REIT gets a struck-out
  row naming the reason rather than a confident number the Models tab suppresses one tab
  away. `peer_ev_revenue` is suppressed when target and peer operating margins differ by
  more than 2×: on 0700.HK the curated peer set medians **5.7%** operating margin (9988
  1.0%, 3690 −7.5%, 1024 10.5%) against Tencent's **34.3%**, so the peer median 1.84×
  revenue multiple implied **189.61** a share against a **439–471** cluster from every
  other multiple. That single number stretched the comps bar to **2.48× wide** and was the
  sole reason its verdict still read "in range" — a bar that broad contains any price.
  Analyst targets became context rather than a vote, with dispersion carried separately as
  an uncertainty signal.

- **A conviction grade that never varied was replaced by arithmetic.** It read LOW on all
  eleven names tested and the overlap zone was non-empty **once**; a signal that never
  varies is not a signal. The chart now leads with a bridge decomposing model value → price
  into named steps ending in an explicitly *unexplained* residual. The residual is left
  that way on purpose: it is the market pricing a longer advantage period, a lower discount
  rate or a higher terminal cash conversion than a ten-year fade at 2.5% can express, and
  closing it by tuning would make the DCF an expensive way to display the share price.

- **Market-implied terminal growth**, solved backwards from today's traded multiple, which
  is the more useful direction to read an exit multiple. Measured: AAPL 7.30%, MSFT 7.63%,
  0700.HK 3.23% against a 4.0% nominal-GDP line — so Tencent's price needs nothing unusual
  while Apple's needs free cash flow compounding above the economy in perpetuity.

### Fixed

- **White-on-accent failed WCAG AA at 3.68:1** (4.5:1 required) on the primary button, the
  active nav tab, the period picker, the segment controls and the user's own chat bubbles —
  all 13-14px body text. The hover state measured **4.80:1**, i.e. *more* readable than the
  resting state, which is backwards. Filled surfaces now use `--accent-fill` (#2b6fd9,
  4.80:1) with `--accent-fill-hover` (#1d4ed8, 6.70:1); `--accent` still drives strokes,
  links, focus rings and chart bars, all of which already passed.

- **71 user-visible strings** had em-dash and en-dash punctuation restructured into periods,
  colons, commas and parentheses. The `—` no-data glyph returned by `num`/`big`/`pct` was
  deliberately **kept**: in a column of financial figures a hyphen reads as a minus sign,
  and that glyph is a table convention rather than prose.

- **Four defects in the above, caught by reviewing the work rather than by the tests.** The
  base-year panel quoted its ratio against the mean of *all* years and its two legs against
  the mean of the *others*, so a reader recomputing from the table on screen got −5.8pp
  where the sentence beneath said −7.7pp. The driver sentence claimed "spending more, not
  earning less" for XOM, where capex rose **and** operating cash fell — both legs adverse.
  A first fix for that keyed on the two signs alone and contradicted itself on 0700.HK,
  naming operating cash the larger leg and calling it "a business spending more" in the same
  breath; the six reachable combinations now resolve in the backend where they are tested.
  And rounding was applied per period then averaged, compounding a display artefact instead
  of landing once at the output.

---

## 2026-08-10 (b) — the two decisions the review left open

Both items the three-lens review deliberately did not settle alone, now decided. Backend
**246 → 254 passing, and the 3 xfails are gone** — the calibration below fixed the
behaviour they were pinning.

### Fixed

- **Cash runway ignored capital expenditure**, which for a pre-profit manufacturer is most
  of the burn. RIVN's 2025 operating outflow is **0.78bn against 1.71bn of capex**, so
  runway read **27.3 quarters** — past the anchor table's top rung at 20, scoring 100 —
  where the free-cash-flow burn gives **8.5 quarters and 63**. Overstated by **3.2×**, on
  the single metric the pre-profit Health pillar leans hardest on.

  The rate now comes from `_statement_fcf`, so both legs share a period by construction.
  The *trigger* deliberately stays operating-outflow-negative rather than moving to
  free-cash-flow-negative, because **capex is discretionary in a way that operating burn is
  not**: a company whose operations fund themselves can stop building and survive, and does
  not have a runway problem to measure. Trigger and rate answer different questions on
  purpose, and a test pins the distinction — the mutation that widens the trigger initially
  survived every other test in the suite.

- **The scoring engine failed its own written acceptance criterion.**
  `docs/scoring-system-design.md` §5.2 specifies that a pre-profit name lands in **Tier
  3–5** and that "no bankrupt-adjacent name outranks a mega-cap compounder". RIVN scored
  **74 / Tier A**, ahead of AAPL 67 and MSFT 73.

  Beyond the runway defect, the `pre_profit_growth` profile weighted the pillar these
  companies fail at **15%** (quality 10 — gross margin 7.5%, operating margin −50.4%) and
  the pillar they ace at **35%** (growth 98). For a pre-profit company "can this become
  profitable" *is* the quality pillar's question, so burying it under growth measured the
  wrong thing. Rebalanced to **Q 0.25 / G 0.25**.

  Measured together: RIVN **74 → 60**, Tier **A → B**, health pillar 82 → 63. Only RIVN
  moved — `cash_runway_q` appears in one profile and the weight change touches only that
  profile, so the other six goldens are byte-identical. The final ordering puts every
  mega-cap above the cash-burner, which is what §5.2 asked for.

  **Two limitations, stated because they do not go away.** First, this re-calibrates curves
  that have **never been validated against forward returns**; §5.2 is a plausibility
  expectation written down in advance, not a market fact, so enforcing it substitutes one
  judgement for another rather than adding evidence. Second — and this matters for the only
  reason `score_history` exists — **the pre-profit series breaks here**: rows recorded
  before today come from the old formula, rows after from the new one, and there is **no
  backfill**. Any future calibration study must treat 2026-08-10 as a discontinuity for
  `pre_profit_growth` and for nothing else.

- **The Portfolio tab made the comparison the Screener refuses to make.** `ScreenerTab`
  carries a prominent warning that composites from different profiles are not one
  measurement — citing "a bank's 70 and a pre-profit growth company's 74", which were the
  live JPM and RIVN values. `PortfolioTab` then rendered those same composites in one
  column, adjacent rows, with no classification and no caveat.

  `store.latest_scores` already returned `classification`; the endpoint was dropping it.
  Each score now shows the profile that produced it, and the table carries the Screener's
  caveat **in the Screener's own wording** — two tabs describing one limitation differently
  is how it got lost in the first place. Not grouped: weights, P&L and concentration are
  portfolio-level figures that need a single list, and the portfolio lists holdings rather
  than ranking them.

---

## 2026-08-10 — currency correctness, scoring guards, a crash, and the tests that were missing

Full three-lens review (finance / engineering / UI) run against every fixture by executing
the code rather than reading it. Backend **153 → 246 passing** plus 3 deliberate xfails;
frontend **22 → 44**. Every behavioural fix below was mutation-tested: reintroducing the
defect fails only the tests that own it.

### Fixed

- **A company's statements and its shares can be in different currencies, and the DCF
  compared them directly.** 0700.HK reports in **CNY** and trades in **HKD** — confirmed
  against Tencent's published FY2024 revenue of RMB 660,257m, which the fixture matches to
  the yuan. Enterprise value was built from statement cash flows and bridged with
  `totalDebt`/`totalCash` (which follow the statements), then divided by shares and
  compared against an HKD price.

  Which `info` field sits on which side of the rate is **measured, not assumed** — yfinance
  documents none of it. Against the quarterly statements, 9988.HK's `totalDebt` and
  `totalCash` come back at **1.0000** and **0.9998** (reporting currency), while 0700.HK's
  `bookValue` and `trailingEps` sit **1.13×** their statement equivalents against a CNYHKD
  spot of 1.1627 (trading currency). `financialCurrency` was not in the `info` whitelist,
  so the app could not previously detect the mismatch at all.

  Corrected at seven boundaries: the DCF equity bridge, the WACC capital-structure weights,
  `resolve_beta`'s peer D/E (each peer on its own rate), `fcf_yield`, `ffo_yield`,
  `comps.ev_implied`, and Altman Z's `equity_liabilities` term. Measured on 0700.HK —
  upside **+30.5% → +44.5%**, fair value **628.44 → 695.47 HKD**, `fcf_yield` score 64 → 68,
  composite **74 → 75**. The unit-free diagnostics (terminal-value share, implied exit
  multiple) are deliberately *not* scaled; the WACC does move (7.69% → 7.66%) because its
  weights were genuinely mixed.

  `fx_rate` returns **None** rather than a fallback constant when unreachable — a stale
  risk-free rate moves a valuation a little, a wrong FX rate rescales all of it. Callers
  then withhold the upside, drop the two market-cap yields, and report Altman Z as `n/a`
  with the reason. Pinned by `-m network` tests so a provider change cannot move every HK
  valuation silently.

- **A dividend cut to zero *improved* the valuation pillar.** yfinance omits
  `dividendYield` for a non-payer rather than sending 0, and `None` reads as *unreported*,
  so the metric left the pillar average instead of scoring its 20-point floor — raising the
  average it left behind. Measured on JPM, changing nothing else: **1.68% → 58, 0.10% → 51,
  zero → 60**. A suspended dividend beat a token one and recovered the whole composite,
  across exactly the profiles where a cut matters most (staples, utilities, REITs, banks,
  insurers). Now scored as zero, with `dividend_yield_assumed_zero` raised only where the
  profile uses the metric. Latent on the fixtures — both are payers — so six direct tests
  pin it.

- **A cost basis of `0` took down the Portfolio tab, unrecoverably.** `unrealized_pnl` and
  `unrealized_pnl_pct` do not share a null condition — zero cost is a real gain and an
  undefined return — and the renderer read the second off the first's guard. The
  `TypeError` fired inside the component's own render, so `ErrorBoundary` unmounted the
  whole tab *including the add/edit form needed to fix the position*: the only way back was
  deleting `app.db`. Reachable by typing `0` in a field whose sibling placeholder suggests
  `0`. The row arithmetic moved out of the endpoint into `main.position_values` so the
  contract could be tested at all — being inline is why the shape shipped unchecked.

- **Two ratios paired figures from different fiscal years.** `_credit_spread` and
  `ratio_analysis`'s interest coverage each called `_latest` twice, independently, and
  `_latest` walks back until it finds *anything*: AAPL resolved EBIT at **2025-09-30** and
  Interest Expense at **2023-09-30**, so the 33.8× coverage on screen — and scored 100 in
  the Health pillar — was a ratio of two different businesses. Both legs are now pinned to
  the newest period reporting both, and that period is displayed. AAPL reads **29.06× in
  2023**; both score 100, so no composite moved and the goldens could never have caught it.

- **The DuPont leverage cap fired on banks.** JPM's equity multiplier is 12.2 because
  deposit-funded intermediation is what a bank is, and the guard cut ROE **78.4 → 70** while
  raising `dupont_leverage_cap_applied` — which reads to a user as an accusation of
  financial engineering. The bank profile already measures capital adequacy properly via
  `equity_assets`. Exempted through `sector_weights.LEVERAGE_IS_STRUCTURAL`: JPM quality
  **75 → 79**, composite **70 → 71**, flag gone. AAPL (multiplier 4.9, ROE 149%) stays
  capped — that is what the guard is for. REITs are deliberately not exempt.

- **A missing debt figure read as a debt-free company.** `(totalDebt or 0)` moved AAPL's
  fair value **143.99 → 147.41** with nothing on screen to say why, while `ratio_analysis`
  correctly returned `None` for the same input. The DCF still computes — refusing to value
  a company over one absent field is worse — but now names the leg it assumed, on the audit
  row.

- **`null >= 0` is `true` in JS**, so an unavailable portfolio P&L rendered green. Same bug
  already fixed once on the DCF upside chip.

### Changed

- **A DCF is no longer presented as an answer for company types it does not fit.** O
  returned a confident **−63.0%** upside off a base cash flow that treats a REIT's property
  acquisitions as maintenance capex; a bank has no `CFO − CapEx` at all. The scoring engine
  already knew — both profiles drop `dcf_upside_pct` — so the card now exports
  `dcf_applicable` and the Financial Models tab states it. The model is still shown; it is
  not shown as a result.
- **The DCF panel names its currency.** An unlabelled `628.44` sat four lines under a header
  reading `Mkt cap 4.33T HKD`, in a different unit. Where a conversion happened the audit
  row states the reporting currency and the rate used.

### Added

- **`tests/test_plausibility.py` — the §5.2 acceptance criteria as assertions.** The design
  doc specifies "RIVN … Tier 3–5" and "no bankrupt-adjacent name outranks a mega-cap
  compounder"; RIVN scores **74 / Tier A**, above MSFT 73, JPM 71, XOM 70 and AAPL 67. The
  profile weights the pillar it fails at 15% (quality 10 — operating margin −50.4%) and the
  one it aces at 35%, and `cash_runway_q` reads 27.3 quarters because it divides cash by
  operating burn and ignores capex.

  Nobody noticed because **`golden_scores.json` had recorded 74/A as the expected value**.
  Snapshot tests catch unintended change and are structurally blind to a wrong answer that
  never changes — the third time that limitation has bitten this codebase. Filed as
  `xfail(strict=True)`: reported in every run, and an error the moment a calibration change
  fixes it. The remedy is a pending decision, recorded in `TODOLIST.md`.

- **Tests for the two modules doing unaudited maths.** `comps.py` (20) — the
  football-field interquartile band, the positive-only peer median, the EV→equity bridge in
  `ev_implied`. `indicators.js` (24) — Wilder's RSI against his own worked dataset, MACD
  alignment and EMA seeding. Both were already correct; neither had a single test.

  Mutation testing then found two holes in the *new* tests: a period-2 RSI case cannot
  distinguish Wilder smoothing from a plain mean (at n=2 the recurrence collapses to
  `(avg + x)/2`), and nothing pinned the EMA's SMA seed until a slope-1 ramp was added,
  where the SMA seed puts MACD's first point at exactly **7.0** against **−4.97** for a
  raw-value seed.

- **`main.position_values`** and 11 tests, pinning which portfolio fields can be null and
  when — the contract whose violation caused the crash above.

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
