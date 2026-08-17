"""Accounting-quality and distress checks — computed, displayed, never scored.

Why these four: they are the highest-evidence, lowest-cost gaps between this app
and the paid tools (GuruFocus ships all of them), and every input is already in
the statements `get_fundamentals` fetches, so they cost no extra request.

Why display-only: the composite already blends ~40 anchor curves that have never
been validated against forward returns (docs/scoring-system-design.md §5.6).
Folding four more unvalidated curves into it would move every score without
adding evidence. These are reported beside the score, with their published
thresholds, so the reader applies them rather than the engine burying them in an
average. Wiring them into pillars is a separate decision, taken on evidence.

Every check states its own applicability. Altman's Z is calibrated on
manufacturers and is meaningless for banks and insurers, whose balance sheets
carry no working-capital or sales concept — those return `applicable: False`
rather than a number that looks computed.
"""
from __future__ import annotations

from backend import financial_models as fm

# Altman (1968), original public-company Z. Zones are Altman's own.
Z_SAFE, Z_DISTRESS = 2.99, 1.81
# Piotroski (2000): nine binary tests; >=7 strong, <=2 weak.
F_STRONG, F_WEAK = 7, 2
# Sloan (1996): the accrual anomaly. Positive = earnings running ahead of cash.
ACCRUAL_HIGH = 0.10

# Classifications where a check's inputs do not exist or its calibration does
# not apply. A bank has no current ratio and no cost of goods sold.
NOT_FOR_FINANCIALS = ("financials_bank", "financials_insurance")

# Altman's Z additionally does not transfer to asset-heavy, structurally levered,
# low-turnover businesses. Its sales/assets and working-capital terms both read
# the normal operating shape of a REIT or a regulated utility as distress:
# measured 2026-08-07 the O fixture scores 1.08, i.e. "distress", for a REIT that
# carries an investment-grade rating and covers its interest 2.0x. Reporting
# "not applicable" is right; reporting 1.08 would be a false signal with a
# decimal point on it. Altman's four-variable Z'' exists for non-manufacturers
# and is NOT implemented here — that is why these return n/a rather than a
# rescaled number.
NOT_FOR_ASSET_HEAVY = ("real_estate_reit", "utilities")


def _periods(statement: dict) -> list[str]:
    """Newest first."""
    return sorted(statement.keys(), reverse=True)


def _at(statement: dict, period: str | None, *names):
    if not period:
        return None
    rows = statement.get(period) or {}
    for name in names:
        if rows.get(name) is not None:
            return rows[name]
    return None


def _pair(statement: dict, *names) -> tuple[float | None, float | None]:
    """(newest, prior) for the first row name present — both from their own period.

    Returns (None, None) rather than reaching further back: a "change since last
    year" computed across a three-year gap is not the quantity it claims to be.
    """
    periods = _periods(statement)
    if len(periods) < 2:
        return (_at(statement, periods[0] if periods else None, *names), None)
    return _at(statement, periods[0], *names), _at(statement, periods[1], *names)


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def altman_z(f: dict, classification: str) -> dict:
    """Bankruptcy-risk composite. Higher is safer."""
    if classification in NOT_FOR_FINANCIALS:
        return {"applicable": False,
                "note": "Z is calibrated on manufacturers; a bank has no "
                        "working-capital or sales term."}
    if classification in NOT_FOR_ASSET_HEAVY:
        return {"applicable": False,
                "note": "Z reads the normal shape of an asset-heavy, levered, "
                        "low-turnover business as distress. Altman's Z'' variant "
                        "covers these and is not implemented."}
    bal, inc = f["balance_sheet"], f["income_statement"]
    period = _periods(bal)[0] if bal else None
    assets = _at(bal, period, "Total Assets")
    if not assets:
        return {"applicable": False, "note": "No total assets reported."}

    ca = _at(bal, period, "Current Assets")
    cl = _at(bal, period, "Current Liabilities")
    working_capital = ca - cl if ca is not None and cl is not None else None
    retained = _at(bal, period, "Retained Earnings")
    liabilities = _at(bal, period, "Total Liabilities Net Minority Interest")
    ebit = _at(inc, _periods(inc)[0] if inc else None, "EBIT", "Operating Income")
    revenue = _at(inc, _periods(inc)[0] if inc else None, "Total Revenue")

    # Four of Altman's five terms divide one statement figure by another and are
    # unit-free. `equity_liabilities` is the exception: market cap is quoted in
    # the trading currency while liabilities come from the statements, so for an
    # issuer reporting in a different currency the term is a mixed ratio and its
    # 0.6 weight carries the error straight into Z.
    market_cap = f["info"].get("marketCap")
    fx, fx_mismatch = fm.statement_to_market_fx(
        f["info"].get("currency"), f["info"].get("financialCurrency"))
    if fx_mismatch:
        if fx is None:
            return {"applicable": False,
                    "note": "Statements and shares are in different currencies "
                            "and no exchange rate was available, so the "
                            "market-value term cannot be put on one basis."}
        market_cap = market_cap / fx if market_cap is not None else None

    terms = {
        "working_capital_assets": (1.2, _div(working_capital, assets)),
        "retained_earnings_assets": (1.4, _div(retained, assets)),
        "ebit_assets": (3.3, _div(ebit, assets)),
        "equity_liabilities": (0.6, _div(market_cap, liabilities)),
        "sales_assets": (1.0, _div(revenue, assets)),
    }
    missing = [k for k, (_, v) in terms.items() if v is None]
    if missing:
        return {"applicable": False,
                "note": f"Missing inputs: {', '.join(sorted(missing))}."}

    z = sum(weight * value for weight, value in terms.values())
    return {
        "applicable": True,
        "value": round(z, 2),
        "band": "safe" if z > Z_SAFE else "distress" if z < Z_DISTRESS else "grey",
        "thresholds": {"safe_above": Z_SAFE, "distress_below": Z_DISTRESS},
        "terms": {k: round(v, 4) for k, (_, v) in terms.items()},
    }


def piotroski_f(f: dict, classification: str) -> dict:
    """Nine binary fundamental-improvement tests. Higher is better."""
    if classification in NOT_FOR_FINANCIALS:
        return {"applicable": False,
                "note": "Four of the nine tests need current ratio and gross "
                        "margin, which a bank does not report."}
    inc, bal, cf = f["income_statement"], f["balance_sheet"], f["cash_flow"]
    if len(_periods(bal)) < 2 or len(_periods(inc)) < 2:
        return {"applicable": False,
                "note": "Needs two annual periods; fewer were reported."}

    ni_now, ni_prior = _pair(inc, "Net Income", "Net Income Common Stockholders")
    assets_now, assets_prior = _pair(bal, "Total Assets")
    cfo_now, cfo_prior = _pair(cf, "Operating Cash Flow",
                               "Cash Flow From Continuing Operating Activities")
    ltd_now, ltd_prior = _pair(bal, "Long Term Debt")
    ca_now, ca_prior = _pair(bal, "Current Assets")
    cl_now, cl_prior = _pair(bal, "Current Liabilities")
    shares_now, shares_prior = _pair(inc, "Diluted Average Shares", "Basic Average Shares")
    gp_now, gp_prior = _pair(inc, "Gross Profit")
    rev_now, rev_prior = _pair(inc, "Total Revenue")

    roa_now, roa_prior = _div(ni_now, assets_now), _div(ni_prior, assets_prior)
    cr_now, cr_prior = _div(ca_now, cl_now), _div(ca_prior, cl_prior)

    def gt(a, b):
        """None when either side is unreported — an unknown test is not a failed one."""
        return None if a is None or b is None else a > b

    tests = {
        "roa_positive": gt(roa_now, 0),
        "cfo_positive": gt(cfo_now, 0),
        "roa_improving": gt(roa_now, roa_prior),
        "accruals_clean": gt(_div(cfo_now, assets_now), roa_now),
        "leverage_falling": gt(_div(ltd_prior, assets_prior), _div(ltd_now, assets_now)),
        "liquidity_improving": gt(cr_now, cr_prior),
        "no_dilution": gt(shares_prior, shares_now - 1e-9) if shares_now is not None
                       and shares_prior is not None else None,
        "margin_improving": gt(_div(gp_now, rev_now), _div(gp_prior, rev_prior)),
        "turnover_improving": gt(_div(rev_now, assets_now), _div(rev_prior, assets_prior)),
    }
    scored = {k: v for k, v in tests.items() if v is not None}
    if len(scored) < 5:
        return {"applicable": False,
                "note": f"Only {len(scored)} of 9 tests computable."}

    passed = sum(1 for v in scored.values() if v)
    return {
        "applicable": True,
        "value": passed,
        "out_of": len(scored),
        # a 6/7 is not a 6/9 — the band reads against what was computable
        "band": "strong" if passed >= F_STRONG else "weak" if passed <= F_WEAK else "middling",
        "thresholds": {"strong_at_or_above": F_STRONG, "weak_at_or_below": F_WEAK},
        "tests": tests,
    }


def accrual_ratio(f: dict) -> dict:
    """(Net income - operating cash flow) / average assets. Lower is better.

    Sloan's accrual anomaly: the wider earnings run ahead of cash, the more of
    the profit is accounting estimate rather than collected money, and the more
    likely it reverses. This is the balance-sheet-light form; both legs are
    pinned to their own period and the denominator averages the two years'
    assets so a large acquisition does not read as an accrual.
    """
    inc, bal, cf = f["income_statement"], f["balance_sheet"], f["cash_flow"]
    period = _periods(cf)[0] if cf else None
    cfo = _at(cf, period, "Operating Cash Flow",
              "Cash Flow From Continuing Operating Activities")
    # net income from the cash-flow statement's own period, not the newest
    ni = _at(inc, period, "Net Income", "Net Income Common Stockholders")
    if ni is None or cfo is None:
        return {"applicable": False,
                "note": "Needs net income and operating cash flow in one period."}
    assets_now, assets_prior = _pair(bal, "Total Assets")
    avg_assets = (assets_now + assets_prior) / 2 if assets_now and assets_prior else assets_now
    ratio = _div(ni - cfo, avg_assets)
    if ratio is None:
        return {"applicable": False, "note": "No total assets reported."}
    return {
        "applicable": True,
        "value": round(ratio, 4),
        "band": "high" if ratio > ACCRUAL_HIGH else "low",
        "thresholds": {"high_above": ACCRUAL_HIGH},
    }


def net_share_issuance(f: dict) -> dict:
    """Year-on-year change in diluted share count. Negative = buyback.

    Net issuance is one of the more durable return predictors, and it is the
    part of "EPS growth" that is not operating performance — a company can grow
    EPS with a flat business by retiring stock, and dilute a good business into
    a flat EPS. Neither is visible in any other metric on the card.
    """
    now, prior = _pair(f["income_statement"], "Diluted Average Shares",
                       "Basic Average Shares")
    change = _div(now - prior, prior) if now is not None and prior else None
    if change is None:
        return {"applicable": False, "note": "Needs two periods of share count."}
    return {
        "applicable": True,
        "value": round(change, 4),
        "band": "buyback" if change < -0.005 else "dilution" if change > 0.005 else "flat",
        "shares_now": now,
        "shares_prior": prior,
    }


def forensic_checks(f: dict, classification: str) -> dict:
    """All four checks. Display-only — nothing here feeds the composite score."""
    return {
        "altman_z": altman_z(f, classification),
        "piotroski_f": piotroski_f(f, classification),
        "accrual_ratio": accrual_ratio(f),
        "net_share_issuance": net_share_issuance(f),
        "note": "Computed from the same statements as the score, but deliberately "
                "not scored into it — published thresholds are shown so you apply "
                "them yourself. See docs/scoring-system-design.md §5.6.",
    }
