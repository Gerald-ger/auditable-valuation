# Financial Models Reference — Analytical Knowledge Base for AI Investment-Advisory Agent

**Version:** 1.0 | **Date:** 2026-07-31 | **Author:** Morgan (Financial Analyst Agent)
**Purpose:** Canonical reference for a local AI agent that pulls live data from the OpenBB Platform (v4, Python API) and must decide WHICH financial model to apply, HOW to apply it, and how to interpret results across past, present, and future stock-value analysis.

> ### ⛔ This is a specification, not a description. Do not edit it to match the code.
>
> Where this document and the engine disagree, the disagreement is a **finding**. Four were
> found on 2026-08-26; one of them — stock compensation added back against a static share
> count, which the SBC row below forbids in as many words — was a real defect worth 12–19%
> of fair value, and it had been in the code since the first DCF. Editing the spec to match
> whatever the engine happens to do would have erased the only thing that caught it.
>
> **The two legitimate moves:** change the code, or leave the rule standing and add an
> `> **As implemented** (module.function, DATE)` note recording what the engine does and
> why it differs. Four such notes already sit below — follow them rather than inventing a
> third option.
>
> **Also: the first 16,000 characters of this file are pasted verbatim into the local AI's
> system prompt** (`backend/ai_client.py`, `REFERENCE_CHAR_BUDGET`) — 21.2% of it as of
> 2026-08-26, and the share falls every time the file grows. Anything inserted near the top
> pushes the tail out of the model's view entirely. A correction beside its own rule earns
> that space; a preamble does not.

---

## 0. How To Use This Document (Agent Protocol)

1. **Classify the company first** (Section 7.1). Model choice depends on company type, not user preference.
2. **Every model section follows the same schema:** `Inputs / Steps / Outputs / When to use / Limitations / OpenBB data mapping`. Parse these subsections mechanically.
3. **Never output a single-point estimate.** Always produce a fair-value RANGE from at least two independent methods (Section 5.2), plus bull/base/bear scenarios (Section 5.3).
4. **State assumptions before conclusions.** Every output must list: growth rate(s), discount rate, terminal assumptions, peer set, and data vintage (as-of dates).
5. **Run the data-quality checks** (Section 7.2, Step 2) before any model. Garbage in, garbage out.
6. **Notation conventions (plain-text math):**
   - `*` multiply, `/` divide, `^` power, `SUM(...)` summation, `E[...]` expected value
   - `FCFF` = free cash flow to firm, `FCFE` = free cash flow to equity
   - `Re` = cost of equity, `Rd` = cost of debt, `Rf` = risk-free rate, `Tc` = corporate tax rate
   - `EV` = enterprise value, `MC` = market capitalization (equity value)
   - `g` = growth rate, `t` = period index, `n` = final explicit forecast period
7. **All model outputs are estimates.** Final agent output is decision support, never certified financial advice (Section 7.4).

---

# 1. INTRINSIC VALUATION MODELS

Intrinsic models value a business from its own cash-generating capacity, independent of what the market currently pays for peers. They are the anchor of any valuation; relative methods (Section 2) are the cross-check.

---

## 1.1 Discounted Cash Flow (DCF) — Unlevered / FCFF Method

The default intrinsic model for any company with forecastable positive (or credibly path-to-positive) free cash flow.

### Core identity

```
Enterprise Value = SUM_{t=1..n} [ FCFF_t / (1 + WACC)^t ] + TV_n / (1 + WACC)^n
Equity Value     = EV - Net Debt - Minority Interest - Preferred Equity + Non-operating Assets
Fair Value/Share = Equity Value / Diluted Shares Outstanding
```

> **As implemented** (`financial_models.dcf_valuation`, recorded 2026-08-26): the
> denominator is yfinance's `sharesOutstanding`, a **basic** point-in-time count, not a
> diluted one. Deliberate, and a real divergence from the line above rather than an
> oversight. `sharesOutstanding` is the count that reproduces `marketCap / price`, so fair
> value per share and the traded price it is compared against stay on one basis; the
> statements' `Diluted Average Shares` is a *period average*, and dividing a point-in-time
> equity value by it would mix the two. The cost is stated plainly: dilution is not
> counted, so fair value per share is overstated by roughly the dilution rate — low single
> digits for the large caps in the fixture set, more for a stock-compensation-heavy issuer.
> The larger of the two effects, the compensation charge itself, **is** now counted; see the
> SBC note below.

### 1.1.1 Unlevered Free Cash Flow (FCFF) projection

```
FCFF = EBIT * (1 - Tc)            # NOPAT
     + D&A                        # non-cash add-back
     - CapEx
     - Increase in Net Working Capital (ΔNWC)
     +/- other non-cash items (stock-based comp: see limitation below)
```

Build the forecast from revenue down:

| Driver | Typical basis | Sanity band |
|---|---|---|
| Revenue growth | Historical CAGR (3–5y), analyst consensus, TAM/market-share logic | Fade toward GDP+inflation (2–4% nominal) by terminal year |
| EBIT margin | Historical average +/- operating-leverage trend, peer benchmark | Should not exceed best-in-class peer without explicit justification |
| Tax rate | Effective rate normalized toward statutory (US ~21% federal + state ≈ 24–26%) | Use marginal/statutory for terminal year |
| CapEx % revenue | Historical average; distinguish maintenance vs growth capex | Terminal CapEx ≈ D&A * (1 + g) so reinvestment supports terminal growth |
| ΔNWC | NWC as % of revenue held constant, times revenue change | Negative-working-capital businesses (subscriptions, retail) generate cash on growth |
| SBC treatment | Either (a) treat as cash expense (subtract, do NOT add back), or (b) add back but increase diluted share count with future dilution | Never add back with static share count — that double-counts value |

> **As implemented** (`statements.sbc_expense`, 2026-08-26): route (a). The charge is read
> off the cash-flow statement for the base period and subtracted from the figure that gets
> discounted. Route (b) was declined for the reason in the share-denominator note above —
> the diluted count is a period average and the equity value is not — and because dilution
> is the smaller of the two effects, so (b) would correct a fraction of what (a) corrects.
> **This rule was breached from the platform's first DCF until this date**, and the breach
> was the combination the right-hand column forbids exactly: `CFO − CapEx` carries the
> non-cash add-back, and `sharesOutstanding` never moves. Measured on the committed
> fixtures, correcting it moves fair value **AAPL −12.7%, MSFT −18.7%, 0700.HK −12.5%**;
> XOM, 0002.HK and JPM report no such row and are untouched. An issuer that reports none
> gets `sbc_basis: "not_reported"` rather than an estimated figure.

**Forecast horizon:** 5 years standard; 10 years for high-growth companies still converging to steady state. Explicit period must end when the company plausibly reaches sustainable margins and reinvestment rates.

> **As implemented** (`financial_models.STAGE1_YEARS` / `STAGE2_YEARS`, recorded 2026-08-26):
> **one** explicit year, then a nine-year linear fade to terminal growth — ten years in
> total, for every company rather than only the fast-growing ones. The explicit stage is one
> year because that is the horizon the analyst consensus feeding it actually forecasts;
> holding a one-year figure flat across five years compounds it into a claim nobody made.
> Measured on AMD, a consensus held flat for five years compounds free cash flow 15.1x
> against 7.2x under the fade. The fade is what replaced the old `[0%, 25%]` growth clamp:
> the ceiling existed to survive a five-year plateau, not to express a view about growth.

### 1.1.2 WACC derivation

```
WACC = (E/V) * Re + (D/V) * Rd * (1 - Tc)
  E = market value of equity (market cap)
  D = market value of debt (book value acceptable proxy for healthy issuers)
  V = E + D
```

> **As implemented** (`financial_models.dcf_valuation`, 2026-08-27): when `E` is not
> reported, the DCF is **refused** rather than computed. `_wacc` read a missing market cap
> as `0`, which is not a capital structure — it makes `E/V` zero and returns the after-tax
> cost of debt alone. Measured across the fixtures before the guard: AAPL discounted at
> 3.87% against its real 9.05% and returned 618.69 against 127.91; the error ran +362%
> (`0002.HK`) to +942% (`0700.HK`), with no exception and no flag, and the composite *rose*
> as `dcf_upside_pct` came off its floor. A caller that supplies `wacc_override` is not
> refused: the sensitivity grid and `solve_for_fair_value` both name their own rate and
> never consult the collapsed one.

**Cost of equity — CAPM:**

```
Re = Rf + Beta_levered * ERP  [+ size premium + country risk premium if applicable]
```

- `Rf`: 10-year government bond yield (match currency of cash flows).
- `Beta`: regress 2–5 years of weekly/monthly stock returns vs broad index; or use provider beta. For thinly traded or distorted betas, use bottom-up beta: unlever peer betas, average, re-lever to target capital structure:

  > **As implemented** (`financial_models.resolve_beta`, 2026-08-06): a simplification of
  > the bottom-up method below — the provider beta is used only within `[0.3, 2.5]`,
  > otherwise the **levered** peer median is substituted (min. 2 credible peers), otherwise
  > 1.0. Peer betas are not unlevered and re-levered, so the substitute carries the peers'
  > capital structures rather than the target's. Adequate as a guard against distorted
  > readings (yfinance reported 0.173 for XOM), not a substitute for the full procedure.
  > Note it cannot help where a whole sector's provider betas are distorted — measured
  > 2026-08-06, energy majors return CVX 0.488, COP 0.123, SHEL −0.218, BP −0.212.
  - `Beta_unlevered = Beta_levered / (1 + (1 - Tc) * D/E)`
  - `Beta_relevered = Beta_unlevered * (1 + (1 - Tc) * D/E_target)`
- `ERP` (equity risk premium): 4.5–5.5% mature markets (use a consistent published source, e.g., Damodaran monthly estimate).
- Size premium: +1–3% for small/micro caps (Duff & Phelps/Kroll style), applied judgmentally.

**Cost of debt:**

```
Rd = Interest Expense / Average Total Debt      # book approximation
Rd = Rf + credit spread for issuer rating       # market approach (preferred)
After-tax Rd = Rd * (1 - Tc)
```

**Sanity checks:** WACC typically 6–9% for mega-cap defensives, 8–11% for typical corporates, 10–14%+ for small/high-risk/emerging. If computed WACC < Rf + 1%, inputs are wrong.

### 1.1.3 Terminal value

**Method A — Gordon Growth (perpetuity):**

```
TV_n = FCFF_{n+1} / (WACC - g_terminal) = FCFF_n * (1 + g) / (WACC - g)
```

- `g_terminal` must be ≤ long-run nominal GDP growth (2–3% mature markets). `g >= WACC` is invalid.
- Check: implied exit multiple `TV_n / EBITDA_n` should be plausible vs today's trading multiples.

**Method B — Exit Multiple:**

```
TV_n = Exit Multiple * EBITDA_n   (or EBIT_n / Revenue_n)
```

- Use the peer-median forward multiple, typically haircut 10–20% for multiple compression over the forecast horizon.
- Check: implied `g` from the exit multiple should be < GDP growth: `g_implied = WACC - FCFF_{n+1}/TV_n`.

**Rule:** compute BOTH, present the range. If they disagree by >30%, flag which assumption drives the gap.

**Warning:** if terminal value > **75%** of total EV, the model is essentially a multiple bet dressed as a DCF — lengthen the explicit period or flag low conviction. *(This read 80% until 2026-08-26. The engine has flagged at 75% — the conventional line — since the check was written, so the figure here was the one that was wrong, and the correction moves the threshold in the stricter direction. `financial_models` raises `terminal_value_high` at that boundary; the fixtures run 55.2–77.3%, and `0002_HK` at 77.3% is the one that trips it.)*

### 1.1.4 Sensitivity tables (mandatory output)

Produce a 2-way grid: WACC (rows, +/- 1.0% in 0.5% steps) × terminal growth or exit multiple (columns). Also a 1-way tornado on: revenue growth, EBIT margin, CapEx intensity, tax rate. Report the fair-value range across the plausible grid, not the center cell alone.

### Inputs
- 3–10 years historical income statement, balance sheet, cash flow statement
- Diluted share count, current price, total debt, cash & equivalents, minority interest, preferred
- Risk-free rate, beta, ERP, credit spread / interest expense, tax rate
- Analyst consensus estimates (revenue/EPS) to anchor years 1–2

### Steps
1. Validate and normalize historicals (remove one-offs; Section 4.3).
2. Project revenue → margins → NOPAT → FCFF for 5–10 years.
3. Derive WACC (CAPM + after-tax cost of debt).
4. Compute terminal value both ways; cross-check implied multiple/growth.
5. Discount FCFF and TV to present; bridge EV → equity value → per share.
6. Run sensitivity grid and scenarios; output fair-value range.

### Outputs
- Fair value per share (base) + range from sensitivity grid
- Implied upside/downside vs current price
- % of EV in terminal value (conviction flag)
- Key-driver tornado ranking

### When to use
- Companies with positive or clearly path-to-positive FCF and forecastable economics: mature tech, industrials, consumer, healthcare, energy (with commodity-price scenarios).
- Primary anchor model for most non-financials.

### Limitations
- Highly sensitive to WACC and terminal assumptions (small input changes → large value swings; always show sensitivity).
- Unsuitable for banks/insurers (cannot separate operating vs financing cash flows) — use DDM/Residual Income (1.2, 1.3).
- Weak for pre-revenue or deeply unprofitable firms (forecast is speculation) — use scenario-weighted DCF or revenue multiples with explicit caveats.
- Cyclical companies: normalize mid-cycle margins, never extrapolate peak/trough.

### OpenBB data mapping

| Input | OpenBB v4 endpoint | Provider notes |
|---|---|---|
| Income statement (hist.) | `obb.equity.fundamental.income(symbol, period="annual", limit=10)` | `yfinance` free (4–5y); `fmp` free tier ~5y annual; `polygon`/`intrinio` deeper |
| Balance sheet | `obb.equity.fundamental.balance(...)` | same |
| Cash flow statement | `obb.equity.fundamental.cash(...)` | same — CapEx, D&A, SBC, ΔNWC components |
| Shares outstanding (diluted) | `obb.equity.fundamental.income` (diluted shares) or `obb.equity.ownership.share_statistics(symbol)` | `yfinance` free |
| Current price / market cap | `obb.equity.price.quote(symbol)` | `yfinance` free |
| Beta | `obb.equity.profile(symbol)` (provider beta) or compute from `obb.equity.price.historical` vs `obb.index.price.historical("^GSPC")` | compute preferred for control |
| Risk-free rate | `obb.fixedincome.government.treasury_rates(provider="federal_reserve")` or `obb.economy.fred_series(symbol_id="DGS10")` | free (FRED key free) |
| Analyst estimates (yr 1–2 anchor) | `obb.equity.estimates.consensus(symbol)` | `yfinance` free (limited); `fmp` better |
| Tax rate | derived: income tax expense / pretax income from `fundamental.income` | — |
| Segment detail (optional) | `obb.equity.fundamental.revenue_per_segment(symbol)` / `revenue_per_geography` | `fmp` (may require paid tier) |

---

## 1.2 Dividend Discount Model (DDM)

### Core identity

```
P0 = SUM_{t=1..∞} [ DPS_t / (1 + Re)^t ]
```

### Single-stage (Gordon Growth)

```
P0 = DPS_1 / (Re - g) = DPS_0 * (1 + g) / (Re - g)
```

- `g` sustainable growth: `g = ROE * (1 - payout ratio)` (retention growth identity).
- Valid only when `g < Re` and dividends are stable/policy-driven.

### Multi-stage (two- or three-stage)

```
P0 = SUM_{t=1..n} [ DPS_t / (1 + Re)^t ] + [ DPS_{n+1} / (Re - g_stable) ] / (1 + Re)^n
```

Stage 1: explicit dividend forecast (payout policy × EPS forecast) for 5–10 years.
Stage 2 (optional): linear fade of growth from high to stable (H-model: `P0 ≈ [DPS_0 * (1+g_L) + DPS_0 * H * (g_S - g_L)] / (Re - g_L)` where `H` = half-life of the fade in years, `g_S` short-run, `g_L` long-run growth).
Terminal: Gordon Growth on stable dividend.

### Inputs
- Dividend history (5–10y), current DPS, payout ratio, EPS forecasts
- Cost of equity (CAPM, Section 1.1.2), sustainable ROE
- Buybacks: for repurchase-heavy firms use total shareholder payout (dividends + net buybacks) per share instead of DPS alone

### Steps
1. Confirm dividend policy stability (payout ratio trend, no cuts in 10y, management commitment language).
2. Forecast EPS → apply payout ratio → DPS path.
3. Estimate `Re` via CAPM; set `g_stable` ≤ nominal GDP growth and ≤ `ROE * retention`.
4. Discount; sensitivity on `Re` and `g` (the spread `Re - g` dominates — show the grid).

### Outputs
- Fair value per share, implied dividend yield vs current, sensitivity grid on (Re, g).

### When to use
- **Banks and insurers** (capital-regulated; dividends are the cleanest distributable-cash proxy; FCFF is meaningless).
- Mature, high-payout companies: utilities, telecoms, consumer staples, pipeline/midstream (with distribution coverage checks).
- REITs: use AFFO-based variant — substitute AFFO/share for DPS capacity; cross-check with dividend coverage (AFFO payout < 90%).

> **As implemented** (`financial_models.dividend_discount_valuation`, 2026-08-29) — this model
> shipped for REITs and diverges from the section above in three ways, each deliberate.
>
> **It discounts declared dividends per share, not AFFO per share.** A REIT distributes by
> statute, so the dividend *is* the distributable cash rather than a proxy for it, and the
> AFFO variant needs a maintenance-versus-growth capex split that no free filing discloses —
> inventing that split would be an assumption made because nobody wired up a source. AFFO
> survives as a **coverage check only**: `diagnostics.payout_of_ffo_proxy` reports the payout
> against `(net income + D&A)`, 81.5% on `O` against the 90% ceiling this section names.
>
> **Growth is the compound rate of the company's own dividends per share, not
> `ROE x (1 - payout)`.** The retention identity assumes book value compounds internally, which
> is how the excess return model in §1.3 grows and why it uses that formula there. A REIT
> retains almost nothing and funds acquisitions by issuing equity, so retention growth would
> read near zero for a company whose dividend has in fact compounded at 4.4%.
>
> **Per share throughout, never aggregate.** On `O` the share count grew 41.4% over four
> years: the aggregate dividend compounds at 17.22% against 4.43% per share. Valuing the
> aggregate would credit today's holder with dividends bought by somebody else's money.
>
> **And it refuses more than this section anticipates.** Beyond `g < Re`, it declines when the
> cost of equity falls below the company's own **pre-tax cost of debt** — a lender ranks ahead
> of a shareholder, so that discount rate is not one the company could raise equity at. This
> fires on `O` in production (regressed beta 0.4263, R² 0.148 → 6.20% against 7.30%). Rows of
> the sensitivity grid that fall under the same floor are marked `below_cost_of_debt`, struck
> through in the UI and skipped by the football-field band, added 2026-08-30 after the grid was
> found pricing rates the headline refuses to price.

### Limitations
- Useless for non-payers or token payers (value sits in retained growth, not distributions).
- `Re - g` denominator hypersensitivity: a 0.5% change can move value 15–30%.
- Ignores balance-sheet optionality and buyback-heavy return policies unless total-payout variant is used.
- Dividend cuts (credit stress) break the model discontinuously — check payout ratio > 80% and rising leverage as warning signs.

### OpenBB data mapping

| Input | OpenBB v4 endpoint | Provider notes |
|---|---|---|
| Dividend history | `obb.equity.fundamental.dividends(symbol)` | `yfinance`/`fmp` free |
| Trailing yield | `obb.equity.fundamental.trailing_dividend_yield(symbol)` | `tiingo` |
| EPS history / payout | `obb.equity.fundamental.income` + `historical_eps(symbol)` | `fmp`/`alpha_vantage` |
| EPS forecasts | `obb.equity.estimates.consensus(symbol)` | `fmp` recommended |
| ROE / payout ratios | `obb.equity.fundamental.ratios(symbol)` | `fmp` |
| Cost of equity inputs | as DCF (treasury rates, beta, index history) | — |
| Dividend calendar | `obb.equity.calendar.dividend(...)` | `fmp` / `nasdaq` |

---

## 1.3 Residual Income (RI) / Economic Value Added (EVA)

Value = book value today + present value of future value creation ABOVE the cost of capital.

### Core identities

```
Residual Income_t = Net Income_t - Re * Book Equity_{t-1}
                  = (ROE_t - Re) * Book Equity_{t-1}

Equity Value = B0 + SUM_{t=1..n} [ RI_t / (1 + Re)^t ] + Terminal RI term
```

Terminal RI: assume excess returns fade to zero (competition) — `TV = RI_n * ω / (1 + Re - ω)` with persistence factor `ω ∈ [0,1]` (0 = immediate fade, 1 = perpetual); or Gordon on RI with `g < Re`.

> **As implemented** (`financial_models.excess_returns_valuation`, 2026-08-29) — the engine
> takes the second branch and **holds ROE flat rather than fading it**. There is no `ω` in the
> codebase. This is the single largest assumption in the model and it is the more aggressive
> one: it assumes the moat survives forever.
>
> The fade was considered and rejected because `ω` would be a constant nothing in this
> repository can calibrate — the same reason the beta regression publishes its R² instead of
> applying a "fit too weak" threshold. What the engine does instead is **print the assumption**:
> `diagnostics.excess_spread` is the permanent gap being claimed (7.14 points on JPM) and
> `diagnostics.implied_terminal_payout` is the payout the terminal phase requires for that ROE
> and that growth to be mutually consistent (84.2% against a current 30.5%). A reader can
> disagree with a number on the screen; they cannot disagree with an `ω` buried in arithmetic.
>
> Terminal growth is capped at `min(TERMINAL_GROWTH, risk-free rate)` exactly as the DCF caps
> it, and for a measured reason: `ROE x (1 - payout)` for a profitable bank routinely exceeds
> its own cost of equity — 11.09% against 8.66% on JPM — so an uncapped Gordon terminal value
> is not merely large, it is **negative**.
>
> ROE is the **mean across reported periods**, not the newest year: JPM runs 13.55 / 15.89 /
> 17.51 / 16.26%, and feeding the newest of those into a perpetuity compounds a 4-point error
> forever. The newest year's own fair value is reported beside it as
> `diagnostics.fair_value_latest_roe`.

**EVA (firm-level twin):**

```
EVA_t = NOPAT_t - WACC * Invested Capital_{t-1} = (ROIC_t - WACC) * IC_{t-1}
EV = Invested Capital_0 + PV(all future EVA)     # Market Value Added form
```

### Inputs
- Book value of equity (or invested capital), ROE/ROIC history and forecast, Re/WACC, clean-surplus check (ΔBook Equity ≈ NI - Dividends + share issuance; large OCI distortions break the model)

### Steps
1. Verify clean-surplus relation roughly holds (flag heavy OCI/FX entities).
2. Forecast ROE and book value per share 5–10 years (banks: tie to regulatory capital ratios — CET1 targets constrain payout and book growth).
3. Compute RI each year; choose fade/persistence for terminal.
4. Discount at Re; add to current book value.

### Outputs
- Fair value per share; implied justified P/B: `P/B = 1 + (ROE - Re)/(Re - g)` — the single most useful cross-check for banks.
- Decomposition: % of value from book vs future excess returns (lower terminal dependence than DCF — a feature).

### When to use
- **Banks/financials** (best-in-class alongside DDM; ROE vs cost of equity is exactly the regulator's and market's lens).
- Companies with negative near-term FCF but reliable accounting earnings.
- Cross-check on DCF: RI front-loads value into current book, reducing terminal-value dominance.

### Limitations
- Sensitive to accounting quality — aggressive accruals inflate ROE and RI (run QoE checks, Section 4.3).
- Intangible-heavy firms: book value understated (R&D/brand expensed), making ROE overstated; interpret spreads, not levels.
- Clean-surplus violations (pensions, FX translation, AFS securities) distort the book-value roll-forward.

### OpenBB data mapping

| Input | OpenBB v4 endpoint | Provider notes |
|---|---|---|
| Book equity / IC | `obb.equity.fundamental.balance(symbol, limit=10)` | free tiers OK |
| Net income / NOPAT | `obb.equity.fundamental.income(...)` | — |
| ROE/ROIC history | `obb.equity.fundamental.ratios(symbol, limit=10)` | `fmp` |
| Forward ROE anchor | `obb.equity.estimates.consensus` (EPS) / book per share | — |
| P/B for justified-multiple check | `obb.equity.fundamental.metrics(symbol)` | `fmp`/`yfinance` |

---

# 2. RELATIVE VALUATION

Relative methods price a company against what the market pays for comparable assets. Fast, market-grounded, and the necessary reality check on intrinsic models — but they import the market's current mood (over- and under-valuation of the whole peer group transfers into your answer).

---

## 2.1 Comparable Company Analysis (Trading Comps)

### 2.1.1 Peer selection criteria (in priority order)

1. **Business model / industry** (same GICS sub-industry or direct product competitors)
2. **Size** (revenue/EV within ~0.3x–3x of target)
3. **Growth profile** (revenue growth within a few points — growth is the #1 multiple driver)
4. **Margin/return profile** (EBITDA margin, ROIC)
5. **Geography / regulatory regime**
6. **Capital structure** (leverage outliers distort equity multiples — prefer EV multiples)

Target 5–10 peers. Fewer than 4 → widen criteria and flag low confidence. Exclude peers with distorted multiples (negative denominator, pending M&A, distress).

### 2.1.2 Key multiples — formulas and when each is appropriate

```
EV = Market Cap + Total Debt + Preferred + Minority Interest - Cash & Equivalents
```

| Multiple | Formula | Best for | Avoid when |
|---|---|---|---|
| EV/EBITDA | EV / EBITDA | Capital-intensive: industrials, telecom, energy, media; cross-capital-structure comparison | Banks (EBITDA meaningless); companies where D&A is a real economic cost proxy (heavy maintenance capex) — prefer EV/EBIT |
| EV/EBIT | EV / EBIT | Differing capital intensity within peer set (charges depreciation) | Very asset-light where D&A trivial (adds nothing vs EBITDA) |
| EV/Sales | EV / Revenue | Pre-profit growth (SaaS, biotech-commercial, early consumer); margin-convergence stories — pair with gross margin | Mature profitable firms (ignores profitability entirely) |
| P/E | Price / diluted EPS | Mature profitable firms with similar leverage; banks and insurers | Negative/near-zero EPS; leverage differs widely; heavy one-offs in earnings |
| PEG | (P/E) / EPS growth % | Ranking growth stocks with different growth rates (rule of thumb: <1 cheap, >2 rich) | Low growth (<5%, ratio explodes); crude — ignores risk & duration of growth |
| P/B | Price / book equity per share | Banks, insurers, asset-heavy financials; pair with ROE (justified P/B, §1.3) | Intangible-heavy businesses (book meaningless) |
| P/TBV | Price / tangible book per share | Bank M&A and distress screens | Same as P/B |
| FCF yield | FCF / Market Cap (or FCFF/EV) | Mature cash cows, quality screens; inverse of P/FCF; >6–8% is notable | Lumpy capex years; growth firms deliberately reinvesting |
| P/FFO, P/AFFO | Price / (A)FFO per share | REITs (replaces P/E; add back real-estate depreciation) | Non-REITs |
| EV/EBITDAR | EV+capitalized rents / EBITDAR | Airlines, retail, restaurants with big operating leases | Post-IFRS16/ASC842 data already capitalizes leases — avoid double counting |

**Forward vs trailing:** prefer NTM (next-twelve-months, from consensus) multiples — markets price the future. Report both; a big gap between trailing and forward multiple = expected inflection.

### Inputs
- Peer list; for each peer and target: market cap, net debt, minorities/preferred, LTM & NTM revenue/EBITDA/EBIT/EPS, growth and margin stats

### Steps
1. Select and screen peers (criteria above); document inclusions/exclusions.
2. Build EV bridge per peer; compute LTM and NTM multiples.
3. Compute peer statistics: min, 25th percentile, median, 75th, max. **Use median, never mean** (outlier robust).
4. Position the target within the range based on relative growth/margin/risk (a faster-growing, higher-margin target deserves above-median).
5. Apply chosen multiple range to target metric → implied EV → bridge to equity value → per share.
6. Regress multiple vs growth across peers (e.g., EV/EBITDA vs revenue growth) for a defensible positioning if peer dispersion is wide.

### Outputs
- Implied value range per multiple (25th–75th percentile band), per share
- Target's premium/discount vs peer median with justification
- Football-field input rows (Section 5.2)

### When to use
- Always, as a cross-check to DCF. Primary method when cash flows are unforecastable but peers exist (early-stage, cyclical trough/peak).

### Limitations
- Circular in bubbles/crashes: peer group mispricing transfers directly.
- Accounting comparability: adjust for lease treatment, SBC in EBITDA, calendarization (different fiscal year ends), one-time items.
- Multiples compress growth, risk, and returns into one number — two firms with the same multiple can be differently valued.
- Thin peer sets (unique business models) force weak comps — flag confidence.

### OpenBB data mapping

| Input | OpenBB v4 endpoint | Provider notes |
|---|---|---|
| Peer list | `obb.equity.compare.peers(symbol)` | `fmp`; validate manually — provider peers are often loose |
| Screening for peers | `obb.equity.screener(...)` | `fmp`/`yfinance`; filter sector, market cap |
| Peer fundamentals | loop `obb.equity.fundamental.income/balance` per peer | rate limits on free tiers — cache |
| Ready-made multiples | `obb.equity.fundamental.metrics(symbol)` (P/E, EV/EBITDA etc.) or `obb.equity.fundamental.multiples(symbol)` | `fmp`, `yfinance` |
| Forward multiples | `obb.equity.estimates.consensus` (NTM EPS/revenue) + `obb.equity.price.quote` | forward EBITDA often needs `fmp` paid or manual build |
| Ratios (margins, growth) | `obb.equity.fundamental.ratios`, `income_growth` | `fmp` |
| Sector aggregates | `obb.equity.compare.groups(...)` | `finviz` (free) |

---

## 2.2 Precedent Transaction Analysis (Deal Comps)

Values the company off multiples paid in actual M&A transactions for similar companies. Answers "what would an acquirer pay," not "where should it trade."

### Key concepts

- **Control premium:** acquirers pay 20–40% above unaffected trading price for control (median ~25–30% historically). Precedent multiples therefore sit ABOVE trading comps. Never mix the two ranges without labeling.
- **Synergies:** strategic buyers bake expected cost/revenue synergies into price; the multiple paid reflects `standalone value + control premium + shared synergies`. A standalone fair-value estimate should NOT assume full synergy value.
- **Deal multiple formula:** `EV_deal / LTM EBITDA_target` (at announcement), plus premium analysis: `Offer price / unaffected price (1-day, 30-day prior)`.

### Inputs
- 5–15 transactions, last 3–7 years, same industry, comparable size; deal EV, target LTM/NTM financials, payment mix (cash/stock), buyer type (strategic vs sponsor)

### Steps
1. Screen deals (industry, size, date, geography); discard pre-regime-change deals (rate environment shifts multiples).
2. Compute EV/EBITDA, EV/Sales, P/E paid; compute premia to unaffected prices.
3. Median/quartile stats; adjust for cycle (deals struck at market peaks overstate).
4. Apply range to target metrics → implied takeout value range.

### Outputs
- Implied acquisition value range (per share), premium context for interpreting live M&A news, floor/ceiling framing vs trading comps.

### When to use
- M&A situations: rumored/announced deals, activist involvement, evaluating whether an offer price is adequate.
- As the "ceiling" band on the football field (control value > standalone trading value).

### Limitations
- Stale fast: rate and cycle regime changes make 5-year-old multiples misleading.
- Disclosed deal terms often incomplete (private targets, earnouts, assumed debt ambiguity).
- Each deal is idiosyncratic (unique synergies, competitive auctions, distressed sales) — dispersion is wide; use quartiles not point estimates.
- Sparse data in niche sectors.

### OpenBB data mapping

| Input | OpenBB v4 endpoint | Provider notes |
|---|---|---|
| M&A / deal news | `obb.news.company(symbol)` filtered for M&A terms | `benzinga` (paid) richest; `fmp`/`tiingo` basic |
| Historical prices (unaffected price, premium calc) | `obb.equity.price.historical(symbol, start_date, end_date)` | free |
| Target fundamentals at announcement | `obb.equity.fundamental.income/balance` with historical `limit` | pick period pre-announcement |
| Deal databases | **Not natively in OpenBB free tiers** — comprehensive precedent data (CapIQ/MergerMarket class) is paid; agent should use disclosed deal terms from filings via `obb.equity.fundamental.filings(symbol)` (`sec` provider, free) and news | flag lower confidence when deal set is thin |

# 3. TRANSACTION / STRUCTURAL MODELS (Context Layer)

The agent will rarely build these end-to-end, but must understand them to interpret sell-side outputs, M&A news, and leverage-driven price floors.

---

## 3.1 Three-Statement Model (The Foundation)

Integrated income statement (IS), balance sheet (BS), and cash flow statement (CF) with dynamic links. Every serious model (DCF, LBO, merger) sits on top of one.

### Linking logic (the circulatory system)

1. **IS → BS:** Net income flows into retained earnings (`RE_t = RE_{t-1} + NI_t - Dividends_t`).
2. **IS → CF:** Net income is the top of the indirect cash flow statement; D&A added back.
3. **BS → CF:** Changes in working-capital accounts (AR, inventory, AP, deferred revenue) drive operating cash; CapEx drives investing cash; debt/equity issuance drives financing cash.
4. **CF → BS:** Ending cash from CF statement becomes the cash line on next period's BS.
5. **Debt schedule (circular):** average debt balance → interest expense → net income → cash available for debt paydown → ending debt. Resolved by iteration or beginning-balance convention.
6. **Balance check:** Assets = Liabilities + Equity every period. A model that doesn't tie is wrong, full stop.

### Inputs / Steps / Outputs
- **Inputs:** 3–5y historical statements, revenue/margin/working-capital/CapEx drivers, debt terms.
- **Steps:** historicals → drivers → project IS → project BS via schedules (PP&E, working capital, debt, equity) → derive CF → check balance.
- **Outputs:** the FCFF stream for DCF, credit metrics (leverage, coverage), funding-gap detection (when does cash go negative).

### When to use
- Foundation for any multi-year projection; mandatory when balance-sheet dynamics matter (leverage, working-capital swings, funding needs).

### Limitations
- Only as good as its drivers; a beautifully linked model with lazy assumptions is precise garbage.

### OpenBB data mapping
- All three statements: `obb.equity.fundamental.income / balance / cash` (annual + `period="quarter"` for recency). Growth versions: `income_growth`, `balance_growth`, `cash_growth` (`fmp`). Reported-as-filed granularity: `provider="polygon"` or `intrinio`; SEC raw via `obb.equity.fundamental.filings(symbol, provider="sec")`.

---

## 3.2 LBO Model — The "Floor Valuation" Signal

A leveraged buyout model asks: what price can a financial sponsor pay, funding the deal with heavy debt, and still earn a target return (~20–25% IRR / 2.0–2.5x MOIC over ~5 years)?

### Mechanics in brief

```
Sources = New Debt (4–6x EBITDA typical) + Sponsor Equity
Uses    = Purchase EV + Fees
Exit Equity = Exit EV (exit multiple * exit EBITDA) - Remaining Debt
IRR solves: Sponsor Equity * (1 + IRR)^years = Exit Equity
```

Value creation levers: (1) debt paydown from FCF, (2) EBITDA growth, (3) multiple expansion (do not underwrite it).

### Why the agent cares
- **Floor valuation:** the maximum price an LBO supports (given current debt markets and target returns) is a practical floor for a company with stable FCF — if the stock trades below its LBO value, take-private risk/opportunity is real. Screen: EV/EBITDA below ~7–8x with stable FCF, low existing leverage, and depressed price = potential LBO candidate; interpret related news accordingly.
- **Credit read-through:** covenant metrics (Net Debt/EBITDA > 6x, EBITDA/Interest < 2x) signal distress risk for already-levered equities.

### Inputs / Steps / Outputs
- **Inputs:** EBITDA (LTM + forecast), maintenance CapEx, current debt-market terms (spread over SOFR, leverage tolerances), exit multiple assumption.
- **Steps:** assume entry price → build sources & uses → project FCF and debt paydown → exit at year 5 → solve IRR; invert to solve max entry price at target IRR.
- **Outputs:** implied "LBO floor" per share; feasibility flag (is FCF stable enough to lever?).

### When to use / Limitations
- **Use:** stable-FCF, low-growth companies; buyout rumor interpretation; floor band on football field.
- **Avoid:** high-growth, cyclical, capex-heavy, or already-levered names (LBO math collapses). Floor logic fails when credit markets shut (2022-style) — leverage available drives the floor as much as the asset does.

### OpenBB data mapping
- EBITDA/FCF: `obb.equity.fundamental.income`, `cash`, `metrics`. Debt detail: `obb.equity.fundamental.balance`. Rate environment: `obb.fixedincome.government.treasury_rates`, `obb.economy.fred_series("SOFR")`, high-yield spreads `obb.economy.fred_series("BAMLH0A0HYM2")` (free, FRED). Buyout news: `obb.news.company`.

---

## 3.3 Merger Model (Accretion / Dilution)

Tests whether an acquisition increases (accretive) or decreases (dilutive) the acquirer's EPS.

### Core logic

```
Pro-forma EPS = (Acquirer NI + Target NI + After-tax Synergies
                 - After-tax Incremental Interest on cash/debt used
                 - New Intangible Amortization) / (Acquirer shares + New shares issued)
Accretion/(Dilution) % = Pro-forma EPS / Standalone Acquirer EPS - 1
```

Quick heuristics:
- **All-cash deal:** accretive if target's after-tax earnings yield (E/P) > after-tax cost of the cash/debt used.
- **All-stock deal:** accretive if acquirer's P/E > target's P/E paid (buying cheaper earnings with expensive paper).

### Why the agent cares (M&A news interpretation)
- On deal announcement: estimate accretion/dilution to predict acquirer stock reaction; assess offered premium vs precedent norms (Section 2.2) for the target.
- Stock-deal arbitrage spread: `Target price vs (exchange ratio * acquirer price)` — the spread measures market-implied deal-break risk.
- Beware "accretive" ≠ "value-creating": overpaying with overvalued stock can be EPS-accretive and value-destructive. Check ROIC on deal vs acquirer WACC: `Deal ROIC = After-tax NOPAT acquired / Purchase EV`.

### Inputs / Steps / Outputs / When to use / Limitations
- **Inputs:** both companies' EPS/NI forecasts, deal terms (price, cash/stock mix, financing rate), synergy guidance.
- **Steps:** build pro-forma NI → adjust shares → compare EPS; sensitivity on synergies and price.
- **Outputs:** accretion/dilution %, breakeven synergies, implied reaction direction.
- **When to use:** any live or rumored M&A involving covered names.
- **Limitations:** EPS accretion is an optics metric; synergy estimates from management are systematically optimistic (haircut 50% for revenue synergies); integration costs usually understated.

### OpenBB data mapping
- Both firms' fundamentals/estimates: `obb.equity.fundamental.income`, `obb.equity.estimates.consensus`. Deal terms: `obb.news.company` + merger filings (8-K, DEFM14A) via `obb.equity.fundamental.filings(provider="sec")`. Prices for spread: `obb.equity.price.quote/historical`.

---

## 3.4 Sum-of-the-Parts (SOTP)

Values each business segment separately with the method appropriate to it, then sums.

```
EV_total = SUM_segments [ Segment metric * segment-appropriate multiple (or segment DCF) ]
Equity Value = EV_total - Net Debt - Corporate costs capitalized - Conglomerate discount (0–20%)
```

### Steps
1. Pull segment revenue/EBIT from filings (segment footnote / MD&A).
2. Assign each segment a pure-play peer set and multiple (a conglomerate's media arm at media multiples, its parks arm at leisure multiples).
3. Capitalize unallocated corporate overhead as a negative value (corporate cost * appropriate multiple).
4. Sum, bridge to equity, compare with the market's single-multiple valuation.

### Outputs / When to use / Limitations
- **Outputs:** per-share SOTP value; hidden-value flag when SOTP > market price by >25% (activist/spin-off catalyst potential).
- **When to use:** conglomerates, holding companies, multi-segment firms with divergent segment economics (e.g., a retailer with a cloud business), stake-holding companies (value listed stakes at market).
- **Limitations:** segment disclosure is coarse and allocation of shared costs is arbitrary; conglomerate discounts persist for years without a catalyst — SOTP upside is not a timing signal; intersegment eliminations can distort segment margins.

### OpenBB data mapping
- Segment data: `obb.equity.fundamental.revenue_per_segment(symbol)` / `revenue_per_geography` (`fmp`, may need paid tier); authoritative source: 10-K segment footnote via `obb.equity.fundamental.filings(provider="sec")` (free, requires text parsing). Pure-play peer multiples: Section 2.1 mapping.

---

# 4. FINANCIAL STATEMENT & BUSINESS ANALYSIS

Runs BEFORE valuation. Establishes data quality, financial health, and business trajectory — and calibrates every model assumption.

---

## 4.1 Ratio Analysis Framework

Compute 5+ years of history plus latest quarter; judge TREND and PEER-RELATIVE level, not absolute level alone. Healthy ranges below are heuristics for a typical non-financial corporate — always context-adjust (noted per row).

### Liquidity

| Ratio | Formula | Heuristic | Context notes |
|---|---|---|---|
| Current ratio | Current Assets / Current Liabilities | 1.2–2.0 | Retail/subscription can run <1 safely (negative WC model); >3 = lazy balance sheet |
| Quick ratio | (Cash + ST Investments + AR) / CL | > 0.8–1.0 | Inventory-heavy sectors naturally lower |
| Cash ratio | Cash / CL | > 0.2 | — |
| Cash conversion cycle | DSO + DIO - DPO | Lower is better; negative = suppliers fund growth | Compare only within industry |

### Solvency / Leverage

| Ratio | Formula | Heuristic | Context notes |
|---|---|---|---|
| Net Debt / EBITDA | (Total Debt - Cash) / EBITDA | < 3.0x investment-grade comfort; > 4–5x stressed | Utilities/REITs/telecom sustain 4–6x on contracted cash flows |
| Debt / Equity | Total Debt / Book Equity | < 1.0–1.5 | Meaningless when book equity tiny/negative from buybacks — use Net Debt/EBITDA |
| Interest coverage | EBIT / Interest Expense | > 4x comfortable; < 2x distress warning | — |
| FCF / Debt | FCF / Total Debt | > 20% strong | Rating-agency style metric |

### Profitability

| Ratio | Formula | Heuristic |
|---|---|---|
| Gross margin | Gross Profit / Revenue | Software 70–90%, consumer brands 40–60%, retail 20–35%, distribution 10–20% — trend matters most |
| EBITDA margin | EBITDA / Revenue | Sector-specific; falling margin with rising revenue = pricing power problem |
| Net margin | Net Income / Revenue | — |
| ROE | Net Income / Avg Book Equity | > 15% good; decompose via DuPont (4.2) before trusting |
| ROIC | NOPAT / (Debt + Equity - Cash) | ROIC > WACC = value creation; ROIC - WACC spread is the single best quality metric |
| ROA | Net Income / Avg Total Assets | Banks: 1%+ is good |

### Efficiency

| Ratio | Formula | Heuristic |
|---|---|---|
| Asset turnover | Revenue / Avg Total Assets | Sector-specific; rising = improving utilization |
| Inventory turns | COGS / Avg Inventory | Falling turns + rising inventory vs sales growth = demand problem or obsolescence |
| DSO | AR / Revenue * 365 | Rising DSO faster than revenue = channel stuffing / collection risk (QoE flag) |
| DPO | AP / COGS * 365 | Sudden stretch = cash-hoarding or supplier stress |

### Market ratios

| Ratio | Formula | Use |
|---|---|---|
| Earnings yield | EPS / Price | Compare vs 10y bond yield (crude risk premium) |
| Dividend yield | DPS / Price | With payout ratio < 60–70% for sustainability (REITs/utilities higher by design) |
| Buyback yield | Net repurchases / Market Cap | Add to dividend yield = total shareholder yield |
| Short interest % float | Shares short / Float | > 10% = elevated controversy; squeeze mechanics possible |

### OpenBB data mapping (whole framework)
- Precomputed: `obb.equity.fundamental.ratios(symbol, limit=10)`, `obb.equity.fundamental.metrics(symbol)` (`fmp`, `yfinance`).
- Raw rebuild (preferred for auditability): `income`, `balance`, `cash`.
- Short interest: `obb.equity.shorts.short_interest(symbol)` (`finra`, free); float via `obb.equity.ownership.share_statistics`.

---

## 4.2 DuPont Decomposition of ROE

```
3-step:  ROE = (NI/Revenue) * (Revenue/Assets) * (Assets/Equity)
             =  Net Margin  * Asset Turnover  * Equity Multiplier (leverage)

5-step:  ROE = (NI/EBT) * (EBT/EBIT) * (EBIT/Revenue) * (Revenue/Assets) * (Assets/Equity)
             = Tax burden * Interest burden * Operating margin * Turnover * Leverage
```

**Interpretation rules for the agent:**
- Rising ROE driven by margin or turnover = quality improvement. Rising ROE driven ONLY by the equity multiplier (buybacks/leverage) = financial engineering; do not extrapolate and check credit metrics.
- Compare decomposition vs peers: same ROE, different path = different risk (a 20% ROE from 3x leverage ≠ 20% ROE from 12% margins).
- Feed into Residual Income (1.3): sustainable ROE assumption must be justified by which DuPont lever sustains it.

---

## 4.3 Quality of Earnings (QoE) Red Flags

Run before trusting any historical inputs. Each flag lowers the confidence score and may warrant normalizing adjustments.

| # | Red flag | Detection test | Implication |
|---|---|---|---|
| 1 | High/rising accruals | `Accruals = NI - CFO`; accrual ratio `(NI - CFO - CFI_capex_adj)/Avg Assets` persistently > 5–10% | Earnings outrunning cash — future reversals likely (Sloan accrual anomaly) |
| 2 | CFO persistently < Net Income | CFO/NI < 0.8 for 2+ years | Paper profits; normalize to cash-based earnings in models |
| 3 | DSO rising faster than revenue | ΔDSO > +10–15% YoY without business-model change | Channel stuffing / aggressive revenue recognition |
| 4 | Inventory growth > revenue growth | 2+ consecutive periods | Demand shortfall or coming write-downs |
| 5 | Serial "one-time" charges | Restructuring/impairment in ≥3 of last 5 years | They're operating costs; add back into normalized EBIT |
| 6 | Frequent non-GAAP vs GAAP gap widening | (Adjusted EPS - GAAP EPS)/GAAP EPS trending up | Definition drift; anchor models to GAAP + explicit approved add-backs only |
| 7 | Capitalizing what peers expense | Rising capitalized software/dev costs as % of opex | Inflated EBITDA and understated capex — adjust FCF |
| 8 | Deferred revenue shrinking while revenue grows | ΔDeferred revenue negative in a subscription model | Future revenue being pulled forward |
| 9 | Auditor change / late filings / material weakness | Filings, 8-K | Severe flag — cap conviction at LOW |
| 10 | Management turnover in finance org | CFO/CAO departures, news | Elevated restatement risk |
| 11 | Big gap between tax income and book income | Cash taxes paid vs reported tax expense diverging | Earnings quality question |
| 12 | Buybacks funded by debt while insiders sell | `ownership.insider_trading` + debt trend | Misaligned capital allocation |

**Normalized earnings procedure:** start from GAAP EBIT → remove genuinely non-recurring items (litigation settlements, disaster losses, M&A fees — each with a documented reason) → re-include serial "one-offs" → this normalized figure feeds DCF year-0 and comps denominators.

### OpenBB data mapping
- Accruals inputs: `fundamental.income` + `fundamental.cash`. Insider sales: `obb.equity.ownership.insider_trading(symbol)` (`fmp`/`intrinio`). Filings & 8-Ks: `obb.equity.fundamental.filings(symbol, provider="sec")` (free). News on auditor/CFO events: `obb.news.company(symbol)`.

---

## 4.4 Marketing / Business-Side Analysis from Public Reports

Quantitative models need qualitative calibration. Extract these signals from 10-K/10-Q, earnings calls, and investor presentations.

### 4.4.1 Revenue segmentation
- Break revenue by segment, geography, and product line; compute each segment's growth and margin trajectory. A consolidated 8% grower that is a 25% grower (60% of revenue) plus a -10% decliner deserves a different multiple than a uniform 8% grower.
- Mix-shift math: `Consolidated margin drift = SUM(segment weight change * segment margin differential)` — project mix, not just totals.

### 4.4.2 Customer concentration
- 10-K disclosure required when any customer ≥ 10% of revenue. One customer > 20% = concentration risk premium: raise discount rate +0.5–1.0% or haircut multiple ~10%; model a customer-loss bear case explicitly.
- Government-contract concentration: add budget-cycle/political risk.

### 4.4.3 Market share trends
- Triangulate: company revenue growth vs peer set revenue growth vs industry growth (share gainer grows above industry). Sustained share gains justify above-median multiple positioning (Section 2.1 step 4); share losses cap terminal margin assumptions.

### 4.4.4 Unit economics (where disclosed)

```
CAC = Sales & Marketing expense / New customers acquired
LTV = ARPU * Gross margin % * Avg customer lifetime   (lifetime ≈ 1 / churn rate)
LTV/CAC > 3 healthy; < 1 = burning value with growth spend
CAC payback = CAC / (ARPU * Gross margin)  → < 18–24 months for SaaS
Net Revenue Retention (NRR): > 110% excellent (growth without new logos); < 100% = leaky bucket
Rule of 40 (SaaS): Revenue growth % + FCF margin % ≥ 40
```

Feed directly into DCF: NRR > 110% supports high near-term growth with fading CAC; NRR < 100% means revenue growth assumptions must be funded by rising S&M (margin cost).

### 4.4.5 MD&A and guidance-language signals

| Signal | Bullish read | Bearish read |
|---|---|---|
| Guidance action | Raise on both revenue AND margin | "Maintained" after a strong quarter (implied cut to remaining year); withdrawn guidance |
| Language shift | Specific, quantified drivers | New hedging vocabulary: "macro headwinds," "elongated sales cycles," "prudent" assumptions |
| Risk-factor diffs (10-K YoY) | Removed risk factors | Newly added specific risks (litigation, customer loss, covenant language) |
| KPI disclosure changes | Adding granular KPIs | Discontinuing a previously touted KPI (users, NRR) — usually means it turned bad |
| Backlog / RPO | Growing remaining performance obligations | RPO growth < revenue growth = future slowdown signal |
| Capital allocation tone | Buybacks at low multiples, disciplined M&A language | Large "transformational" M&A talk when core growth stalls |

**Agent rule:** MD&A signals do not change the model mechanics; they change assumption placement within the plausible range and the scenario weights (Section 5.5).

### OpenBB data mapping
- Segments: `obb.equity.fundamental.revenue_per_segment` / `revenue_per_geography` (`fmp`). Filings text (MD&A, risk factors): `obb.equity.fundamental.filings(provider="sec")` then fetch/parse document. Earnings calendar & surprises: `obb.equity.calendar.earnings(...)`, `obb.equity.fundamental.historical_eps(symbol)` (`fmp`/`alpha_vantage`). Transcripts: `obb.equity.fundamental.transcript(symbol, year)` (`fmp`, may be paid). KPIs like NRR/CAC: not in structured endpoints — parse investor presentations/filings; treat as manual-extraction fields.

# 5. PAST / PRESENT / FUTURE STOCK VALUE ANALYSIS

The agent's three analytical lenses. Past explains, present triangulates, future projects with uncertainty.

---

## 5.1 PAST — Historical Performance Attribution

### 5.1.1 Total Shareholder Return (TSR) decomposition

For any lookback window (1y, 3y, 5y, 10y):

```
TSR = (P_end + Dividends reinvested) / P_start - 1

Decompose price change:
P = EPS * P/E   →   Price return ≈ EPS growth + P/E multiple change + cross term
Full identity: (1 + price return) = (1 + EPS growth) * (1 + multiple change)
TSR ≈ EPS growth + multiple re-rating + dividend yield (+ small cross terms)
```

Refine EPS growth further: `EPS growth = revenue growth + margin change effect + share-count change (buyback) effect`.

**Interpretation rules:**
- TSR driven mostly by multiple expansion (e.g., P/E 15x → 30x) = re-rating already happened; forward returns depend on fundamentals delivering. Do NOT extrapolate past TSR.
- TSR driven by EPS growth with stable multiple = fundamentally earned; more repeatable if drivers persist.
- Negative TSR with growing EPS = de-rating — ask why (rates, competition, governance). Potential value setup if cause is cyclical/temporary.

### 5.1.2 Relative performance & risk stats
- Alpha vs benchmark: regress excess returns vs index (also yields beta for CAPM).
- Drawdown history, realized volatility (annualized stdev of daily returns * sqrt(252)) — feeds scenario widths and Monte Carlo.
- Rolling correlation vs sector ETF: idiosyncratic vs macro-driven name.

### 5.1.3 Historical fundamental trajectory
- 5–10y CAGRs: revenue, EBIT, EPS, FCF/share, dividend. FCF/share CAGR vs EPS CAGR divergence = earnings-quality question (Section 4.3).
- Multiple history: current NTM P/E and EV/EBITDA vs own 5y/10y range (percentile). Trading at 90th percentile of own history demands a "what changed" justification.

### OpenBB data mapping
- Prices & dividends: `obb.equity.price.historical(symbol, start_date=..., adjustment="splits_and_dividends")`; performance summary: `obb.equity.price.performance(symbol)`.
- Benchmark: `obb.index.price.historical("^GSPC" or "^NDX")` (`yfinance`, `cboe`); sector ETF via `obb.equity.price.historical("XLK", ...)`.
- Historical multiples: `obb.equity.fundamental.metrics(symbol, limit=40, period="quarter")` (`fmp`) or rebuild from price history + historical EPS.
- Fundamental CAGRs: `fundamental.income/cash` with `limit=10`.

---

## 5.2 PRESENT — Fair-Value Triangulation (Football Field)

Never trust one model. Assemble a football field: each method contributes a value RANGE; the overlap zone is the defensible fair-value band.

### Standard rows (per company type, see Section 7.1)

| Method | Range source | Typical weight (non-financial) |
|---|---|---|
| DCF — Gordon terminal | Sensitivity grid 25th–75th | 30–40% |
| DCF — Exit multiple terminal | Sensitivity grid | (blended with above) |
| Trading comps — EV/EBITDA | Peer 25th–75th percentile applied | 25–35% |
| Trading comps — P/E (NTM) | Peer 25th–75th | 15–25% |
| Precedent transactions | Deal quartiles | 0–15% (only if M&A plausible; label as control value) |
| 52-week range / analyst targets | Context only | 0% weight — display, don't average |
| **Excess return** (banks, insurers) | Sensitivity grid 25th–75th | replaces the DCF row |
| **Dividend discount** (REITs) | Grid 25th–75th, unioned with the dividend-growth sweep, eligible rows only | replaces the DCF row |

> **As implemented** (`comps.football_field`, 2026-08-29) — a bank, insurer or REIT gets the
> struck-out DCF row **and** the row above it, not one or the other: "this method does not
> apply here" and "nothing here can be valued" are different findings and the chart says which
> one it means. The dividend row's band skips grid cells whose cost of equity falls below the
> company's own pre-tax cost of debt, since a bar is a published valuation and the model
> declines to publish one there. The excess-return band takes no union with its own
> one-dimensional sweep because that model's grid already sweeps both first-order inputs, so
> the sweep is literally a row of the grid — verified element for element on JPM.

### Weighting procedure

```
FairValue_low  = SUM( w_i * range_low_i )
FairValue_high = SUM( w_i * range_high_i )
Midpoint = (low + high) / 2
Upside % = Midpoint / Current Price - 1
```

**Weighting rules:**
- Weight UP the method whose inputs are most reliable for this company (stable FCF → DCF heavier; no FCF → comps heavier; bank → DDM/RI/P-B heavier).
- If methods disagree wildly (>40% spread between midpoints), do not average into false precision — report both anchors and the assumption that separates them ("DCF says $80 because we assume margin recovery; comps say $55 because peers don't have it yet").
- Precedent range sits above trading range by construction (control premium) — include only with an M&A thesis.

### Conviction score (output alongside the range)

| Level | Criteria |
|---|---|
| HIGH | Methods overlap within ~15%; QoE clean; assumption sensitivity moderate; data complete |
| MEDIUM | Methods within ~30%; minor QoE flags; one major uncertain driver |
| LOW | Methods diverge >30%; QoE flags; thin peer set; pre-profit; conclusion flips on ±15% assumption change (Rule: that's a coin flip, say so) |

---

## 5.3 FUTURE — Scenario Analysis (Bull / Base / Bear)

Mandatory for every valuation. Scenarios differ by DRIVERS, not by arbitrary +/-20% on the answer.

| Element | Bear | Base | Bull |
|---|---|---|---|
| Revenue growth | Competitive loss / recession case | Consensus-anchored | Share gains / TAM upside |
| Margins | Compression (pricing, cost inflation) | Gradual per plan | Operating leverage beats |
| Multiple / terminal | De-rating to historical trough or peer low | Current-normal | Modest re-rate cap (avoid bull-case multiple euphoria) |
| Discount rate | +50–100bp (risk realized) | Base WACC | Base (do not cut WACC in bull cases) |
| Probability | p_bear | p_base | p_bull (sum = 1; default 25/50/25) |

```
Probability-weighted value = p_bear*V_bear + p_base*V_base + p_bull*V_bull
Skew = (V_bull - V_base) vs (V_base - V_bear)   → report asymmetry, it is the trade
```

**Rules:** each scenario must name its trigger conditions (observable events that would shift probability mass). News flow (5.6) updates the probabilities, not the models.

## 5.4 Sensitivity & Simulation

### 5.4.1 Sensitivity analysis (deterministic)
- 2-way data tables on the two most powerful drivers (usually WACC × terminal g; or growth × margin).
- Tornado chart: vary each input ±1 stdev of its historical range, hold others at base, rank by output impact. The top 2–3 bars are the "assumptions to monitor" in the final output.
- Breakeven framing: "current price implies X% growth at Y margin" — reverse-DCF is often the most communicable output: solve for the growth rate that justifies today's price and judge its plausibility.

### 5.4.2 Monte Carlo (probabilistic concept)
- Assign distributions to key inputs: revenue growth ~ Normal(mu, sigma from historical dispersion or analyst estimate spread); margin ~ triangular(bear, base, bull); WACC ~ Normal(base, 0.5%).
- Correlate where economically linked (growth and margin often positively correlated via operating leverage).
- 10,000 iterations → output distribution of fair value → report P10 / P50 / P90 and `P(fair value > current price)`.
- Implementation: numpy/scipy locally; OpenBB supplies the input distributions' parameters (estimate dispersion via `obb.equity.estimates.consensus` high/low/stdev fields).
- **Caveat:** Monte Carlo formalizes uncertainty already assumed; it does not create knowledge. Distribution choice drives the tails — disclose it.

## 5.5 Factor Models & Expected-Return Context

### CAPM (single factor)

```
E[Ri] = Rf + beta_i * (E[Rm] - Rf)
```

Used for: cost of equity (1.1.2), benchmark-adjusted performance (alpha).

### Fama-French 3-factor

```
E[Ri] - Rf = alpha + b*(Rm - Rf) + s*SMB + h*HML
SMB = small-minus-big (size factor); HML = high-minus-low book/market (value factor)
```

### Fama-French 5-factor (adds)

```
+ r*RMW + c*CMA
RMW = robust-minus-weak profitability; CMA = conservative-minus-aggressive investment
```

**Agent usage:**
1. Regress 3–5y of monthly excess returns on factors → factor loadings profile the stock (small-value vs large-growth exposure) and produce a factor-adjusted alpha (is past outperformance skill/mispricing or factor exposure?).
2. Optional: use multi-factor expected return instead of CAPM in Re for value/small names where CAPM under-prices risk.
3. Factor data source: Ken French Data Library (free CSV download; NOT in OpenBB natively). Market/momentum proxies can be built from `obb.index.price.historical` and ETF pairs (IWM-SPY for size, IWD-IWF for value) if the library is unavailable.

## 5.6 Analyst Estimates, Revisions & Earnings Surprise Drift

- **Estimate revisions momentum:** rising consensus EPS (breadth of upward revisions) is one of the most persistent return predictors. Track 1m/3m change in NTM consensus. Revisions UP + price flat = improving setup; revisions DOWN + price up = deteriorating setup.
- **Post-earnings announcement drift (PEAD):** stocks beating (missing) with strong surprise tend to drift in the surprise direction for weeks. Standardized surprise: `SUE = (Actual EPS - Consensus) / stdev of estimates`. |SUE| > 2 with confirming guidance = drift signal; fade if the beat was low-quality (tax rate, one-offs — check 4.3).
- **Dispersion as uncertainty:** wide analyst high-low spread = wide fair-value distribution; feed into Monte Carlo sigma and conviction score.
- **Price targets:** use the RANGE and revision direction, not the mean (targets lag price mechanically).

### OpenBB data mapping (5.5–5.6)
- Consensus & dispersion: `obb.equity.estimates.consensus(symbol)` (`yfinance` basic; `fmp` better fields).
- Price targets: `obb.equity.estimates.price_target(symbol)` (`fmp`/`benzinga`); historical estimates: `obb.equity.estimates.historical(symbol)` (`fmp`).
- Surprise history: `obb.equity.fundamental.historical_eps(symbol)` (actual vs estimate; `alpha_vantage`/`fmp`); earnings dates: `obb.equity.calendar.earnings(...)`.
- Factor regressions: returns from `obb.equity.price.historical` + `obb.index.price.historical`; FF factors external (Ken French library).

## 5.7 News & Sentiment Integration — Adjusting Model Assumptions

Qualitative flow maps to specific quantitative levers. NEVER let news change the model structure; it changes assumptions, scenario probabilities, and conviction.

| News type | Model lever adjusted | Direction & magnitude guidance |
|---|---|---|
| Guidance raise/cut | Year 1–2 revenue/margin in DCF; NTM metric in comps | Reset to new guidance midpoint; cut = also widen bear scenario, shift p_bear +10–15pts |
| New major customer / large contract | Revenue growth path; backlog assumptions | Add contract value over its term; check concentration (4.4.2) |
| Competitor entry / price war | Terminal margin, market-share trajectory | Haircut terminal EBIT margin 100–300bp in bear; raise p_bear |
| Regulatory investigation / litigation | Discount rate risk premium OR explicit contingent liability | +25–100bp on Re, or subtract PV(expected settlement) from equity value |
| M&A rumor (as target) | Add precedent-transaction row to football field | Blend standalone value with takeout value weighted by deal probability |
| M&A announcement (as acquirer) | Accretion/dilution quick math (3.3); leverage check | Dilutive + levering deal = derate; check deal ROIC vs WACC |
| CEO/CFO departure | Conviction level; execution risk premium | Drop conviction one notch; unexplained CFO exit = QoE flag (4.3 #10) |
| Macro: rates up (10y +50bp) | Rf in WACC → discount rate up | Mechanical: rerun DCF; long-duration (high-growth) names hit hardest |
| Macro: recession signals | Scenario probabilities; cyclical revenue paths | Shift weight to bear; check covenant/coverage ratios (4.1) |
| Buyback authorization / dividend initiation | Share count path; capital-allocation quality | Reduce share count in EPS path only if FCF actually funds it |
| Insider cluster buying | Conviction (mild positive) | No model change; note in qualitative summary |
| Short-seller report | QoE full re-run (4.3); conviction cap | Do not price-adjust until claims are checked against filings |
| Sentiment score trend (aggregated news tone) | Scenario probabilities at the margin | Sustained tone shift over weeks > single-story spikes; sentiment is noisy — cap its influence at ±10pts of probability mass |

**Discipline rules:**
1. One news item never moves fair value more than the math it justifies (a 5% guidance cut ≠ a 30% target cut unless leverage/multiple effects compound — show the chain).
2. Distinguish transitory (weather quarter, FX) vs structural (competition, demand) — only structural changes touch terminal assumptions.
3. Log every news-driven assumption change with date, source, and lever moved (audit trail).

### OpenBB data mapping
- Company news: `obb.news.company(symbol, provider=...)` (`yfinance`/`fmp`/`tiingo` free-ish; `benzinga` paid, richest metadata).
- Market/world news: `obb.news.world(...)`.
- Macro levers: `obb.economy.cpi(...)`, `obb.economy.gdp.real(...)`, `obb.economy.fred_series(symbol_id=...)` (DGS10, T10Y2Y, UNRATE, BAMLH0A0HYM2), `obb.fixedincome.government.yield_curve(...)`, `obb.economy.calendar(...)` for upcoming events.
- Sentiment: no universal free endpoint — derive tone locally (LLM classification of `news.company` headlines/bodies); some providers expose sentiment fields on paid tiers.

---

# 6. OPENBB DATA MAPPING — CONSOLIDATED REFERENCE

OpenBB Platform v4, Python API (`from openbb import obb`). Per-model tables appear in each section; this is the master matrix.

## 6.1 Master endpoint matrix

| Data need | Endpoint | Free provider | Better/paid provider | Notes |
|---|---|---|---|---|
| Income statement | `obb.equity.fundamental.income(symbol, period, limit)` | `yfinance` (~4-5y) | `fmp` (deeper hist. paid), `polygon`, `intrinio` | annual + quarterly |
| Balance sheet | `obb.equity.fundamental.balance(...)` | `yfinance` | `fmp`, `polygon`, `intrinio` | |
| Cash flow | `obb.equity.fundamental.cash(...)` | `yfinance` | `fmp`, `polygon` | CapEx, SBC, ΔNWC |
| Growth rates | `obb.equity.fundamental.income_growth / balance_growth / cash_growth` | — | `fmp` | convenience |
| Ratios (precomputed) | `obb.equity.fundamental.ratios(symbol, limit)` | — | `fmp` (free tier limited) | rebuild from raw when possible |
| Key metrics / multiples | `obb.equity.fundamental.metrics(symbol)`, `fundamental.multiples` | `yfinance` | `fmp` | P/E, EV/EBITDA, ROE etc. |
| Dividends | `obb.equity.fundamental.dividends(symbol)` | `yfinance` | `fmp`, `intrinio` | |
| EPS history & surprises | `obb.equity.fundamental.historical_eps(symbol)` | `alpha_vantage` (free key) | `fmp` | actual vs estimate |
| Filings (10-K/Q, 8-K) | `obb.equity.fundamental.filings(symbol, provider="sec")` | `sec` (free) | `fmp`, `intrinio` | text parsing required |
| Segment revenue | `obb.equity.fundamental.revenue_per_segment / revenue_per_geography` | — | `fmp` (often paid tier) | fallback: parse 10-K |
| Earnings call transcript | `obb.equity.fundamental.transcript(symbol, year)` | — | `fmp` | for MD&A-style signals |
| Company profile / beta | `obb.equity.profile(symbol)` | `yfinance` | `fmp`, `intrinio` | sector, description, beta |
| Quote / market cap | `obb.equity.price.quote(symbol)` | `yfinance` | `fmp`, `intrinio` | |
| Price history | `obb.equity.price.historical(symbol, start_date, end_date, adjustment)` | `yfinance` | `polygon`, `tiingo`, `fmp` | use dividend-adjusted for TSR |
| Price performance | `obb.equity.price.performance(symbol)` | — | `fmp`, `finviz` (free) | |
| Analyst consensus | `obb.equity.estimates.consensus(symbol)` | `yfinance` | `fmp`, `intrinio` | fwd EPS/revenue |
| Price targets | `obb.equity.estimates.price_target(symbol)` | — | `fmp`, `benzinga` (paid) | |
| Historical estimates | `obb.equity.estimates.historical(symbol)` | — | `fmp` | revisions tracking |
| Peers | `obb.equity.compare.peers(symbol)` | — | `fmp` (free tier OK) | validate manually |
| Screener | `obb.equity.screener(...)` | `yfinance`, `finviz` | `fmp` | peer building |
| Institutional ownership | `obb.equity.ownership.institutional(symbol)` | — | `fmp`, `intrinio` | 13F-based |
| Insider trades | `obb.equity.ownership.insider_trading(symbol)` | — | `fmp`, `intrinio` | |
| Share statistics / float | `obb.equity.ownership.share_statistics(symbol)` | `yfinance` | `fmp` | |
| Major holders | `obb.equity.ownership.major_holders(symbol)` | `yfinance` | — | |
| Short interest | `obb.equity.shorts.short_interest(symbol)` | `finra` (free) | — | |
| Company news | `obb.news.company(symbol, limit)` | `yfinance`, `tiingo` | `benzinga` (paid), `fmp` | |
| World/macro news | `obb.news.world(...)` | `tiingo` | `benzinga` | |
| Treasury rates (Rf) | `obb.fixedincome.government.treasury_rates(...)` | `federal_reserve` (free) | — | 10y for Rf |
| Yield curve | `obb.fixedincome.government.yield_curve(...)` | `federal_reserve`, `fred` | — | inversion = recession signal |
| FRED series (any macro) | `obb.economy.fred_series(symbol_id=...)` | `fred` (free API key) | — | DGS10, SOFR, HY spreads, UNRATE |
| CPI / GDP | `obb.economy.cpi(...)`, `obb.economy.gdp.real(...)` | `fred`, `oecd` (free) | — | inflation → nominal g |
| Economic calendar | `obb.economy.calendar(...)` | — | `fmp`, `tradingeconomics` | event risk |
| Benchmark index | `obb.index.price.historical("^GSPC")` | `yfinance`, `cboe` | — | beta, alpha, TSR compare |
| Sector ETF proxy | `obb.equity.price.historical("XLK"...)`; holdings `obb.etf.holdings(...)` | `yfinance`, `fmp` | — | sector-relative work |
| Earnings/dividend calendar | `obb.equity.calendar.earnings / dividend(...)` | `yfinance`, `nasdaq` | `fmp` | timing catalysts |

## 6.2 Provider strategy (free vs paid)

| Tier | Stack | Coverage adequacy |
|---|---|---|
| $0 | `yfinance` + `sec` + `federal_reserve`/`fred` + `finra` + `alpha_vantage` (free key) + `finviz` | Full DCF/comps/ratios on large caps; ~4–5y history; consensus basic; no segments/transcripts |
| Freemium (recommended) | Add `fmp` free/starter + `tiingo` free | 5y+ history, ratios, peers, price targets, revisions, news depth |
| Paid | `fmp` premium, `polygon`, `intrinio`, `benzinga` | 10y+ as-reported statements, transcripts, segments, real-time, rich news/sentiment |

**Operational rules for the agent:**
1. Always record `provider` and retrieval timestamp with every datapoint (reproducibility).
2. Cross-validate any load-bearing number (share count, net debt, LTM EBITDA) across 2 providers when available; discrepancy > 3% → flag and prefer SEC-filed figures.
3. Cache fundamentals per session (rate limits: yfinance throttles bursts; fmp free = 250 calls/day class limits).
4. Currency: confirm reporting currency vs listing currency (`profile`), convert with `obb.currency.price.historical(...)` when mixed.
5. Missing-field policy: never silently impute; either derive from raw statements or mark the model input DEGRADED and reflect it in conviction.

# 7. AGENT DECISION FRAMEWORK

## 7.1 Model selection by company type (decision rules)

### Classification inputs
Determine type from: `obb.equity.profile` (sector/industry), fundamentals (FCF positivity, dividend policy, segment count), and these tests in order:

```
IF sector in {Banks, Insurance, Diversified Financials}      -> TYPE = FINANCIAL
ELIF REIT structure (real estate + distribution mandate)     -> TYPE = REIT
ELIF segments >= 3 with distinct industries or holdco stakes -> TYPE = CONGLOMERATE
ELIF net income < 0 AND FCF < 0                              -> TYPE = PRE_PROFIT
ELIF revenue growth > 15% and reinvestment-heavy             -> TYPE = GROWTH
ELIF dividends stable 10y AND payout > 40%                   -> TYPE = MATURE_PAYER
ELSE                                                         -> TYPE = MATURE_STANDARD
Modifier: commodity/cyclical industry (energy, materials, semis-memory, airlines) -> CYCLICAL flag
```

### Model priority matrix

| Company type | PRIMARY models | SECONDARY / cross-check | AVOID | Type-specific notes |
|---|---|---|---|---|
| Growth tech (profitable) | DCF (10y, fade to steady state); EV/Sales + EV/EBITDA comps vs growth-adjusted peers | Reverse-DCF (what does price imply?); Rule of 40; PEG | DDM; P/B; LBO floor | SBC treatment critical (1.1.1); NRR/unit economics calibrate growth (4.4.4) |
| Pre-profit / early stage | Scenario-weighted DCF (survive/scale/fail branches); EV/Sales comps with gross-margin pairing | Unit economics viability (LTV/CAC); cash-runway analysis: `runway = cash / quarterly burn` | P/E, EV/EBITDA, DDM, RI, LBO | Conviction cap: LOW-MEDIUM; probability of failure explicit; dilution from future raises in share count |
| Mature industrial / consumer | DCF (5y); EV/EBITDA + EV/EBIT + P/E comps | FCF yield; DuPont trend; LBO floor if under-levered | EV/Sales (uninformative) | Mid-cycle margin normalization if CYCLICAL flag |
| Mature dividend payer (utility, telecom, staples) | DDM multi-stage; DCF | P/E comps; dividend yield vs history & bonds; RI | EV/Sales | Payout sustainability check (FCF coverage > 1.2x); rate sensitivity high |
| Bank | Residual Income / justified P/B; multi-stage DDM | P/TBV vs ROTE regression across peers; P/E | DCF-FCFF, EV/EBITDA, EV/Sales (ALL invalid — cannot define EV/FCFF for banks) | Key drivers: NIM, credit costs, CET1; regulatory capital constrains payout |
| Insurance | RI / P/B vs ROE; DDM | P/E on operating EPS | FCFF DCF, EV multiples | Reserve development quality = QoE focus |
| REIT | P/AFFO comps; AFFO-based DDM; NAV (cap-rate on NOI) | Dividend yield spread vs 10y treasury; debt/EBITDA | P/E (depreciation distorts), FCFF DCF standard form | `NAV = NOI / cap rate - net debt`; payout of AFFO < 90% |
| Conglomerate / holdco | SOTP (3.4) | DCF on consolidated as sanity; holdco discount 10–20% | Single-multiple comps (mixes segment economics) | Listed-stake values marked to market |
| Cyclical (flag) | DCF on normalized mid-cycle earnings; EV/mid-cycle EBITDA | P/B at trough (floor); "peak multiple on trough earnings" rule: cyclicals look CHEAPEST at the top | Trailing P/E at cycle peak (value trap generator) | Never extrapolate peak margins into terminal value |

## 7.2 Recommended analysis pipeline (execution order)

```
STEP 1: DATA PULL
  profile, 10y statements (annual + 8 quarters), prices (10y, adjusted),
  estimates, dividends, ownership, short interest, news (90 days), macro set
  (10y yield, CPI, HY spread, yield curve), peers + their key metrics.

STEP 2: DATA QUALITY GATE
  - Statements tie? (assets = L + E; CFO reconciles to NI + adjustments)
  - Share count consistent across endpoints (±3%)?
  - Currency/fiscal-year alignment; calendarize peers
  - QoE screen (4.3) -> quality score; normalize one-offs
  FAIL any critical check -> continue with DEGRADED flag; cap conviction.

STEP 3: HISTORICAL ANALYSIS (PAST — 5.1)
  TSR decomposition (growth vs re-rating vs dividends), CAGRs,
  margin/ROIC trajectory, multiple percentile vs own history, DuPont trend.

STEP 4: CLASSIFY & SELECT MODELS (7.1)
  Output: company type, primary + secondary model list, avoided models w/ reason.

STEP 5: BUILD MODELS
  Primary intrinsic model with documented assumptions table
  (each assumption: value, source, confidence H/M/L).
  Comps with screened peer table. Sensitivity grids (5.4.1).

STEP 6: VALUATION TRIANGULATION (PRESENT — 5.2)
  Football-field ranges, weights + rationale, overlap zone, conviction score.

STEP 7: SCENARIO OVERLAY (FUTURE — 5.3)
  Bull/base/bear with named triggers, probabilities, probability-weighted value,
  skew statement. Optional Monte Carlo if inputs justify (5.4.2).

STEP 8: NEWS / SENTIMENT ADJUSTMENT (5.7)
  Map last-90-day news to specific levers; adjust scenario probabilities;
  log every adjustment (date, source, lever, magnitude).

STEP 9: OUTPUT
  See 7.3 format. Include monitoring list: top tornado drivers + scenario triggers
  + next catalyst dates (earnings, macro events).
```

## 7.3 Output format (standardized)

```
COMPANY: <name, ticker> | AS-OF: <date> | PRICE: <px> | TYPE: <classification>
FAIR VALUE RANGE: $X – $Y (midpoint $Z) | UPSIDE/(DOWNSIDE) AT MID: +/-N%
PROBABILITY-WEIGHTED VALUE: $W (bear $A @ p%, base $B @ p%, bull $C @ p%)
CONVICTION: HIGH / MEDIUM / LOW — <one-line reason>
METHODS & WEIGHTS: DCF 40% ($..–$..), EV/EBITDA comps 35% ($..–$..), ...
KEY ASSUMPTIONS: <top 3–5 with values and sources>
KEY RISKS: <top 3, each tied to the lever it breaks>
WHAT WOULD CHANGE THE VIEW: <scenario triggers / monitoring list>
DATA QUALITY: <clean / flags listed> | PROVIDERS: <list + timestamps>
DISCLAIMER: <7.4 boilerplate>
```

Communication rules (from the analyst playbook):
- Lead with the "so what" — the range, the skew, and the one assumption that matters most.
- No false precision: round fair values to the nearest dollar (or ~1%); never quote four decimals on an estimate built on a ±2% growth guess.
- If the conclusion flips on a ±15% change in one assumption, SAY SO explicitly — that recommendation is not robust.

## 7.4 Explicit caveats (must accompany every output)

1. **All models are estimates.** Every valuation is a simplification built on assumptions; stated ranges reflect model uncertainty, not outcome guarantees.
2. **Garbage in, garbage out.** Outputs inherit the quality of provider data and the honesty of reported financials; QoE flags and DEGRADED data materially reduce reliability.
3. **Past performance does not predict future results.** Historical CAGRs, multiples, and factor premia can and do break; regime changes (rates, technology, regulation) invalidate extrapolation.
4. **Markets can stay irrational longer than models stay solvent.** A fair-value gap is not a timing signal; convergence catalysts are required and uncertain.
5. **The agent's output is decision support, not financial advice.** It is not a solicitation, not certified investment advice, and not a substitute for a licensed professional's judgment or the user's own risk assessment and position sizing.
6. **Conflicts and coverage gaps.** Free-tier data may be delayed, incomplete, or revised; small caps and non-US listings have systematically worse data coverage — treat outputs there with extra skepticism.

---

## Appendix A — Quick formula index

```
WACC              = E/V * Re + D/V * Rd * (1 - Tc)
CAPM              Re = Rf + beta * ERP
FCFF              = EBIT*(1-Tc) + D&A - CapEx - ΔNWC
Gordon TV         = FCF_{n+1} / (WACC - g)
DDM (1-stage)     P0 = DPS_1 / (Re - g)
Residual income   RI_t = (ROE_t - Re) * B_{t-1};  Value = B0 + PV(RI)
Justified P/B     = 1 + (ROE - Re) / (Re - g)
EV                = MC + Debt + Pref + Minorities - Cash
EVA               = (ROIC - WACC) * Invested Capital
Sustainable g     = ROE * (1 - payout)
DuPont            ROE = Net margin * Asset turnover * Equity multiplier
CCC               = DSO + DIO - DPO
LTV/CAC           = (ARPU * GM% / churn) / (S&M / new customers)
SUE               = (Actual EPS - Consensus) / stdev(estimates)
TSR               ≈ EPS growth + multiple change + dividend yield
Runway (quarters) = Cash / quarterly cash burn
NAV (REIT)        = NOI / cap rate - net debt
Reverse DCF       solve g such that DCF(g) = current price
```

## Appendix B — Healthy-range cheat sheet (context-adjust per 4.1)

```
Net Debt/EBITDA < 3x | Interest coverage > 4x | Current ratio 1.2–2 | ROIC > WACC
FCF conversion (FCF/NI) > 80% | Payout < 70% (non-REIT) | LTV/CAC > 3 | NRR > 100%
Rule of 40 (SaaS) >= 40 | AFFO payout (REIT) < 90% | CET1 (banks) > regulatory min + 1–2%
```

---

*End of reference. Version-control this document; log all changes with rationale. Assumptions matter more than formulas.*



