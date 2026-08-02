"""Financial model calculations (Tab 2 engine).

Implements the priority models from docs/financial-models-reference.md:
ratio analysis + DuPont, a 5-year FCFF DCF with sensitivity grid, and
market-multiples snapshot. All functions take the fundamentals dict
produced by data_provider.get_fundamentals so they stay provider-agnostic;
the one live market input is the risk-free rate used by WACC.
"""
from __future__ import annotations

from data_provider import risk_free_rate

# Assumption defaults (user-overridable via the API)
RISK_FREE_RATE = 0.043      # fallback only — WACC uses the live US 10Y when reachable
EQUITY_RISK_PREMIUM = 0.05
TERMINAL_GROWTH = 0.025
DEFAULT_TAX_RATE = 0.21
PROJECTION_YEARS = 5


def _latest(statement: dict, *row_names):
    """Most recent non-null value for any of the given row names."""
    for period in sorted(statement.keys(), reverse=True):
        rows = statement[period]
        for name in row_names:
            v = rows.get(name)
            if v is not None:
                return v
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


def _statement_fcf(cash_flow: dict) -> float | None:
    """Annual FCF from the newest period reporting both legs (CapEx is negative).

    Both legs must come from the same period — mixing this year's operating
    cash flow with last year's CapEx would silently distort the valuation.
    """
    for period in sorted(cash_flow.keys(), reverse=True):
        rows = cash_flow[period]
        ocf = rows.get("Operating Cash Flow")
        if ocf is None:
            ocf = rows.get("Cash Flow From Continuing Operating Activities")
        capex = rows.get("Capital Expenditure")
        if ocf is not None and capex is not None:
            return ocf + capex
    return None


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


def _wacc(info: dict, tax_rate: float) -> dict:
    beta = info.get("beta") or 1.0
    # HK issuers keep the USD 10Y: the HKD peg makes it an acceptable proxy
    rf = risk_free_rate(RISK_FREE_RATE)
    cost_of_equity = rf + beta * EQUITY_RISK_PREMIUM
    market_cap = info.get("marketCap") or 0
    total_debt = info.get("totalDebt") or 0
    cost_of_debt = rf + 0.015  # spread heuristic; refine with real credit data later
    total = market_cap + total_debt
    if total == 0:
        wacc = cost_of_equity
    else:
        wacc = (market_cap / total) * cost_of_equity + \
               (total_debt / total) * cost_of_debt * (1 - tax_rate)
    return {
        "risk_free_rate": round(rf, 4),
        "beta": beta,
        "cost_of_equity": round(cost_of_equity, 4),
        "cost_of_debt_after_tax": round(cost_of_debt * (1 - tax_rate), 4),
        "weight_equity": round(market_cap / total, 4) if total else 1.0,
        "wacc": round(wacc, 4),
    }


def dcf_valuation(f: dict, growth_rate: float | None = None,
                  terminal_growth: float = TERMINAL_GROWTH,
                  wacc_override: float | None = None,
                  tax_rate: float = DEFAULT_TAX_RATE) -> dict:
    info = f["info"]
    # Statement first: yfinance's info["freeCashflow"] is annual for some issuers
    # and a single quarter for others (MSFT reports ~0.24x the statement figure),
    # which silently rescales the entire valuation.
    fcf, fcf_source = _statement_fcf(f["cash_flow"]), "cash_flow_statement"
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

    wacc_parts = _wacc(info, tax_rate)
    wacc = wacc_override if wacc_override is not None else wacc_parts["wacc"]
    if wacc <= terminal_growth:
        return {"error": f"WACC ({wacc:.2%}) must exceed terminal growth ({terminal_growth:.2%})."}

    def enterprise_value(w: float, g_term: float) -> float:
        pv = 0.0
        cash_flow = fcf
        for year in range(1, PROJECTION_YEARS + 1):
            # fade projection growth linearly toward terminal growth
            g = growth_rate + (g_term - growth_rate) * (year - 1) / (PROJECTION_YEARS - 1)
            cash_flow *= (1 + g)
            pv += cash_flow / (1 + w) ** year
        terminal = cash_flow * (1 + g_term) / (w - g_term)
        return pv + terminal / (1 + w) ** PROJECTION_YEARS

    ev = enterprise_value(wacc, terminal_growth)
    net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    equity_value = ev - net_debt
    shares = info.get("sharesOutstanding")
    fair_value = equity_value / shares if shares else None
    price = info.get("currentPrice") or info.get("regularMarketPrice")

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

    return {
        "assumptions": {
            "base_fcf": fcf,
            "fcf_source": fcf_source,
            "growth_rate_year1": round(growth_rate, 4),
            "growth_source": growth_source,
            "terminal_growth": terminal_growth,
            "tax_rate": tax_rate,
            "projection_years": PROJECTION_YEARS,
            **wacc_parts,
            "wacc_used": round(wacc, 4),
        },
        "enterprise_value": round(ev),
        "net_debt": net_debt,
        "equity_value": round(equity_value),
        "fair_value_per_share": round(fair_value, 2) if fair_value else None,
        "current_price": price,
        "upside_pct": round((fair_value / price - 1) * 100, 1) if fair_value and price else None,
        "sensitivity": {
            "terminal_growth_cols": [round(terminal_growth + d, 4)
                                     for d in (-0.005, -0.0025, 0.0, 0.0025, 0.005)],
            "rows": sensitivity,
        },
    }


def revenue_trend(f: dict) -> list[dict]:
    return [{"period": p, "revenue": v}
            for p, v in _series(f["income_statement"], "Total Revenue")]


def full_analysis(f: dict) -> dict:
    return {
        "ticker": f["ticker"],
        "company": {k: f["info"].get(k) for k in
                    ["longName", "sector", "industry", "currency", "marketCap",
                     "targetMeanPrice", "recommendationKey", "numberOfAnalystOpinions"]},
        "ratios": ratio_analysis(f),
        "dcf": dcf_valuation(f),
        "revenue_trend": revenue_trend(f),
    }
