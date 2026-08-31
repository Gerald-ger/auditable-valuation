# Notes & limitations

What this platform does not do, does not know, or knows only approximately — each with the
measurement that established it. Split out of the README on 2026-08-28 because it had grown to
219 lines, a fifth of that file, and a reader scanning for "what is this" was meeting the
caveats before the screenshots. Nothing here was shortened in the move.

Every entry is a present-tense claim about the current code. If one of them stops being true,
it is a bug in this file.

[← back to the README](../README.md)

---

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
- **Stock compensation is subtracted, not added back.** Operating cash flow carries it
  back as a non-cash charge, and the share count is `sharesOutstanding`, which does not
  move — so keeping the add-back valued the same equity twice, once as cash the company
  did not spend and once as shares it did issue. The reference doc forbids exactly that
  combination, and the engine was doing it until 2026-08-26. The charge is now read off
  the statement for the base period and subtracted from the figure that gets discounted:
  **AAPL −12.7%, MSFT −18.7%, 0700.HK −12.5%** on the committed fixtures. XOM, 0002.HK and
  JPM report no such row and are untouched; `assumptions.sbc_basis` says which case
  applied, and `not_reported` is deliberately distinct from a reported zero.

  The **scoring** FCF metrics keep the gross figure, for the same reason they keep the
  levered one — they divide by market cap and net income, both already after compensation,
  so netting it again would double-correct them. The denominator stays basic rather than
  diluted: `sharesOutstanding` is the count that reproduces `marketCap / price`, so fair
  value per share and the traded price stay on one basis, where the statements' diluted
  figure is a *period average*. The cost of that choice is not argued away — fair value per
  share is still overstated by roughly the dilution rate, which is the smaller of the two
  effects by an order of magnitude.
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
- The DCF risk-free rate matches the currency the cash flows are reported in. USD reads the
  live US 10Y treasury yield, refreshed once per day, with a 4.3% fallback when OpenBB or the
  Fed feed is unreachable; CNY reads China's own curve (`cgb_10y_less_spread`, since
  2026-08-19) and HKD reads Hong Kong's (`hkgb_10y_less_spread`, since 2026-08-26), each net
  of that country's sovereign default spread so country risk is not counted twice against a
  country-inclusive ERP. Only when a curve is unreachable *and* nothing recent enough is
  stored does an issuer fall back to the US 10Y, labelled `usd_proxy`.
  **The HKD peg argument this section used to make is superseded rather than weakened**: a peg
  fixes an exchange rate, not a term structure, and measured 2026-08-25 the two ten-years
  differ by 120bp — 164bp of WACC on a low-beta name, moving `0002.HK` from 97.27 to 234.83.
  See `docs/data-sources-review.md` for the full source table.
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
- **Terminal growth shows its derivation** rather than appearing as a bare 2.5%. Two ceilings
  are displayed whether or not they bind, but **only one is applied**: long-run nominal GDP
  (nothing outgrows its economy forever) bounds the answer, and the risk-free rate —
  Damodaran's cap, the ten-year as a market read of long-run nominal growth — is **reported
  beside it rather than enforced**, since 2026-08-31.

  The reason is that the second ceiling stops reading long-run growth when the curve is set
  by policy. Until that date a CNY reporter inherited China's sovereign yield as its
  perpetual growth rate: 0700.HK was granted **1.10%** against its own 9.39% year-one
  consensus, worth **539.04 against 652.41** on fair value and 67 → 72 on the valuation
  pillar. Reference doc §1.1.3 asks only `g ≤ long-run nominal GDP`, so the risk-free half
  was this platform's own addition.

  **Deleting it would have cost something real, which is why it is printed instead.**
  Measured 2026-08-31: at a 2020-style 0.60% ten-year the old ceiling held AAPL at 177.17
  where the anchor gives 266.87, and JPM at 606.95 against 909.11. No evidence decides which
  reading is right, so both are on screen and the reader picks — the same trade this engine
  makes for a weak regression, publishing R² rather than applying a "fit too weak" cut.

  Neither ceiling touches a rate the caller names: the reconciliation back-solves past both
  deliberately, and capping it would report "closing this gap needs 7.0% perpetual growth"
  as unreachable.
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

  **The interval decides the floor's upper half only.** Freeing a precise regression from 0.30
  left that branch bounded above and nowhere below, and the comment saying `WACC ≤ terminal
  growth` covered the other side was wrong about what it covers: measured 2026-08-31, a beta of
  **−0.40 values AAPL at 21,288 against a price near 311**, and the refusal only fires from
  −0.41. The branch is now held at **0.0** — below zero `rf + beta × ERP` prices a company's
  equity beneath its own government's paper, which **CAPM genuinely permits** for an asset that
  hedges the market. So this is a policy about what to publish rather than a correction: a
  261-week regression is not trusted far enough to print a discount rate under the sovereign
  when the figure one step above the refusal is 68× the price. A real negative-beta name — a
  gold miner, a tail hedge — is discounted conservatively at the risk-free rate as a result, and
  that is the cost. **`[0.00, 0.30)` is still open, and it is the half that matters**: at a beta
  of 0.05 AAPL is worth 420.87, a +35% call from a number that looks unremarkable on screen.
  Closing that needs the precision cutoff the paragraph above declines to invent.
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
- Terminal value is 55–77% of enterprise value on the sample fixtures — measured
  2026-08-26, and the figure is unmoved by the stock-compensation change above, since it is
  a ratio the whole valuation scales with. Above 75% the UI flags it, which **`0002.HK` at
  77.3% does**, so this is a live check rather than a theoretical one: at that point the
  perpetuity assumption, not the explicit forecast, is producing the answer. Cross-check
  with the implied exit multiple — a DCF that only works by exiting far below today's
  trading multiple is assuming compression, which is a stance to agree with rather than
  inherit. Always sanity-check with the sensitivity grid and the editable assumptions.
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
- **A DCF is not shown as an answer for company types it does not fit — and since
  2026-08-29 they are given the model that does fit instead.** Banks have no `CFO − CapEx`
  at all, and a REIT's capex is property acquisition rather than maintenance, so the DCF
  still returns a number (O: −56.9% on the production path, which regresses beta from
  market bars; −73.5% from the reported beta alone) that means nothing, and both the
  Scorecard's valuation pillar and the Financial Models tab say so. What is no longer true
  is the sentence this entry used to end on. Banks and insurers now route to an
  **excess return** model and REITs to a **two-stage per-share dividend discount**, each
  drawing its own football-field bar. *(The −63% here was measured before the beta
  regression changed which path production takes; corrected 2026-08-30.)*
- **A model that fits is not the same as a model that answers.** On `O` — the only REIT
  fixture — the dividend model **refuses**: its regressed beta of 0.4263 (R² 0.148) puts
  the cost of equity at 6.20% against a 7.30% pre-tax cost of debt, and no fair value is
  reported rather than one discounted at a rate below the lender ranking ahead of the
  shareholder. So a REIT's default screen still carries no intrinsic number, and
  `valuation_upside_pct` is deliberately withheld from the REIT scoring profile for the
  same reason: this repository has never observed the metric produce a value. The
  assumption controls sit above the refusal so a reader can supply their own rate, which
  is the only path to a REIT valuation here today.
- Free cash flow for both the DCF and the two FCF scoring metrics comes from the cash-flow
  statement. `info["freeCashflow"]` is only a fallback and raises the
  `fcf_from_info_unverified_period` flag when used, because yfinance reports it annually
  for some issuers and quarterly for others (MSFT 0.244×, GOOGL 0.309×).
- The AI never computes or changes a number. It only comments on figures already computed
  by the deterministic engine, at `temperature: 0` with a fixed seed so the same input
  gives the same commentary.
- The bull/bear debate and token streaming have **never been run against a live model** —
  Ollama is not installed here, so only the offline degradation path is verified. See
  [TODOLIST.md](../TODOLIST.md).
- Portfolio value, cost and P&L are converted to **HKD** before they are summed, so the
  totals, the per-row weights and the concentration figures are comparable across markets.
  Per-share price and cost stay in the holding's own currency, and the columns say which is
  which. When a rate cannot be fetched nothing is converted and the totals are withheld
  rather than added across units — the currency that could not be priced is named on screen.
- Everything runs locally; nothing is sent to any cloud service.
- **Decision support only — not certified financial advice.**
