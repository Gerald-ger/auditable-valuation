"""Deterministic company scoring engine.

Implements docs/scoring-system-design.md: piecewise-linear metric scoring
against healthy-range anchors, sector-weighted pillars, coverage-aware
composite, and S/A/B/C/D tiers. The local LLM never touches these numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend import financial_models as fm
from backend import market_series
from backend import sector_weights
from backend import statements

# Anchor tables: ascending x, linear interpolation, clipped at the ends.
# Values grounded in financial-models-reference.md §4.1 / Appendix B.
# Non-monotonic lists deliberately penalize "too much of a good thing".
METRIC_ANCHORS = {
    # Valuation
    "earnings_yield_fwd": [(-0.05, 0), (0.00, 10), (0.03, 40), (0.05, 60), (0.08, 85), (0.12, 100)],
    "fcf_yield":          [(-0.05, 0), (0.00, 15), (0.02, 40), (0.05, 70), (0.08, 90), (0.12, 100)],
    "ev_ebitda":          [(4, 100), (7, 90), (10, 70), (14, 50), (20, 25), (30, 0)],
    "p_b":                [(0.6, 100), (1.0, 90), (1.5, 75), (2.5, 55), (4, 35), (8, 10)],
    "ev_sales":           [(1.5, 100), (3, 85), (6, 60), (10, 40), (15, 20), (25, 0)],
    "dcf_upside_pct":     [(-40, 0), (-15, 30), (0, 50), (15, 70), (40, 90), (80, 100)],
    "dividend_yield":     [(0.0, 20), (0.01, 40), (0.025, 65), (0.04, 85), (0.06, 100), (0.09, 70)],
    "ffo_yield":          [(0.0, 10), (0.03, 40), (0.05, 60), (0.07, 80), (0.10, 100)],
    # Quality
    "roe":                [(0.0, 10), (0.08, 40), (0.15, 70), (0.20, 85), (0.30, 100)],
    "roa":                [(0.0, 10), (0.005, 40), (0.01, 65), (0.015, 85), (0.025, 100)],
    "roic":               [(0.0, 10), (0.06, 35), (0.09, 55), (0.12, 75), (0.20, 95), (0.30, 100)],
    "operating_margin":   [(0.0, 10), (0.05, 35), (0.10, 55), (0.20, 80), (0.30, 100)],
    "gross_margin":       [(0.10, 10), (0.25, 35), (0.40, 60), (0.60, 85), (0.80, 100)],
    "fcf_conversion":     [(0.0, 0), (0.5, 30), (0.8, 60), (1.0, 85), (1.3, 100), (2.5, 80)],
    # Health
    "net_debt_ebitda":    [(0.0, 100), (1.5, 85), (3.0, 65), (4.0, 40), (5.0, 20), (6.0, 0)],
    "interest_coverage":  [(0.0, 0), (2.0, 25), (4.0, 60), (8.0, 85), (15.0, 100)],
    "current_ratio":      [(0.5, 10), (1.0, 50), (1.2, 75), (1.6, 100), (2.5, 90), (4.0, 60)],
    "debt_equity":        [(0.1, 100), (0.5, 90), (1.0, 70), (1.5, 50), (2.0, 30), (3.0, 10)],
    "cash_runway_q":      [(2, 0), (4, 30), (8, 60), (12, 80), (20, 100)],
    "equity_assets":      [(0.04, 10), (0.06, 40), (0.08, 65), (0.10, 85), (0.14, 100)],
    # Growth
    "revenue_growth":     [(-0.15, 0), (-0.05, 20), (0.0, 35), (0.05, 55), (0.12, 75), (0.25, 95), (0.50, 100)],
    "revenue_cagr_3y":    [(-0.10, 0), (0.0, 30), (0.05, 55), (0.10, 75), (0.20, 95), (0.35, 100)],
    "earnings_growth":    [(-0.30, 0), (-0.10, 20), (0.0, 40), (0.10, 65), (0.25, 85), (0.50, 100)],
    "pe_gap":             [(-0.20, 10), (0.0, 45), (0.10, 65), (0.25, 85), (0.50, 100)],
    # Momentum
    "price_vs_200dma":    [(-0.30, 5), (-0.10, 30), (0.0, 55), (0.10, 80), (0.25, 100), (0.60, 85)],
    "range_52w_pos":      [(0.0, 10), (0.3, 35), (0.5, 55), (0.8, 85), (1.0, 100)],
    "rel_52w_change":     [(-0.40, 5), (-0.15, 30), (0.0, 55), (0.15, 80), (0.40, 100)],
    # Reachable by no profile — `analyst_upside` is computed and displayed but
    # scored nowhere (see sector_weights.BASE_METRICS). Kept rather than deleted
    # for two reasons: the note recording *why* it was dropped cites this curve's
    # neutral point of 45 as its evidence, and `extract_metrics` still produces
    # the metric, so scoring it again — as target *revisions* in momentum, the
    # one form with documented information content — would need a curve, not a
    # rewrite. Do not read its presence as "this counts".
    "analyst_upside":     [(-0.20, 10), (0.0, 45), (0.10, 65), (0.25, 85), (0.50, 100)],
}

TIERS = [(80, "S", "Strong"), (65, "A", "Solid"), (50, "B", "Mixed"),
         (35, "C", "Weak"), (0, "D", "Fragile")]

CAVEAT = ("This score is a snapshot of current fundamentals, valuation and price "
          "momentum against heuristic healthy ranges. It is NOT a prediction or a "
          "guarantee of future returns; it does not model catalysts, competitive "
          "shifts, or macro regime changes. Coverage and data quality limits apply. "
          "Decision support only — not financial advice.")


def piecewise_score(value, anchors):
    if value is None:
        return None
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, s0), (x1, s1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            return s0 + (s1 - s0) * (value - x0) / (x1 - x0)
    return None


def _clamp(v, lo, hi):
    return None if v is None else max(lo, min(hi, v))


def extract_metrics(f: dict,
                    market_bars: tuple[list[dict], list[dict]] | None = None
                    ) -> tuple[dict, list[str]]:
    """Raw metric values from the fundamentals dict. None = unreported;
    bad values (negative earnings/FCF) are computed, not skipped."""
    info = f["info"]
    inc, bal, cf = f["income_statement"], f["balance_sheet"], f["cash_flow"]
    flags = []

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    mcap = info.get("marketCap")
    eps = info.get("forwardEps") or info.get("trailingEps")
    net_income = statements.latest(inc, "Net Income", "Net Income Common Stockholders")
    ebit = statements.latest(inc, "EBIT", "Operating Income")
    equity = statements.latest(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    assets = statements.latest(bal, "Total Assets")
    dep_amort = statements.latest(cf, "Depreciation And Amortization", "Depreciation Amortization Depletion")
    # Same source discipline as dcf_valuation: info["freeCashflow"] is a single
    # quarter for some issuers (measured 2026-08-06: MSFT 0.244x, GOOGL 0.309x of
    # the annual statement) and annual for others. That silently rescaled fcf_yield
    # and made fcf_conversion mix a quarter of FCF over a full year of net income.
    statement_fcf = statements.statement_fcf(cf)
    fcf_period = statement_fcf[0] if statement_fcf else None
    fcf = statement_fcf[1] if statement_fcf else None
    if fcf is None:
        fcf = info.get("freeCashflow")
        if fcf is not None:
            flags.append("fcf_from_info_unverified_period")
    total_debt, total_cash = info.get("totalDebt"), info.get("totalCash")

    def div(a, b):
        return a / b if a is not None and b not in (None, 0) else None

    # Yields divide a statement figure by market capitalisation, and for an
    # issuer that reports in one currency and trades in another those are
    # different units — 0700.HK reports CNY and trades HKD. `fx` converts the
    # numerator; it is 1.0 for every single-currency issuer. None means the two
    # differ and no rate was available, in which case the yields are dropped
    # rather than computed on a mixed basis (`fcf_yield` read 0.0439 unconverted
    # against 0.0478 correct, scoring 63.9 against 67.8).
    fx, fx_mismatch = fm.statement_to_market_fx(
        info.get("currency"), info.get("financialCurrency"))
    if fx_mismatch and fx is None:
        flags.append("fx_rate_unavailable")

    def to_market(value):
        """A statement figure expressed in the currency market cap is quoted in."""
        return value * fx if value is not None and fx is not None else None

    m = {}
    # eps and price are both trading-currency, so this one needs no conversion
    m["earnings_yield_fwd"] = _clamp(div(eps, price), -0.5, 0.5)
    m["fcf_yield"] = _clamp(div(to_market(fcf), mcap), -0.5, 0.5)
    # A negative EV/EBITDA is not a cheap one. EBITDA <= 0 flips the ratio's
    # sign and the ascending anchors would clip it to the *best* score — the
    # same reason net_debt_ebitda below guards its denominator. Negative EV the
    # anchors cannot express either; cheapness still reaches the pillar through
    # earnings_yield_fwd, fcf_yield and dcf_upside_pct.
    # Restated onto one currency before scoring: the vendor divides a
    # trading-currency EV by reporting-currency EBITDA, which scored a
    # CNY-reporting HK issuer as dearer than it is (0700.HK 15.705 -> 14.277,
    # worth 6 points on this metric). See fm.ev_multiple_one_currency.
    ev_ebitda, ev_sales = fm.ev_multiples_for(info)
    ebitda = info.get("ebitda")
    if ev_ebitda is not None and (ev_ebitda <= 0 or (ebitda is not None and ebitda <= 0)):
        ev_ebitda = None
    m["ev_ebitda"] = _clamp(ev_ebitda, 0, 1000)
    # Negative book value is a broken balance sheet, not cheapness — clamping
    # it to 0 handed it the top anchor score.
    pb = info.get("priceToBook")
    m["p_b"] = _clamp(pb, 0, 1000) if pb is not None and pb > 0 else None
    m["ev_sales"] = _clamp(ev_sales, 0, 1000)
    # A non-payer is a zero yield, not an unreported one. yfinance omits
    # dividendYield entirely rather than sending 0, and None means "unreported"
    # to piecewise_score — so the metric was dropped from the pillar average
    # instead of scoring its 20-point floor, which *raised* the average it left.
    # Measured on JPM 2026-08-10, changing nothing else: paying 1.68% scored
    # valuation 58, cutting to 0.10% scored 51, and cutting to zero scored 60 —
    # a suspended dividend came out ahead of a token one and recovered the whole
    # composite. That is the loudest signal the profiles scoring this metric
    # have (staples, utilities, REITs, banks, insurers), so it cannot read as
    # missing data. The residual risk is the reverse case — a real payer whose
    # yield yfinance fails to report now scores 20 rather than being skipped —
    # which score_company surfaces as `dividend_yield_assumed_zero`.
    m["dividend_yield"] = (info.get("dividendYield") or 0.0) / 100  # yfinance gives percent
    # NOT NAREIT FFO. Proper FFO is net income + real-estate depreciation
    # - gains on property sales + impairments. yfinance exposes no gain-on-sale-
    # of-real-estate row at all (the O fixture reports only "Gain On Sale Of
    # Security"), so the adjusted figure cannot be built from this source. This
    # is net income plus total D&A, a proxy that runs high for REITs that sell
    # property. Cards that actually score it carry `ffo_yield_is_proxy`; see
    # score_company. Measured on O, the candidate adjustments score 69-77
    # against 71 here — ~0.5 composite points, not a tier.
    m["ffo_yield"] = _clamp(
        div(to_market((net_income or 0) + (dep_amort or 0))
            if net_income is not None else None, mcap), -0.5, 0.5)

    # ROE is undefined on negative equity — and a negative-equity issuer with a
    # negative net income reports a spuriously *positive* ROE. Same trigger as
    # the debt_equity guard below, applied for the same reason.
    roe = info.get("returnOnEquity")
    if equity is not None and equity <= 0:
        roe = None
        flags.append("roe_skipped_negative_equity")
    m["roe"] = _clamp(roe, -2, 2)
    m["roa"] = _clamp(info.get("returnOnAssets"), -1, 1)
    invested = None
    if equity is not None:
        invested = equity + (total_debt or 0) - (total_cash or 0)
    # statutory rate for the listing's jurisdiction, not a flat US 21%
    nopat = ebit * (1 - fm.tax_rate_for(info)) if ebit is not None else None
    m["roic"] = _clamp(div(nopat, invested) if invested and invested > 0 else None, -1, 1)
    m["operating_margin"] = _clamp(info.get("operatingMargins"), -2, 2)
    m["gross_margin"] = _clamp(info.get("grossMargins"), -2, 2)
    # FCF / net income is only a conversion rate when both legs cover the same
    # annual period. The net income used here is therefore pinned to the period
    # statements.statement_fcf resolved, not the newest one available; when FCF fell back
    # to info["freeCashflow"] there is no verified period and the metric is
    # dropped rather than computed on a mixed basis.
    conversion_ni = statements.value_at(inc, fcf_period, "Net Income",
                                 "Net Income Common Stockholders") if fcf_period else None
    if fcf_period and conversion_ni is None:
        flags.append("fcf_conversion_period_mismatch")
    m["fcf_conversion"] = _clamp(
        div(fcf, conversion_ni) if conversion_ni and conversion_ni > 0 else None, -5, 5)

    net_debt = (total_debt or 0) - (total_cash or 0)
    # `ebitda` resolved above alongside the ev_ebitda guard
    m["net_debt_ebitda"] = _clamp(max(net_debt, 0) / ebitda if ebitda and ebitda > 0 else None, 0, 50)
    # Both legs from one period. Pairing the newest EBIT with the newest
    # interest independently made AAPL's coverage FY2025 operating income over
    # FY2023 interest — 33.8x, a ratio of two different years. `ebit` above
    # stays unpinned on purpose: NOPAT wants the most recent operating income,
    # and it is divided by a balance-sheet figure, not another income row.
    coverage, _ = statements.interest_coverage(inc)
    m["interest_coverage"] = _clamp(coverage, -50, 200)
    m["current_ratio"] = _clamp(info.get("currentRatio"), 0, 20)
    de = div(total_debt, equity) if equity and equity > 0 else None
    if de is None and equity is not None and equity <= 0:
        flags.append("debt_equity_skipped_negative_equity")
    m["debt_equity"] = _clamp(de, 0, 50)
    # Runway has to burn what the company actually burns. Dividing cash by the
    # operating outflow alone ignored capital expenditure, which for a pre-profit
    # manufacturer is most of the burn: RIVN's 2025 operating outflow is 0.78bn
    # against 1.71bn of capex, so runway read **27.3 quarters** — past the top
    # anchor at 20, scoring 100 — where the free-cash-flow burn gives **8.5
    # quarters** and 63. Overstated by 3.2x, on the single metric the pre-profit
    # Health pillar leans hardest on.
    #
    # The rate is `OCF + CapEx` from `statements.statement_fcf`, so both legs share a
    # period by construction — the discipline `fcf_conversion` already inherits.
    #
    # Trigger and rate deliberately ask different questions, and the split is
    # not arbitrary: **capex is discretionary in a way that operating burn is
    # not.** A company whose operations fund themselves can stop building and
    # survive; one whose operations do not cannot stop operating. So "is there a
    # survival question at all" keys on operating outflow, while "how fast is
    # cash actually leaving, at today's plans" includes the capex. Widening the
    # trigger to free-cash-flow-negative would hand a runway to a company that
    # is only burning because it chose to expand.
    # Capex is never positive, so `ocf < 0` already implies the burn is negative.
    period_ocf = statements.value_at(cf, fcf_period, "Operating Cash Flow",
                              "Cash Flow From Continuing Operating Activities") \
        if fcf_period else None
    burn = statement_fcf[1] if statement_fcf else None
    if period_ocf is not None and period_ocf < 0 and burn and total_cash:
        m["cash_runway_q"] = _clamp(total_cash / (abs(burn) / 4), 0, 100)
    else:
        m["cash_runway_q"] = None
    m["equity_assets"] = _clamp(div(equity, assets), -1, 1)

    m["revenue_growth"] = _clamp(info.get("revenueGrowth"), -1, 3)
    rev = statements.series(inc, "Total Revenue")
    if len(rev) >= 3 and rev[0][1] and rev[0][1] > 0:
        years = len(rev) - 1
        m["revenue_cagr_3y"] = _clamp((rev[-1][1] / rev[0][1]) ** (1 / years) - 1, -1, 3)
    else:
        m["revenue_cagr_3y"] = None
    m["earnings_growth"] = _clamp(info.get("earningsGrowth"), -2, 5)
    tpe, fpe = info.get("trailingPE"), info.get("forwardPE")
    m["pe_gap"] = _clamp(tpe / fpe - 1 if tpe and fpe and tpe > 0 and fpe > 0 else None, -1, 3)

    two_hundred = info.get("twoHundredDayAverage")
    m["price_vs_200dma"] = _clamp(price / two_hundred - 1
                                  if price and two_hundred else None, -1, 3)
    lo, hi = info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")
    m["range_52w_pos"] = (price - lo) / (hi - lo) if price and lo and hi and hi > lo else None
    # Relative strength against the index the company actually trades on,
    # measured from closes rather than read from the vendor's scalars.
    #
    # Two separate reasons, both measured 2026-08-14. The benchmark was wrong:
    # `SandP52WeekChange` is the S&P for every ticker, so 0700.HK was scored
    # against an index it does not trade on. And the obvious fix — read
    # `52WeekChange` off `^HSI` — is not available, because that field is
    # unusable: `^GSPC` reports it in percent (20.918) while `^HSI` reports it
    # in decimal (0.500), and the HSI value matches neither its own price
    # history (-1.41%) nor any unit reading of it. Trusting it would have
    # scored Tencent at -63.7% relative instead of -23.8%, making the defect
    # worse. The per-stock scalar is no better: 0700.HK's own `52WeekChange`
    # says -13.7% where its closes say -24.2%.
    #
    # Falls back to the old pair when no bars are supplied, so a history outage
    # degrades this metric rather than dropping the momentum pillar below its
    # availability threshold.
    stock_bars, index_bars = market_bars or (None, None)
    rel = None
    if stock_bars and index_bars:
        own = market_series.change_over(stock_bars)
        bench = market_series.change_over(index_bars)
        if own is not None and bench is not None:
            rel = own - bench
    if rel is None:
        w52, sp52 = info.get("52WeekChange"), info.get("SandP52WeekChange")
        rel = w52 - sp52 if w52 is not None and sp52 is not None else None
        if rel is not None:
            flags.append("rel_52w_change_from_vendor_scalars")
    m["rel_52w_change"] = _clamp(rel, -3, 3)
    n_analysts = info.get("numberOfAnalystOpinions") or 0
    tgt = info.get("targetMeanPrice")
    m["analyst_upside"] = _clamp(tgt / price - 1 if tgt and price and n_analysts >= 4 else None, -1, 3)

    return m, flags


def score_company(f: dict, dcf: dict | None = None,
                  market_bars: tuple[list[dict], list[dict]] | None = None) -> dict:
    info = f["info"]
    # The profile decides which metrics are scored and how they are weighted, so
    # the classifier must not read info["freeCashflow"] — see classify's docstring.
    statement_fcf = statements.statement_fcf(f["cash_flow"])
    classification = sector_weights.classify(
        info, statement_fcf[1] if statement_fcf else None)
    profile = sector_weights.get_profile(classification)
    raw, flags = extract_metrics(f, market_bars)

    active = [x for lst in profile["metrics"].values() for x in lst]
    # DCF upside only where the model is applicable (profile includes it)
    if "dcf_upside_pct" in active:
        # The bars go into this fallback too. Callers that already ran the DCF
        # pass it in (main.py does, with the same series), but a caller relying
        # on this branch would otherwise score a valuation built on a *different*
        # beta from the one the Models tab shows for the same company.
        dcf = dcf if dcf is not None else fm.dcf_valuation(f, market_bars=market_bars)
        raw["dcf_upside_pct"] = None if dcf.get("error") else dcf.get("upside_pct")
    if "ffo_yield" in active and raw.get("ffo_yield") is not None:
        flags.append("ffo_yield_is_proxy")
    # Only where the metric counts: every non-payer would otherwise carry this,
    # including profiles that never score a dividend. Same rule as ffo_yield above.
    if "dividend_yield" in active and info.get("dividendYield") is None:
        flags.append("dividend_yield_assumed_zero")

    ratios = fm.ratio_analysis(f)
    equity_multiplier = ratios["dupont"]["equity_multiplier"]

    pillar_names = {"V": "valuation", "Q": "quality", "H": "health",
                    "G": "growth", "M": "momentum"}
    pillars, missing = {}, []
    for pillar, metric_list in profile["metrics"].items():
        detail, scores = {}, []
        for metric in metric_list:
            anchors = profile["anchor_overrides"].get(metric, METRIC_ANCHORS[metric])
            s = piecewise_score(raw.get(metric), anchors)
            if s is None:
                missing.append(metric)
            else:
                # DuPont guard: leverage-manufactured ROE is not quality —
                # except where the leverage is the business model rather than a
                # financing choice (see sector_weights.LEVERAGE_IS_STRUCTURAL)
                if metric == "roe" and classification not in sector_weights.LEVERAGE_IS_STRUCTURAL \
                        and equity_multiplier and equity_multiplier > 4 and s > 70:
                    s = 70
                    if "dupont_leverage_cap_applied" not in flags:
                        flags.append("dupont_leverage_cap_applied")
                scores.append(s)
                detail[metric] = {"raw": round(raw[metric], 4), "score": round(s)}
        avail_frac = len(scores) / len(metric_list) if metric_list else 0
        pillars[pillar_names[pillar]] = {
            "score": round(sum(scores) / len(scores)) if scores else None,
            "weight": profile["weights"][pillar],
            "available_fraction": round(avail_frac, 2),
            "insufficient": avail_frac < 0.4,
            "metrics": detail,
        }

    # composite over sufficient pillars, weights renormalized
    usable = {k: v for k, v in pillars.items() if v["score"] is not None and not v["insufficient"]}
    total_w = sum(v["weight"] for v in usable.values())
    composite = round(sum(v["weight"] * v["score"] for v in usable.values()) / total_w) \
        if total_w > 0 else None

    coverage = round(100 * sum(v["weight"] * v["available_fraction"] for v in pillars.values()))
    confidence = "HIGH" if coverage >= 85 else "MEDIUM" if coverage >= 60 else "LOW"
    if profile["confidence_cap"] == "MEDIUM" and confidence == "HIGH":
        confidence = "MEDIUM"

    tier, tier_label = None, None
    if composite is not None:
        for floor, t, label in TIERS:
            if composite >= floor:
                tier, tier_label = t, label
                break

    return {
        "ticker": f["ticker"],
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "classification": classification,
        # Whether a discounted-cash-flow valuation means anything for this
        # company type, decided by the profile rather than by whether the model
        # happened to return a number. Read from `sector_weights.dcf_applies`
        # rather than restated here, because the Scorecard's football field asks
        # the same question and the two tabs must not be able to answer it
        # differently for one company.
        "dcf_applicable": sector_weights.dcf_applies(classification),
        "composite_score": composite,
        "tier": tier,
        "tier_label": tier_label,
        "confidence": confidence,
        "coverage_pct": coverage,
        "pillars": pillars,
        # Shown, never scored — see the note above sector_weights.BASE_METRICS.
        # A target price is a twelve-month forecast of where a stock will trade,
        # not an estimate of what the business is worth, and published targets
        # sit above price on average. It stays on screen because a reader wants
        # to see it; it stays out of every pillar because it must not quietly
        # move a grade. `upside` is None below four analysts, the same gate
        # `extract_metrics` applies and the same one the football field uses.
        "analyst_context": {
            "target_mean": info.get("targetMeanPrice"),
            "analysts": info.get("numberOfAnalystOpinions"),
            "upside": raw.get("analyst_upside"),
            "recommendation": info.get("recommendationKey"),
        },
        "flags": flags,
        "missing_metrics": missing,
        "caveat": CAVEAT,
    }
