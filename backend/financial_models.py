"""Financial model calculations (Tab 2 engine).

Implements the priority models from docs/financial-models-reference.md:
ratio analysis + DuPont, a two-stage FCFF DCF with sensitivity grid, and
market-multiples snapshot. All functions take the fundamentals dict
produced by data_provider.get_fundamentals so they stay provider-agnostic;
the one live market input is the risk-free rate used by WACC.

`dcf_valuation` is a **pure function** of its arguments. Anything needing the
network — the peer betas used when a reported beta is implausible — is resolved
by the caller and injected, so the model stays offline-testable and one page
load does not fan out into peer fetches it did not ask for.
"""
from __future__ import annotations

from statistics import median

from data_provider import risk_free_rate

# Assumption defaults (user-overridable via the API)
RISK_FREE_RATE = 0.043      # fallback only — WACC uses the live US 10Y when reachable
EQUITY_RISK_PREMIUM = 0.05
TERMINAL_GROWTH = 0.025
DEFAULT_TAX_RATE = 0.21

# Two-stage projection: an explicit high-growth stage, then a linear fade to the
# terminal rate. A single 5-year fade compressed the whole growth phase of a
# durable compounder into five years and drove structurally large negative
# upside on mega-caps; the fade stage now carries that transition instead.
STAGE1_YEARS = 5            # explicit forecast at the starting growth rate
STAGE2_YEARS = 5            # linear fade from the starting rate to terminal
PROJECTION_YEARS = STAGE1_YEARS + STAGE2_YEARS

# Statutory profits/corporate tax by listing currency. yfinance does not forward
# a country field through get_fundamentals' whitelist, and currency is a reliable
# proxy for the listing's tax regime for the markets this app covers.
TAX_RATE_BY_CURRENCY = {"HKD": 0.165, "USD": 0.21}

# A reported beta outside this band is not credible for a listed operating
# company — yfinance returned 0.173 for XOM, which alone swung its DCF upside by
# ~79 points. Outside the band we substitute peer evidence rather than trust it.
BETA_MIN, BETA_MAX = 0.3, 2.5
BETA_FALLBACK = 1.0
# A median of one observation is not a median. Measured 2026-08-06, yfinance's
# betas are broken sector-wide for energy — XOM's peers return CVX 0.488,
# COP 0.123, SHEL -0.218, BP -0.212, so only one survives the credibility band
# and it is still implausibly low for an oil major. Requiring two keeps the
# substitution honest and lets those cases fall through to the neutral default.
MIN_PEER_BETAS = 2

# Synthetic credit spread over the risk-free rate, keyed on interest coverage
# (EBIT / interest expense). Replaces a flat +1.5% that charged a net-cash
# company and a highly levered REIT exactly the same cost of debt.
# Ascending coverage thresholds; the first row whose floor is met wins.
CREDIT_SPREAD_LADDER = [
    (12.5, 0.006),
    (8.5, 0.0085),
    (6.5, 0.011),
    (4.5, 0.014),
    (3.0, 0.020),
    (2.0, 0.030),
    (1.5, 0.045),
    (0.0, 0.070),
]
DEFAULT_CREDIT_SPREAD = 0.015  # when coverage cannot be computed


def _latest(statement: dict, *row_names):
    """Most recent non-null value for any of the given row names."""
    for period in sorted(statement.keys(), reverse=True):
        rows = statement[period]
        for name in row_names:
            v = rows.get(name)
            if v is not None:
                return v
    return None


def _value_at(statement: dict, period: str, *row_names):
    """Value for the given period only — used where two figures must share a period."""
    rows = statement.get(period)
    if not rows:
        return None
    for name in row_names:
        if rows.get(name) is not None:
            return rows[name]
    return None


def _series(statement: dict, *row_names) -> list[tuple[str, float]]:
    """(period, value) oldest-first for the first row name that has data."""
    out = []
    for period in sorted(statement.keys()):
        rows = statement[period]
        for name in row_names:
            if rows.get(name) is not None:
                out.append((period, rows[name]))
                break
    return out


def _statement_fcf(cash_flow: dict) -> tuple[str, float] | None:
    """(period, FCF) from the newest period reporting both legs (CapEx is negative).

    Returns the period as well as the value so callers that divide FCF by another
    statement figure can demand the same period. Mixing this year's operating
    cash flow with last year's CapEx — or this year's FCF with last year's net
    income — would silently distort the result.
    """
    for period in sorted(cash_flow.keys(), reverse=True):
        rows = cash_flow[period]
        ocf = rows.get("Operating Cash Flow")
        if ocf is None:
            ocf = rows.get("Cash Flow From Continuing Operating Activities")
        capex = rows.get("Capital Expenditure")
        if ocf is not None and capex is not None:
            return period, ocf + capex
    return None


def tax_rate_for(info: dict) -> float:
    """Statutory tax rate for the listing's jurisdiction, by currency."""
    return TAX_RATE_BY_CURRENCY.get(info.get("currency"), DEFAULT_TAX_RATE)


def resolve_beta(info: dict, peer_betas: list[float] | None = None) -> tuple[float, str]:
    """(beta, source). Reported beta wins when it is credible; peers break the tie.

    peer_betas is injected by the caller — this function never fetches.
    """
    raw = info.get("beta")
    if raw is not None and BETA_MIN <= raw <= BETA_MAX:
        return raw, "reported"
    usable = [b for b in (peer_betas or []) if b is not None and BETA_MIN <= b <= BETA_MAX]
    if len(usable) >= MIN_PEER_BETAS:
        return round(median(usable), 4), "peer_median"
    return BETA_FALLBACK, "default"


def _credit_spread(f: dict) -> tuple[float, float | None]:
    """(spread, interest_coverage) — cost of debt should reflect leverage."""
    inc = f["income_statement"]
    ebit = _latest(inc, "EBIT", "Operating Income")
    interest = _latest(inc, "Interest Expense")
    if ebit is None or not interest:
        return DEFAULT_CREDIT_SPREAD, None
    coverage = ebit / abs(interest)
    for floor, spread in CREDIT_SPREAD_LADDER:
        if coverage >= floor:
            return spread, round(coverage, 2)
    return CREDIT_SPREAD_LADDER[-1][1], round(coverage, 2)


def ratio_analysis(f: dict) -> dict:
    info = f["info"]
    inc, bal = f["income_statement"], f["balance_sheet"]

    revenue = _latest(inc, "Total Revenue")
    net_income = _latest(inc, "Net Income", "Net Income Common Stockholders")
    ebit = _latest(inc, "EBIT", "Operating Income")
    interest = _latest(inc, "Interest Expense")
    equity = _latest(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    assets = _latest(bal, "Total Assets")

    def div(a, b):
        return round(a / b, 4) if a is not None and b not in (None, 0) else None

    dupont = {
        "net_margin": div(net_income, revenue),
        "asset_turnover": div(revenue, assets),
        "equity_multiplier": div(assets, equity),
    }
    dupont["roe_composed"] = (
        round(dupont["net_margin"] * dupont["asset_turnover"] * dupont["equity_multiplier"], 4)
        if all(v is not None for v in dupont.values()) else None
    )

    return {
        "liquidity": {
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
        },
        "solvency": {
            "debt_to_equity": div(info.get("totalDebt"), equity),
            "interest_coverage": div(ebit, interest),
            "net_debt": (info.get("totalDebt") - info.get("totalCash"))
                        if info.get("totalDebt") is not None and info.get("totalCash") is not None else None,
        },
        "profitability": {
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "net_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
        },
        "market": {
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "peg_ratio": info.get("pegRatio"),
            # yfinance returns dividendYield already in percent (0.32 == 0.32%)
            "dividend_yield": info.get("dividendYield") / 100
                              if info.get("dividendYield") is not None else None,
        },
        "dupont": dupont,
        "growth": {
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
        },
    }


def _wacc(f: dict, tax_rate: float, peer_betas: list[float] | None = None) -> dict:
    info = f["info"]
    beta, beta_source = resolve_beta(info, peer_betas)
    # HK issuers keep the USD 10Y: the HKD peg makes it an acceptable proxy
    rf = risk_free_rate(RISK_FREE_RATE)
    cost_of_equity = rf + beta * EQUITY_RISK_PREMIUM
    market_cap = info.get("marketCap") or 0
    total_debt = info.get("totalDebt") or 0
    spread, coverage = _credit_spread(f)
    cost_of_debt = rf + spread
    total = market_cap + total_debt
    if total == 0:
        wacc = cost_of_equity
    else:
        wacc = (market_cap / total) * cost_of_equity + \
               (total_debt / total) * cost_of_debt * (1 - tax_rate)
    return {
        "risk_free_rate": round(rf, 4),
        "beta": beta,
        "beta_source": beta_source,
        "beta_reported": info.get("beta"),
        "cost_of_equity": round(cost_of_equity, 4),
        "credit_spread": spread,
        "interest_coverage": coverage,
        "cost_of_debt_after_tax": round(cost_of_debt * (1 - tax_rate), 4),
        "weight_equity": round(market_cap / total, 4) if total else 1.0,
        "wacc": round(wacc, 4),
    }


def _growth_path(growth_rate: float, terminal_growth: float) -> list[float]:
    """Growth applied in each projection year: flat through stage 1, then fading."""
    path = [growth_rate] * STAGE1_YEARS
    for year in range(1, STAGE2_YEARS + 1):
        path.append(growth_rate + (terminal_growth - growth_rate) * year / STAGE2_YEARS)
    return path


def dcf_valuation(f: dict, growth_rate: float | None = None,
                  terminal_growth: float = TERMINAL_GROWTH,
                  wacc_override: float | None = None,
                  tax_rate: float | None = None,
                  peer_betas: list[float] | None = None) -> dict:
    info = f["info"]
    if tax_rate is None:
        tax_rate = tax_rate_for(info)
    # Statement first: yfinance's info["freeCashflow"] is annual for some issuers
    # and a single quarter for others (MSFT reports ~0.24x the statement figure),
    # which silently rescales the entire valuation.
    statement = _statement_fcf(f["cash_flow"])
    fcf_source = "cash_flow_statement"
    fcf = statement[1] if statement else None
    if fcf is None:
        fcf, fcf_source = info.get("freeCashflow"), "info_freecashflow"
    if not fcf or fcf <= 0:
        return {"error": "No positive free cash flow available — DCF not applicable "
                         "(see reference doc: use relative valuation instead)."}

    growth_source = "user"
    if growth_rate is None:
        # prefer analyst forward consensus over trailing growth
        fwd = (f.get("estimates") or {}).get("revenue_growth_fwd")
        rg = fwd if fwd is not None else info.get("revenueGrowth")
        growth_source = "analyst_consensus_fwd" if fwd is not None else "trailing_revenue_growth"
        growth_rate = max(min(rg if rg is not None else 0.05, 0.25), 0.0)

    wacc_parts = _wacc(f, tax_rate, peer_betas)
    wacc = wacc_override if wacc_override is not None else wacc_parts["wacc"]
    if wacc <= terminal_growth:
        return {"error": f"WACC ({wacc:.2%}) must exceed terminal growth ({terminal_growth:.2%})."}

    def project(w: float, g_term: float) -> tuple[float, float, float]:
        """(PV of explicit years, PV of terminal value, final-year growth factor)."""
        pv = 0.0
        cash_flow = fcf
        compounded = 1.0
        for year, g in enumerate(_growth_path(growth_rate, g_term), start=1):
            cash_flow *= (1 + g)
            compounded *= (1 + g)
            pv += cash_flow / (1 + w) ** year
        terminal = cash_flow * (1 + g_term) / (w - g_term)
        return pv, terminal / (1 + w) ** PROJECTION_YEARS, compounded

    def enterprise_value(w: float, g_term: float) -> float:
        pv, terminal_pv, _ = project(w, g_term)
        return pv + terminal_pv

    explicit_pv, terminal_pv, growth_factor = project(wacc, terminal_growth)
    ev = explicit_pv + terminal_pv
    net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    equity_value = ev - net_debt
    shares = info.get("sharesOutstanding")
    fair_value = equity_value / shares if shares else None
    price = info.get("currentPrice") or info.get("regularMarketPrice")

    # Cross-check: what exit multiple does the perpetuity terminal value imply?
    # A perpetuity that only works by exiting far above today's trading multiple
    # is assuming multiple expansion, which is a modelling choice, not a result.
    # EBITDA is grown on the same path as FCF — an approximation, stated as one.
    ebitda = info.get("ebitda")
    implied_exit_multiple = None
    if ebitda and ebitda > 0:
        terminal_ev_undiscounted = terminal_pv * (1 + wacc) ** PROJECTION_YEARS
        implied_exit_multiple = round(terminal_ev_undiscounted / (ebitda * growth_factor), 1)

    sensitivity = []
    for dw in (-0.01, -0.005, 0.0, 0.005, 0.01):
        row = {"wacc": round(wacc + dw, 4), "values": []}
        for dg in (-0.005, -0.0025, 0.0, 0.0025, 0.005):
            w, g = wacc + dw, terminal_growth + dg
            if w <= g or not shares:
                row["values"].append(None)
            else:
                row["values"].append(round((enterprise_value(w, g) - net_debt) / shares, 2))
        sensitivity.append(row)

    terminal_share = round(terminal_pv / ev, 4) if ev else None

    return {
        "assumptions": {
            "base_fcf": fcf,
            "fcf_source": fcf_source,
            "fcf_period": statement[0] if statement else None,
            "growth_rate_year1": round(growth_rate, 4),
            "growth_source": growth_source,
            "terminal_growth": terminal_growth,
            "tax_rate": tax_rate,
            "projection_years": PROJECTION_YEARS,
            "stage1_years": STAGE1_YEARS,
            "stage2_years": STAGE2_YEARS,
            **wacc_parts,
            "wacc_used": round(wacc, 4),
        },
        "enterprise_value": round(ev),
        "net_debt": net_debt,
        "equity_value": round(equity_value),
        "fair_value_per_share": round(fair_value, 2) if fair_value else None,
        "current_price": price,
        "upside_pct": round((fair_value / price - 1) * 100, 1) if fair_value and price else None,
        "diagnostics": {
            # >75% is the conventional warning line: above it the valuation is
            # driven by the terminal assumption, not by the explicit forecast.
            "terminal_value_share": terminal_share,
            "terminal_value_high": terminal_share is not None and terminal_share > 0.75,
            "implied_exit_ev_ebitda": implied_exit_multiple,
            "current_ev_ebitda": info.get("enterpriseToEbitda"),
        },
        "sensitivity": {
            "terminal_growth_cols": [round(terminal_growth + d, 4)
                                     for d in (-0.005, -0.0025, 0.0, 0.0025, 0.005)],
            "rows": sensitivity,
        },
    }


def revenue_trend(f: dict) -> list[dict]:
    return [{"period": p, "revenue": v}
            for p, v in _series(f["income_statement"], "Total Revenue")]


def full_analysis(f: dict, peer_betas: list[float] | None = None) -> dict:
    return {
        "ticker": f["ticker"],
        "company": {k: f["info"].get(k) for k in
                    ["longName", "sector", "industry", "currency", "marketCap",
                     "targetMeanPrice", "recommendationKey", "numberOfAnalystOpinions"]},
        "ratios": ratio_analysis(f),
        "dcf": dcf_valuation(f, peer_betas=peer_betas),
        "revenue_trend": revenue_trend(f),
    }
