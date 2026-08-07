"""Deterministic company scoring engine.

Implements docs/scoring-system-design.md: piecewise-linear metric scoring
against healthy-range anchors, sector-weighted pillars, coverage-aware
composite, and S/A/B/C/D tiers. The local LLM never touches these numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

import financial_models as fm
import sector_weights

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


def extract_metrics(f: dict) -> tuple[dict, list[str]]:
    """Raw metric values from the fundamentals dict. None = unreported;
    bad values (negative earnings/FCF) are computed, not skipped."""
    info = f["info"]
    inc, bal, cf = f["income_statement"], f["balance_sheet"], f["cash_flow"]
    flags = []

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    mcap = info.get("marketCap")
    eps = info.get("forwardEps") or info.get("trailingEps")
    net_income = fm._latest(inc, "Net Income", "Net Income Common Stockholders")
    ebit = fm._latest(inc, "EBIT", "Operating Income")
    interest = fm._latest(inc, "Interest Expense")
    equity = fm._latest(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    assets = fm._latest(bal, "Total Assets")
    dep_amort = fm._latest(cf, "Depreciation And Amortization", "Depreciation Amortization Depletion")
    # Same source discipline as dcf_valuation: info["freeCashflow"] is a single
    # quarter for some issuers (measured 2026-08-06: MSFT 0.244x, GOOGL 0.309x of
    # the annual statement) and annual for others. That silently rescaled fcf_yield
    # and made fcf_conversion mix a quarter of FCF over a full year of net income.
    statement_fcf = fm._statement_fcf(cf)
    fcf_period = statement_fcf[0] if statement_fcf else None
    fcf = statement_fcf[1] if statement_fcf else None
    if fcf is None:
        fcf = info.get("freeCashflow")
        if fcf is not None:
            flags.append("fcf_from_info_unverified_period")
    total_debt, total_cash = info.get("totalDebt"), info.get("totalCash")

    def div(a, b):
        return a / b if a is not None and b not in (None, 0) else None

    m = {}
    m["earnings_yield_fwd"] = _clamp(div(eps, price), -0.5, 0.5)
    m["fcf_yield"] = _clamp(div(fcf, mcap), -0.5, 0.5)
    m["ev_ebitda"] = _clamp(info.get("enterpriseToEbitda"), -100, 1000)
    m["p_b"] = _clamp(info.get("priceToBook"), 0, 1000)
    m["ev_sales"] = _clamp(info.get("enterpriseToRevenue"), 0, 1000)
    m["dividend_yield"] = div(info.get("dividendYield"), 100)  # yfinance gives percent
    # NOT NAREIT FFO. Proper FFO is net income + real-estate depreciation
    # - gains on property sales + impairments. yfinance exposes no gain-on-sale-
    # of-real-estate row at all (the O fixture reports only "Gain On Sale Of
    # Security"), so the adjusted figure cannot be built from this source. This
    # is net income plus total D&A, a proxy that runs high for REITs that sell
    # property. Cards that actually score it carry `ffo_yield_is_proxy`; see
    # score_company. Measured on O, the candidate adjustments score 69-77
    # against 71 here — ~0.5 composite points, not a tier.
    m["ffo_yield"] = _clamp(div((net_income or 0) + (dep_amort or 0), mcap)
                            if net_income is not None else None, -0.5, 0.5)

    m["roe"] = _clamp(info.get("returnOnEquity"), -2, 2)
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
    # _statement_fcf resolved, not the newest one available; when FCF fell back
    # to info["freeCashflow"] there is no verified period and the metric is
    # dropped rather than computed on a mixed basis.
    conversion_ni = fm._value_at(inc, fcf_period, "Net Income",
                                 "Net Income Common Stockholders") if fcf_period else None
    if fcf_period and conversion_ni is None:
        flags.append("fcf_conversion_period_mismatch")
    m["fcf_conversion"] = _clamp(
        div(fcf, conversion_ni) if conversion_ni and conversion_ni > 0 else None, -5, 5)

    net_debt = (total_debt or 0) - (total_cash or 0)
    ebitda = info.get("ebitda")
    m["net_debt_ebitda"] = _clamp(max(net_debt, 0) / ebitda if ebitda and ebitda > 0 else None, 0, 50)
    m["interest_coverage"] = _clamp(div(ebit, interest), -50, 200)
    m["current_ratio"] = _clamp(info.get("currentRatio"), 0, 20)
    de = div(total_debt, equity) if equity and equity > 0 else None
    if de is None and equity is not None and equity <= 0:
        flags.append("debt_equity_skipped_negative_equity")
    m["debt_equity"] = _clamp(de, 0, 50)
    ocf = fm._latest(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    if ocf is not None and ocf < 0 and total_cash:
        m["cash_runway_q"] = _clamp(total_cash / (abs(ocf) / 4), 0, 100)
    else:
        m["cash_runway_q"] = None
    m["equity_assets"] = _clamp(div(equity, assets), -1, 1)

    m["revenue_growth"] = _clamp(info.get("revenueGrowth"), -1, 3)
    rev = fm._series(inc, "Total Revenue")
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
    w52, sp52 = info.get("52WeekChange"), info.get("SandP52WeekChange")
    m["rel_52w_change"] = _clamp(w52 - sp52 if w52 is not None and sp52 is not None else None, -3, 3)
    n_analysts = info.get("numberOfAnalystOpinions") or 0
    tgt = info.get("targetMeanPrice")
    m["analyst_upside"] = _clamp(tgt / price - 1 if tgt and price and n_analysts >= 4 else None, -1, 3)

    return m, flags


def score_company(f: dict, dcf: dict | None = None) -> dict:
    info = f["info"]
    # The profile decides which metrics are scored and how they are weighted, so
    # the classifier must not read info["freeCashflow"] — see classify's docstring.
    statement_fcf = fm._statement_fcf(f["cash_flow"])
    classification = sector_weights.classify(
        info, statement_fcf[1] if statement_fcf else None)
    profile = sector_weights.get_profile(classification)
    raw, flags = extract_metrics(f)

    active = [x for lst in profile["metrics"].values() for x in lst]
    # DCF upside only where the model is applicable (profile includes it)
    if "dcf_upside_pct" in active:
        dcf = dcf if dcf is not None else fm.dcf_valuation(f)
        raw["dcf_upside_pct"] = None if dcf.get("error") else dcf.get("upside_pct")
    if "ffo_yield" in active and raw.get("ffo_yield") is not None:
        flags.append("ffo_yield_is_proxy")

    equity_multiplier = None
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
                # DuPont guard: leverage-manufactured ROE is not quality
                if metric == "roe" and equity_multiplier and equity_multiplier > 4 and s > 70:
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
        "composite_score": composite,
        "tier": tier,
        "tier_label": tier_label,
        "confidence": confidence,
        "coverage_pct": coverage,
        "pillars": pillars,
        "flags": flags,
        "missing_metrics": missing,
        "caveat": CAVEAT,
    }
