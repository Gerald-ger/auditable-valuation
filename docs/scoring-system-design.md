# Company Scoring & Ranking System — Design Document

**Version:** 1.0 | **Date:** 2026-07-31 | **Author:** Morgan (Financial Analyst Agent)
**Depends on:** `docs/financial-models-reference.md` (§4 ratios, §5 past/present/future, §7.1 model-priority matrix), `backend/financial_models.py` (ratio + DCF engine), yfinance fundamentals dict from `data_provider.get_fundamentals`.

> ### ⛔ This is a specification, not a description. Do not edit it to match the code.
>
> Where this document and `backend/scoring.py` or `backend/sector_weights.py` disagree, the
> disagreement is a **finding**. §5.2's acceptance criteria are load-bearing in exactly this
> way: `backend/tests/test_plausibility.py` encodes them, and RIVN scoring 74/Tier A against
> a written spec of Tier 3–5 was caught here and nowhere else — the golden snapshot had been
> recording 74/A as *expected* since the day it was written.
>
> **If the code has moved,** update the table and add a dated note saying what changed and
> why, as the `pre_profit_growth` row does. Do not quietly restate the code's numbers as
> though they had always been the design.

---

## 1. Feasibility Verdict

### 1.1 The three options evaluated

| Criterion | Deterministic Python | Local 7B LLM (qwen2.5:7b, CPU) | Hybrid (deterministic score + LLM narrative/sentiment) |
|---|---|---|---|
| Reproducibility (same inputs → same score) | Perfect. Pure function of inputs. | Poor. Even at temperature=0, output varies with prompt ordering, context length, and Ollama version. A ranking that changes on re-run is unusable. | Perfect for the score (deterministic); LLM output is labeled commentary, never the number. |
| Auditability | Full. Every score decomposes to metric → anchor → weight. "Why 72?" has an exact answer. | None. "Why 72?" answers with a plausible-sounding rationalization that may not match any actual computation. | Full for the score. |
| Numerical reliability | Exact float arithmetic. | 7B models are demonstrably bad at consistent multi-factor weighted arithmetic: digit transposition, sign errors on negative metrics, silent unit confusion (%, bps, $M vs $B), and weighted sums that don't reconcile to the stated weights. This is the core task of a scoring engine — it is the LLM's weakest skill. | Arithmetic never touches the LLM. |
| Latency (i7-1355U, no GPU, ~5–10 tok/s) | <10 ms per company. Ranking 100 tickers: instant (data fetch is the bottleneck, not scoring). | A structured scoring response is ~400–800 output tokens → **1–3 minutes per company**. Ranking 50 companies: 1–2.5 hours of CPU pegged at 100%. Not viable as the scoring path. | Score instant; LLM runs only on demand for the one company the user is viewing. |
| Hallucination risk | Zero (worst case: a bug, which is findable). | High. Will confidently invent metric values that were never in the prompt, "recall" stale training-data fundamentals, and blend them with live data. | Contained: LLM receives only pre-computed numbers and is asked to explain, not compute. |
| Where the LLM genuinely adds value | — | Narrative interpretation ("ROE is high but DuPont shows it's leverage-driven — treat with caution"); classifying news headlines as positive/negative/neutral (classification, not arithmetic — a task 7B models do acceptably); summarizing the score card in plain language. | Exactly these two roles. |

### 1.2 Verdict — DECISIVE

**Build the scoring engine as a deterministic Python library. Use the local LLM only for two optional, non-blocking roles: (a) generating the plain-language narrative from the already-computed score card, and (b) classifying news headlines for an optional, weight-capped Sentiment pillar.**

The LLM must **never** produce, adjust, or "sanity-check" the numeric score. This mirrors the reference doc's own discipline (§5.7): qualitative signals adjust assumptions within bounded ranges — they never replace the math. If Ollama is down, the score is unaffected; only the prose and the (optional) sentiment pillar degrade, and the coverage indicator says so.

Practical consequence for the codebase: a single `backend/scoring.py` module (~300–400 lines) + one JSON/dict weight library. No new dependencies.

---

## 2. Scoring Architecture

### 2.1 Pillars and metrics

Five core pillars, plus one optional AI-assisted pillar. All core metrics are computable **today** from the yfinance fundamentals dict (`info` + statements) already flowing through `financial_models.py`. Items marked ⬆ get better inputs once OpenBB lands.

#### Pillar V — Valuation (is the price reasonable for what you get?)

| Metric | Source (yfinance) | Direction | Notes |
|---|---|---|---|
| Earnings yield (fwd) = 1 / forwardPE | `info.forwardPE` (fallback `trailingPE`) | higher = better | Negative EPS → metric scores 0, not missing (expensive by definition) |
| FCF yield = FCF / marketCap | `cash_flow` statement (`OCF + CapEx`, same period), `info.marketCap`; `info.freeCashflow` **fallback only** | higher = better | Reference §4.1: >6–8% notable. `info.freeCashflow` is a single quarter for some issuers and annual for others (measured 2026-08-06: MSFT 0.244×, GOOGL 0.309× of the annual statement), which silently rescales the metric — same trap `dcf_valuation()` avoids. Falling back raises the `fcf_from_info_unverified_period` flag |
| EV/EBITDA | `info.enterpriseToEbitda` | lower = better | Skip for banks/insurance (§2.1.2 of reference: meaningless) |
| P/B | `info.priceToBook` | lower = better | Weighted up for financials; pair with ROE (justified P/B, ref §1.3) |
| EV/Sales | `info.enterpriseToRevenue` | lower = better | Only used for PRE_PROFIT type (ref §2.1.2) |
| DCF upside % | existing `dcf_valuation()` output `upside_pct` | higher = better | Only when DCF is applicable per §7.1 (skip banks/REITs/pre-profit). **Known limitation:** the anchor floors at −40%, and a two-stage FCFF DCF puts several quality mega-caps past it (AAPL −53.7% as of 2026-08-06), so they all score 0 and the metric stops discriminating among them. That is the model's honest verdict — a 2.2% FCF yield discounted at ~9.6% is expensive on FCFF — not a data fault, so it is scored rather than suppressed. Read it alongside the DCF's implied exit multiple: AAPL's terminal value assumes exiting at 8.5× EV/EBITDA against 27.2× today, i.e. severe multiple compression |
| Intrinsic upside % | `financial_models.intrinsic_valuation()` output `upside_pct` | higher = better | **Added 2026-08-29.** The same `UPSIDE_ANCHORS` curve `dcf_upside_pct` uses, shared by reference in `scoring.METRIC_ANCHORS` rather than copied. Active for `financials_bank` and `financials_insurance` only — the model behind it is the excess return one, and on JPM it is algebraically the justified-P/B gap (2.5660 / 2.7890 − 1 = −8.0%), which is why the V pillar can finally see a bank being expensive against its own book rather than only against its peers'. **Deliberately not given to `real_estate_reit`:** its model refuses on the one REIT fixture, so scoring it would add an input this repository has never observed produce a value. `None` when the model errors — never 0, which would read as "no upside" rather than "no answer" |
| Dividend yield | `info.dividendYield` | higher = better | Only for MATURE_PAYER / utilities / REITs; gated by payout sustainability |

⬆ OpenBB: NTM consensus multiples, peer-median comparison (peer-relative percentile mode, §2.2 below), P/AFFO for REITs.

#### Pillar Q — Quality / Profitability (is this a good business?)

| Metric | Source | Direction | Notes |
|---|---|---|---|
| ROE | `info.returnOnEquity` | higher = better | **DuPont guard:** if equity multiplier > 4 (from existing `ratio_analysis()`), cap the ROE metric score at 70 — leverage-manufactured ROE is not quality (ref §4.2) |
| ROIC proxy = NOPAT / (debt + equity − cash) | statements + info | higher = better | The single best quality metric per ref §4.1; compare vs WACC from `_wacc()` |
| Operating margin | `info.operatingMargins` | higher = better | Sector-specific anchors (see 2.3) |
| Gross margin | `info.grossMargins` | higher = better | Sector-specific anchors |
| FCF conversion = FCF / Net Income | both legs from the `cash_flow` / `income_statement` **statements** | higher = better | <0.8 for 2+ yrs is a QoE flag (ref §4.3 #2); score low. Both legs must be annual: pairing `info.freeCashflow` (a quarter for some issuers) with annual net income is a mixed-basis ratio, not a conversion rate |

#### Pillar H — Financial Health (can it survive stress?)

| Metric | Source | Direction | Notes |
|---|---|---|---|
| Net Debt / EBITDA | `info.totalDebt`, `info.totalCash`, `info.ebitda` | lower = better | Bands shift for utilities/REITs/telecom (ref §4.1: 4–6x sustainable there) |
| Interest coverage = EBIT / interest | statements (already in `ratio_analysis()`) | higher = better | >4 comfortable, <2 distress |
| Current ratio | `info.currentRatio` | band-optimal (1.2–2.0) | Skip for banks; retail/subscription tolerate <1 (anchor override) |
| Debt / Equity | computed in `ratio_analysis()` | lower = better | Skip when book equity tiny/negative from buybacks (mark missing, renormalize) |
| Cash runway (PRE_PROFIT only) = cash / quarterly burn | statements | higher = better | Ref §7.1 pre-profit row; replaces ND/EBITDA |
| Equity/Assets (banks only) | balance sheet | higher = better | Leverage lens valid for banks; crude CET1 proxy until OpenBB ⬆ |

#### Pillar G — Growth (is the future bigger than the present?)

| Metric | Source | Direction | Notes |
|---|---|---|---|
| Revenue growth (yoy) | `info.revenueGrowth` | higher = better | |
| Revenue CAGR (3y) | income statement series (existing `_series`) | higher = better | Smooths one-year noise; **label: historical fact, not forecast** |
| Earnings growth | `info.earningsGrowth` | higher = better | |
| Fwd vs trailing P/E gap = trailingPE/forwardPE − 1 | info | higher = better | Crude implied-EPS-growth signal; drop when either PE missing/negative |

⬆ OpenBB: consensus NTM revenue/EPS growth, **estimate-revision momentum** (ref §5.6 — one of the most persistent predictors; add as a metric when `obb.equity.estimates.historical` is wired).

#### Pillar M — Momentum / Technical (is the market agreeing or disagreeing?)

| Metric | Source | Direction | Notes |
|---|---|---|---|
| Price vs 200-day MA = price/twoHundredDayAverage − 1 | `info` | higher = better (capped) | Anchor caps the top: +40% above 200d scores no higher than +25% (overextension isn't extra merit) |
| 52-week range position = (price − 52wLow)/(52wHigh − 52wLow) | `info` | higher = better | |
| Relative 52w change = 52WeekChange − SandP52WeekChange | `info` | higher = better | Sector ETF-relative ⬆ with OpenBB |
| ~~Analyst signal = (targetMeanPrice/price − 1), gated by numberOfAnalystOpinions ≥ 4~~ | `info` | — | **Removed — superseded by the note below.** |

**`analyst_upside` is computed but scored in no pillar** (`backend/scoring.py`); it is
surfaced only as `analyst_context`. A target price is a twelve-month forecast of where a
stock will trade, not an estimate of what the business is worth, and published targets sit
above price on average. It also double-counted sell-side opinion: the DCF's growth input is
already analyst consensus, so one source was moving two of five metrics with correlated
errors of the same sign. Removing it moved the composite −3 to +1 and no fixture changed
tier.

#### Pillar S — News Sentiment (OPTIONAL, AI-assisted, weight-capped)

- Input: last ~30 days of headlines (`yf.Ticker.news` today; `obb.news.company` ⬆).
- LLM task: classify each headline `{positive | negative | neutral}` with a fixed few-shot prompt, temperature 0. Classification only — no scoring math in the prompt.
- Pillar score = `50 + 50 * (pos − neg)/total`, shrunk toward 50 when headline count < 10.
- **Weight cap: 0.10 in every sector profile, default 0.00 (off).** When enabled, it takes its weight proportionally from M and V. This mirrors ref §5.7's rule: sentiment moves probabilities at the margin (±10 pts), never the model.
- If Ollama unavailable → pillar marked missing, weights renormalize, coverage indicator reflects it. Scoring never blocks on the LLM.

### 2.2 Normalization: metric → 0–100

**Primary method (works today, no peer data needed): absolute piecewise-linear mapping against healthy-range anchors from the reference doc (§4.1, Appendix B).**

```python
def piecewise_score(value, anchors):
    """anchors: [(x0, s0), (x1, s1), ...] sorted by x. Linear interpolation,
    clipped to [first_score, last_score]. Descending scores encode
    lower-is-better; a peak in the middle encodes band-optimal."""
    if value is None: return None          # missing, NOT neutral-50
    xs = [a[0] for a in anchors]
    if value <= xs[0]:  return anchors[0][1]
    if value >= xs[-1]: return anchors[-1][1]
    for (x0, s0), (x1, s1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            return s0 + (s1 - s0) * (value - x0) / (x1 - x0)
```

Default anchor table (`METRIC_ANCHORS`) — values grounded in reference §4.1 heuristics; sector profiles may override (see §3):

```python
METRIC_ANCHORS = {
  # Valuation
  "earnings_yield_fwd": [(-0.05, 0), (0.00, 10), (0.03, 40), (0.05, 60), (0.08, 85), (0.12, 100)],
  "fcf_yield":          [(-0.05, 0), (0.00, 15), (0.02, 40), (0.05, 70), (0.08, 90), (0.12, 100)],
  "ev_ebitda":          [(30, 0), (20, 25), (14, 50), (10, 70), (7, 90), (4, 100)],   # descending
  "p_b":                [(8, 10), (4, 35), (2.5, 55), (1.5, 75), (1.0, 90), (0.6, 100)],
  "ev_sales":           [(25, 0), (15, 20), (10, 40), (6, 60), (3, 85), (1.5, 100)],
  "dcf_upside_pct":     [(-40, 0), (-15, 30), (0, 50), (15, 70), (40, 90), (80, 100)],
  "dividend_yield":     [(0.0, 20), (0.01, 40), (0.025, 65), (0.04, 85), (0.06, 100), (0.09, 70)],  # >9% = distress signal, score falls
  # Quality
  "roe":                [(0.0, 10), (0.08, 40), (0.15, 70), (0.20, 85), (0.30, 100)],
  "roic":               [(0.0, 10), (0.06, 35), (0.09, 55), (0.12, 75), (0.20, 95), (0.30, 100)],
  "operating_margin":   [(0.0, 10), (0.05, 35), (0.10, 55), (0.20, 80), (0.30, 100)],
  "gross_margin":       [(0.10, 10), (0.25, 35), (0.40, 60), (0.60, 85), (0.80, 100)],
  "fcf_conversion":     [(0.0, 0), (0.5, 30), (0.8, 60), (1.0, 85), (1.3, 100), (2.5, 80)],  # extreme >2.5 = check accruals
  # Health
  "net_debt_ebitda":    [(6.0, 0), (5.0, 20), (4.0, 40), (3.0, 65), (1.5, 85), (0.0, 100)],  # net cash caps at 100
  "interest_coverage":  [(0.0, 0), (2.0, 25), (4.0, 60), (8.0, 85), (15.0, 100)],
  "current_ratio":      [(0.5, 10), (1.0, 50), (1.2, 75), (1.6, 100), (2.5, 90), (4.0, 60)],  # band-optimal; >3 lazy balance sheet
  "debt_equity":        [(3.0, 10), (2.0, 30), (1.5, 50), (1.0, 70), (0.5, 90), (0.1, 100)],
  "cash_runway_q":      [(2, 0), (4, 30), (8, 60), (12, 80), (20, 100)],   # 0 quarters is a reading, not a gap - see the note below
  "equity_assets":      [(0.04, 10), (0.06, 40), (0.08, 65), (0.10, 85), (0.14, 100)],
  # Growth
  "revenue_growth":     [(-0.15, 0), (-0.05, 20), (0.0, 35), (0.05, 55), (0.12, 75), (0.25, 95), (0.50, 100)],
  "revenue_cagr_3y":    [(-0.10, 0), (0.0, 30), (0.05, 55), (0.10, 75), (0.20, 95), (0.35, 100)],
  "earnings_growth":    [(-0.30, 0), (-0.10, 20), (0.0, 40), (0.10, 65), (0.25, 85), (0.50, 100)],
  "pe_gap":             [(-0.20, 10), (0.0, 45), (0.10, 65), (0.25, 85), (0.50, 100)],
  # A value of exactly zero is a reading and is scored. A missing row is not,
  # and is excluded from coverage. **Amended 2026-08-27** - two metrics could
  # not tell the two apart, and both failed in the direction that flatters:
  #   cash_runway_q     `and total_cash` dropped a burning company holding
  #                     nothing, the worst case the metric exists to catch.
  #                     Measured on RIVN: one dollar of cash scored Health 32,
  #                     zero dollars scored it 63.
  #   interest_coverage EBIT/0 has no value, so the metric was excluded - while
  #                     an issuer paying one dollar of interest scored 100. A
  #                     reported zero now takes the top of this curve, carrying
  #                     `raw: null` and a note, because printing 15.0 would put
  #                     a ratio on screen that no statement supports.
  # Momentum
  "price_vs_200dma":    [(-0.30, 5), (-0.10, 30), (0.0, 55), (0.10, 80), (0.25, 100), (0.60, 85)],  # blow-off tops score down
  "range_52w_pos":      [(0.0, 10), (0.3, 35), (0.5, 55), (0.8, 85), (1.0, 100)],
  "rel_52w_change":     [(-0.40, 5), (-0.15, 30), (0.0, 55), (0.15, 80), (0.40, 100)],
  "analyst_upside":     [(-0.20, 10), (0.0, 45), (0.10, 65), (0.25, 85), (0.50, 100)],
}
```

Rules:
- **Winsorize before scoring:** clamp raw inputs to sane bounds (e.g., PE ∈ [-1000, 1000], margins ∈ [-2, 2]) to survive yfinance junk values.
- **Descending anchor lists** (ev_ebitda, p_b, ...) are just sorted descending by x — same interpolation code, reversed.
- **Non-monotonic anchors** encode "too much of a good thing" (dividend yield >9% = cut risk; current ratio >3 = lazy capital; price 60% above 200dma = froth). This is deliberate and comes straight from the reference doc's context notes.

**Secondary method (when a peer list exists — OpenBB `compare.peers` ⬆, or user-supplied):** peer-relative percentile. `score = 100 * rank(value among peers) / (n−1)` (inverted for lower-is-better), require n ≥ 5 peers (ref §2.1.1: fewer than 4 → low confidence). When both methods are available, blend 50/50 and report both. The absolute method remains the default and the fallback — it never depends on data you might not have.

### 2.3 Missing data policy

**Never silently impute neutral-50.** (Reference §6.2 rule 5: never silently impute.)

1. A missing metric contributes nothing; its weight is removed and the remaining weights in that pillar are **renormalized** to sum to 1.
2. A pillar with < 40% of its metric weight available is marked `insufficient` and excluded; pillar weights renormalize across remaining pillars.
3. **Coverage indicator** (always reported): `coverage = sum(weight of scored metrics, pillar-weight adjusted) / 1.0`, as a percent. Composite scores with coverage < 60% are displayed with a LOW-confidence badge and excluded from cross-company ranking tables by default.
4. Exception: metrics that are missing *because the value is bad* are scored, not skipped — negative EPS → earnings yield scores ~0; negative FCF → FCF yield scores ~0. Missing-because-unreported ≠ missing-because-terrible; the code must distinguish (`None` from provider vs computed negative).

---

## 3. Sector Weighting Library

Grounded in the model-priority matrix (reference §7.1): sectors where the primary models are intrinsic-cash-flow get higher V+Q; capital-regulated financials shift to P/B–ROE logic; payers shift to yield and balance-sheet durability; pre-profit shifts to growth and survival.

Classification: start from `info.sector` / `info.industry` (yfinance GICS-ish strings), then apply the §7.1 override tests in order — FINANCIAL / REIT / PRE_PROFIT beat the sector label (a pre-profit biotech uses `pre_profit_growth`, not `healthcare`).

```python
# Pillar order: V=Valuation, Q=Quality, H=Health, G=Growth, M=Momentum
# S (sentiment) omitted: capped at 0.10, taken proportionally from M and V when enabled.
SECTOR_WEIGHTS = {
  #                        V     Q     H     G     M    substitutions / anchor overrides
  "technology":         {"V": 0.20, "Q": 0.25, "H": 0.10, "G": 0.30, "M": 0.15,
                         "notes": "EV/EBITDA + EY + FCF yield; drop P/B (intangible-heavy, ref §2.1.2); gross-margin anchors shifted up (software 70-90%)"},
  "communication_svcs": {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15,
                         "notes": "Split personality (telecom vs internet): telecom industries get utilities-style ND/EBITDA bands + dividend yield on"},
  "consumer":           {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15,
                         "notes": "Staples industries: shift G->Q (Q 0.30, G 0.15), dividend yield on. Discretionary: as-is, CYCLICAL flag"},
  "healthcare":         {"V": 0.20, "Q": 0.30, "H": 0.15, "G": 0.25, "M": 0.10,
                         "notes": "Margin quality dominates; biotech w/ negative NI -> reclassify pre_profit_growth"},
  "energy":             {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15,
                         "notes": "CYCLICAL: FCF yield weighted up inside V; growth deliberately low (never extrapolate peak, ref §7.1); ND/EBITDA strict"},
  "industrials":        {"V": 0.25, "Q": 0.25, "H": 0.20, "G": 0.15, "M": 0.15,
                         "notes": "EV/EBITDA + EV-EBIT-style EY; asset turnover added to Q (ref §4.1 efficiency); interest coverage weighted up"},
  "logistics":          {"V": 0.25, "Q": 0.25, "H": 0.25, "G": 0.10, "M": 0.15,
                         "notes": "Sub-type of industrials: asset turnover + FCF conversion weighted up in Q; leverage matters more (capital-intensive) -> H raised"},
  "utilities":          {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15,
                         "notes": "Dividend yield ON and weighted up in V (DDM logic, ref §1.2); ND/EBITDA bands relaxed to [(8,0),(6,25),(5,50),(4,70),(2.5,90),(1,100)]; payout<80% gate"},
  "real_estate_reit":   {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15,
                         "notes": "DROP P/E and EV/EBITDA-standard; V = dividend yield + P/B + FFO-proxy yield ((NI + D&A)/marketCap as P/FFO stand-in until OpenBB); ND/EBITDA bands relaxed as utilities; payout vs FFO < 90% gate (ref §7.1)"},
  "financials_bank":    {"V": 0.30, "Q": 0.30, "H": 0.20, "G": 0.10, "M": 0.10,
                         "notes": "DROP EV/EBITDA, EV/Sales, FCF yield, current ratio, ND/EBITDA, DCF upside (all invalid, ref §7.1). V = P/B + earnings yield + dividend yield + valuation_upside_pct (added 2026-08-29 — the excess return model's own upside, on the DCF's anchor curve). Q = ROE (justified-P/B pairing) + ROA (>1% good). H = equity/assets"},
  "financials_insurance":{"V": 0.30, "Q": 0.30, "H": 0.20, "G": 0.10, "M": 0.10,
                         "notes": "Same drops as banks, and the same valuation_upside_pct addition; P/B vs ROE is the axis (ref §7.1)"},
  "pre_profit_growth":  {"V": 0.15, "Q": 0.25, "H": 0.25, "G": 0.25, "M": 0.10,
                         "notes": "V = EV/Sales ONLY; Q = gross margin + margin trend (path to profit); H = cash runway + debt/equity (survival, ref §7.1: runway = cash/quarterly burn); conviction hard-capped at MEDIUM"},
}
DEFAULT_WEIGHTS = {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15}  # unclassified fallback
```

**Rebalanced 2026-08-10 — superseded from the table above.** Q was 0.15 and G was 0.35,
which weighted the pillar these companies fail at a quarter of the pillar they ace: RIVN
scored quality 10, growth 98, and came out 74/Tier A — above AAPL's 67, and two tiers
above the "Tier 3-5" §5.2 of this document specifies for this path. Rebalanced to
0.25/0.25, which with the `cash_runway_q` fix lands RIVN at 60/Tier B. Recorded honestly:
these curves are still not validated against forward returns, so this enforced a written
expectation rather than adding evidence.

Every row sums to 1.00. Substitutions are implemented as per-sector `include`/`exclude` metric lists plus optional `anchor_overrides` — three dicts total, not a framework.

---

## 4. Composite Score, Tiers, and Output Format

### 4.1 Composite

```
pillar_score_p = Σ (metric_weight_i × metric_score_i) / Σ metric_weight_i     (available metrics only)
composite      = Σ (pillar_weight_p × pillar_score_p) / Σ pillar_weight_p     (available pillars only)
```

Round the composite to the nearest integer. **Never display decimals** — a 71.38 is false precision on anchor heuristics (analyst playbook: precision without accuracy is noise).

> **As implemented** (`scoring.score_company`, recorded 2026-08-30): **the second line holds and
> the first does not.** The composite is a genuine weighted sum — `sum(v["weight"] * v["score"])
> / total_w` at `scoring.py:442`, its denominator built on the line above, with the weights
> coming from `sector_weights.SECTOR_PROFILES[...]["weights"]`. The pillar score is not:
> `scoring.py:432`
> is `round(sum(scores) / len(scores))`, an unweighted mean over the metrics that scored.
> **There is no `metric_weight_i` anywhere in the engine** — `grep metric_weight backend/`
> returns nothing, and `SECTOR_PROFILES` carries only per-pillar `weights`, a `metrics`
> membership list, and `anchor_overrides` (which curve maps a value to a score, not how much
> that score counts). No structure exists that could make one metric outrank another inside a
> pillar.
>
> This is not a divergence the code drifted into; the mechanism was never built. It is
> recorded here rather than removed from the formula, because this file is a specification —
> restating the code's arithmetic as the design would erase the gap instead of naming it.
>
> **§3's four "weighted up" notes inherit the same gap** and are not separately annotated:
> `energy`'s FCF yield ("inside V"), `industrials`' interest coverage, `logistics`' asset
> turnover and FCF conversion ("in Q"), and `utilities`' dividend yield ("in V"). All four
> describe a metric weighted up *relative to its siblings in the same pillar*, and all four
> are scored on the same unweighted footing as every other metric there. `real_estate_reit`
> is **not** among them, though a first draft of this note said it was: its row drops metrics
> and names which ones make up V, which is membership rather than weighting — and membership
> *is* implemented, through `SECTOR_PROFILES[...]["metrics"]`.
>
> Closing this needs a mechanism before it needs a number: a weight per metric per profile,
> a renormalisation rule for the missing-data case §4.1 already specifies, and a re-bake of
> `golden_scores.json`. See TODOLIST.

### 4.2 Tier bands

| Score | Tier | Label | Reading |
|---|---|---|---|
| 80–100 | 1 | Strong | Fundamentals + momentum broadly aligned and healthy |
| 65–79 | 2 | Solid | Above average; check the weakest pillar |
| 50–64 | 3 | Mixed | Strengths offset by real weaknesses — pillar breakdown is the story |
| 35–49 | 4 | Weak | Multiple deteriorating pillars |
| 0–34 | 5 | Fragile | Broad weakness or distress signals |

Confidence badge from coverage: **HIGH ≥ 85%**, **MEDIUM 60–84%**, **LOW < 60%** (LOW: show score greyed, exclude from default ranking). PRE_PROFIT type: confidence capped at MEDIUM regardless of coverage (ref §7.1).

### 4.3 Output schema (API response)

```json
{
  "ticker": "AAPL",
  "as_of": "2026-07-31T14:02:11Z",
  "classification": "technology",
  "composite_score": 74,
  "tier": 2,
  "tier_label": "Solid",
  "confidence": "HIGH",
  "coverage_pct": 92,
  "pillars": {
    "valuation":  {"score": 48, "weight": 0.20, "metrics": {"earnings_yield_fwd": {"raw": 0.034, "score": 44}, "fcf_yield": {"raw": 0.031, "score": 51}, "ev_ebitda": {"raw": 24.1, "score": 35}}},
    "quality":    {"score": 93, "weight": 0.25, "metrics": {"...": "..."}},
    "health":     {"score": 81, "weight": 0.10, "metrics": {"...": "..."}},
    "growth":     {"score": 62, "weight": 0.30, "metrics": {"...": "..."}},
    "momentum":   {"score": 77, "weight": 0.15, "metrics": {"...": "..."}}
  },
  "flags": ["dupont_leverage_cap_applied"],
  "missing_metrics": ["peg_ratio"],
  "caveat": "This score is a snapshot of current fundamentals, valuation and price momentum against heuristic healthy ranges. It is NOT a prediction or a guarantee of future returns; it does not model catalysts, competitive shifts, or macro regime changes. Coverage and data quality limits apply. Decision support only — not financial advice."
}
```

The `caveat` string ships in every response and the frontend must render it (reference §7.4 items 1, 3, 5 are non-negotiable). The per-metric `raw` + `score` pairs are what make the number auditable — keep them.

### 4.4 LLM narrative (optional endpoint, on demand)

`POST /api/score/{ticker}/narrative` → feeds the *computed* score JSON above into qwen2.5 with a prompt of the form: "You are given a completed score card. Write 4–6 sentences explaining the strongest pillar, the weakest pillar, and what the flags mean. Do not compute or change any numbers. Do not state any figure not present in the input." Streamed to the UI; 30–60s on this CPU is acceptable for a single on-demand company view, and the score card is already on screen while it types.

---

## 5. Validation Plan

### 5.1 Determinism check (must pass, automated)
Score the same cached fundamentals dict twice in one process and across two processes → byte-identical JSON (excluding `as_of`). Add as a unit test. This is also the regression harness: snapshot the score JSON for 3 cached tickers; any code change that moves a score must be explainable.

### 5.2 Backtest-lite: golden-ten ordering plausibility
Score these ten on the same day and check the *ordering and tiering*, not exact values:

| Ticker | Type exercised | Plausibility expectation (2026 context) |
|---|---|---|
| MSFT | technology | Tier 1–2; Q and H near top of set |
| NVDA | technology | High Q/G, V should visibly drag (expensive) — if V scores > 60 the anchors are too loose |
| AAPL | technology | Tier 2-ish; Q high, G moderate |
| JPM | financials_bank | Bank path executes: no EV/EBITDA/current-ratio in output; Tier 1–2 |
| KO | consumer (staples) | Tier 2–3; H/Q solid, G low — dividend yield metric active |
| XOM | energy (cyclical) | V and H decent, G low; sanity: not Tier 1 purely off trailing cheapness |
| UNH | healthcare | Whatever the tier, pillar breakdown must match the known story of the period |
| PLD | real_estate_reit | REIT path: FFO-proxy + dividend metrics present, P/E absent |
| BA | industrials (stressed) | H pillar should be visibly weak — if H > 60, health anchors are broken |
| RIVN (or similar) | pre_profit_growth | EV/Sales-only V, runway in H, confidence ≤ MEDIUM, Tier 3–5 |

Acceptance: (a) no bankrupt-adjacent name outranks a mega-cap compounder; (b) each special-type pipeline (bank, REIT, pre-profit) emits the substituted metric set and omits the invalid ones; (c) the eyeball ordering of the ten offends no one who reads financial statements.

### 5.3 Sensitivity of the ranking to weights
Perturb every pillar weight ±20% (renormalized), re-rank the golden ten. If a name moves more than one tier, its score is weight-fragile — verify that's economically real (a genuinely mixed company should be weight-sensitive; MSFT should not be). Per the analyst rule: if the conclusion flips on a modest assumption change, say so — surface a `weight_stability` note if a company's tier changes under this perturbation.

### 5.4 Degenerate-input tests
Feed: all-None info dict (→ coverage 0%, no score, no crash); negative equity (→ D/E marked missing, renormalized); negative EPS + negative FCF (→ V scores near 0, not missing); absurd values (PE = 4,000 → winsorized). One parametrized pytest file.

### 5.5 Weak external cross-check (context only)
Correlate composite vs yfinance `recommendationMean` across ~30 tickers. Expect mild agreement (negative correlation, since 1=strong buy). Perfect agreement is NOT the goal — analyst consensus lags and herds (ref §5.6); use it only to catch sign errors (if your Tier 1s are consensus strong-sells across the board, investigate).

### 5.6 What this validation does NOT do
It does not prove predictive power. A proper backtest (score → forward 12M return, by tier, over years) needs point-in-time fundamentals that yfinance cannot provide (lookahead bias). Ship without it; state it in the docs; revisit when OpenBB + a point-in-time source exist.

---

## 6. Implementation Map (for the coding session that follows)

| Piece | Where | Size |
|---|---|---|
| `piecewise_score`, winsorize, `METRIC_ANCHORS` | `backend/scoring.py` | ~80 lines |
| Metric extraction (reuse `_latest`/`_series`/`ratio_analysis`/`dcf_valuation` from `financial_models.py`) | `backend/scoring.py` | ~100 lines |
| `SECTOR_WEIGHTS` + include/exclude/overrides + classifier (§7.1 rules) | `backend/sector_weights.py` (pure data + one function) | ~90 lines |
| Composite + coverage + tier + JSON assembly | `backend/scoring.py` | ~60 lines |
| API route `GET /api/score/{ticker}` (+ optional `/narrative`) | existing FastAPI app | ~30 lines |
| Tests (5.1, 5.4 + golden-ten script) | `backend/tests/test_scoring.py` | ~120 lines |

No new dependencies. The LLM path touches only the `/narrative` endpoint and the optional sentiment classifier — both fail soft.

---
*Version-control this document. The anchor table and the weight library are the assumptions of this system — every change to them must be logged with a rationale, exactly as the reference doc demands of model assumptions.*
