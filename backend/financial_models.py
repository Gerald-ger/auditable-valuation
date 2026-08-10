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

from data_provider import fx_rate, risk_free_rate

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


def paired_latest(statement: dict, names_a: tuple, names_b: tuple):
    """(period, a, b) from the newest period reporting **both**, else None.

    Two independent `_latest` calls will happily pair this year's numerator with
    a years-old denominator, because each walks back until it finds anything.
    Measured on the AAPL fixture 2026-08-10: `_latest` for EBIT resolves
    2025-09-30 while `_latest` for Interest Expense resolves 2023-09-30 — yfinance
    stopped reporting the row — so the interest coverage on screen was FY2025
    operating income over FY2023 interest, a ratio of two different businesses.

    This is the same discipline `_statement_fcf` enforces by returning its period
    and `fcf_conversion` inherits from it: a ratio is only a ratio when both legs
    describe one period. A stale-but-consistent answer beats a fresh-looking
    mixed one, and the period is returned so callers can say which year it is.
    """
    for period in sorted(statement.keys(), reverse=True):
        a = _value_at(statement, period, *names_a)
        b = _value_at(statement, period, *names_b)
        if a is not None and b is not None:
            return period, a, b
    return None


EBIT_ROWS = ("EBIT", "Operating Income")
INTEREST_ROWS = ("Interest Expense",)


def interest_coverage(income_statement: dict):
    """(coverage, period) — EBIT over interest expense, both from one period."""
    pair = paired_latest(income_statement, EBIT_ROWS, INTEREST_ROWS)
    if pair is None:
        return None, None
    period, ebit, interest = pair
    if not interest:
        return None, period
    return ebit / abs(interest), period


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
    """(period, **levered** FCF) from the newest period reporting both legs.

    CapEx is negative, so this is `CFO - CapEx`. Under US GAAP interest paid sits
    inside operating cash flow, which makes this a levered measure — closer to
    free cash flow to equity before net borrowing than to FCFF. That is the right
    quantity for `scoring.fcf_yield` (divided by market cap) and
    `scoring.fcf_conversion` (divided by net income), both of which are after
    interest. It is **not** the right quantity to discount at WACC:
    `dcf_valuation` adds interest back through `_fcff_interest_addback` instead.
    Do not "fix" this function — three of its four callers want it levered.

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


def _fcff_interest_addback(cash_flow: dict, period: str | None,
                           tax_rate: float) -> tuple[float, str]:
    """(after-tax interest to add back, basis) turning levered FCF into FCFF.

    `_statement_fcf` is levered where interest paid runs through operating
    activities, so discounting it at WACC *and* subtracting net debt would charge
    the debt twice. The add-back is `Interest x (1 - Tc)`.

    Whether it applies at all is **read from the statement, not assumed**. US
    GAAP requires interest paid to be disclosed as supplemental data alongside an
    operating-activities classification; IFRS permits classifying it in
    financing, in which case operating cash flow is *already* unlevered and
    adding interest back would overstate FCFF rather than correct it. Measured
    2026-08-09 across the fixtures: 0700.HK reports `Interest Paid Cff` in all
    four captured periods (and `Interest Received Cfi`, so its interest income is
    outside operating too), while every US filer reports `Interest Paid
    Supplemental Data`. Keying on the row that is actually present means a new
    IFRS listing is handled correctly without anyone having to know its GAAP.

    The cash figure is used rather than the income statement's accrual, because
    the quantity being adjusted is cash. The two diverge when interest is
    capitalised — XOM's accrual is 603M against 1,752M paid, a factor of 2.9.

    Interest *income* is deliberately not netted off: on a cash basis US filers
    disclose no matching "interest received" row, so netting would mean adding a
    cash figure and subtracting an accrual one. The consequence is that cash is
    valued twice for a net-cash issuer — once through the `EV - net_debt` bridge
    and once through the perpetual interest it earns inside operating cash flow.
    Measured, that is worth about +3% of FCF on MSFT and AAPL.

    Returns 0.0 with a stated reason whenever the adjustment cannot be justified,
    so an unverifiable case is left alone rather than guessed at.
    """
    if period is None:
        return 0.0, "no_statement_fcf"
    rows = cash_flow.get(period) or {}
    if rows.get("Interest Paid Cff") is not None:
        return 0.0, "not_required_interest_in_financing"
    cash_interest = rows.get("Interest Paid Supplemental Data")
    if cash_interest is not None:
        # Disclosed as an outflow; sign convention varies, magnitude does not.
        return abs(cash_interest) * (1 - tax_rate), "cash_interest_paid"
    return 0.0, "unverified_interest_classification"


def tax_rate_for(info: dict) -> float:
    """Statutory tax rate for the listing's jurisdiction, by currency."""
    return TAX_RATE_BY_CURRENCY.get(info.get("currency"), DEFAULT_TAX_RATE)


def statement_to_market_fx(trading_currency, reporting_currency):
    """(rate, mismatch) taking a statement figure into the trading currency.

    Statements are denominated in `financialCurrency` and the shares trade in
    `currency`, and for a China-domiciled Hong Kong listing those differ — 0700.HK
    reports CNY and trades HKD. Measured live 2026-08-10 against the quarterly
    statements, the split inside yfinance's `info` is:

        reporting currency   totalDebt, totalCash, totalRevenue, ebitda,
                             freeCashflow, operatingCashflow  (9988.HK matches
                             its quarterly balance sheet at 1.0000 and 0.9998)
        trading currency     currentPrice, marketCap, bookValue, trailingEps,
                             forwardEps  (0700.HK's book value and EPS both sit
                             1.12-1.13x their statement equivalents against a
                             CNYHKD spot of 1.1627)

    So a DCF built from statement cash flows and bridged with `totalDebt` lands
    in the reporting currency, while the price it is compared against is in the
    trading one. Unconverted, 0700.HK read +30.5% upside where the FX-correct
    figure is around +42%.

    `mismatch` is True whenever the two currencies genuinely differ, so callers
    can tell "no conversion needed" (rate 1.0) from "conversion needed but
    unavailable" (rate None) — those must not behave the same.
    """
    if not trading_currency or not reporting_currency:
        return 1.0, False
    if trading_currency == reporting_currency:
        return 1.0, False
    return fx_rate(reporting_currency, trading_currency), True


def _to_trading(info: dict):
    """statement_to_market_fx for a whole `info` dict."""
    return statement_to_market_fx(info.get("currency"), info.get("financialCurrency"))


def _debt_to_equity(debt, market_cap, fx: float | None = 1.0) -> float | None:
    """Market-value D/E. Zero debt is a real answer; missing debt is not.

    `debt` arrives in the reporting currency and `market_cap` in the trading one,
    so `fx` converts the numerator before the ratio is taken. It is 1.0 for every
    single-currency issuer, and None when the two differ and no rate was
    available — in which case the ratio is not computed rather than mixed.
    """
    if debt is None or not market_cap or market_cap <= 0 or fx is None:
        return None
    return max(debt, 0.0) * fx / market_cap


def resolve_beta(info: dict, peers: list[dict] | None = None,
                 tax_rate: float = DEFAULT_TAX_RATE) -> tuple[float, str]:
    """(beta, source). Reported beta wins when it is credible; peers break the tie.

    `peers` is injected by the caller — this function never fetches. Each entry
    is a peer snapshot: `beta`, `market_cap`, `total_debt`.

    When a peer's leverage is known, its beta is **unlevered before the median
    and re-levered to the target's own capital structure** (reference doc
    §1.1.2):

        Bu_i = Bl_i / (1 + (1 - Tc) * (D/E)_i)
        Bl   = median(Bu) * (1 + (1 - Tc) * (D/E)_target)

    A levered peer beta carries that peer's balance sheet, not the target's, so
    substituting a raw peer median imported the peers' leverage along with their
    business risk. Unlevering strips the financing effect out, leaving asset risk
    that is genuinely comparable, and re-levering puts the target's own leverage
    back on. Tc is the target's statutory rate for every peer — a simplification
    that holds for a domestic peer set and is wrong for a cross-border one.

    Degrades in order: re-levered peer median -> raw levered peer median (when
    leverage is unknown for too many peers) -> neutral 1.0. The result is held
    inside the same credibility band applied to a reported beta, so a heavily
    levered target cannot re-lever its way to an absurd number.
    """
    raw = info.get("beta")
    if raw is not None and BETA_MIN <= raw <= BETA_MAX:
        return raw, "reported"

    credible = [p for p in (peers or [])
                if p.get("beta") is not None and BETA_MIN <= p["beta"] <= BETA_MAX]

    target_fx, _ = _to_trading(info)
    target_de = _debt_to_equity(info.get("totalDebt"), info.get("marketCap"), target_fx)
    if target_de is not None:
        unlevered = []
        for p in credible:
            # each peer carries its own currency pair — an HK peer set can mix
            # HKD-reporting and CNY-reporting names
            peer_fx, _ = statement_to_market_fx(p.get("currency"),
                                                p.get("financial_currency"))
            de = _debt_to_equity(p.get("total_debt"), p.get("market_cap"), peer_fx)
            if de is not None:
                unlevered.append(p["beta"] / (1 + (1 - tax_rate) * de))
        if len(unlevered) >= MIN_PEER_BETAS:
            relevered = median(unlevered) * (1 + (1 - tax_rate) * target_de)
            return round(min(max(relevered, BETA_MIN), BETA_MAX), 4), "peer_median_relevered"

    if len(credible) >= MIN_PEER_BETAS:
        return round(median([p["beta"] for p in credible]), 4), "peer_median"
    return BETA_FALLBACK, "default"


def _credit_spread(f: dict) -> tuple[float, float | None, str | None]:
    """(spread, interest_coverage, coverage_period) — cost of debt reflects leverage.

    The period comes back so the audit row can say which year the coverage that
    set this spread was measured in; see `paired_latest` for why it is one year
    rather than the newest of each leg.
    """
    coverage, period = interest_coverage(f["income_statement"])
    if coverage is None:
        return DEFAULT_CREDIT_SPREAD, None, period
    for floor, spread in CREDIT_SPREAD_LADDER:
        if coverage >= floor:
            return spread, round(coverage, 2), period
    return CREDIT_SPREAD_LADDER[-1][1], round(coverage, 2), period


def ratio_analysis(f: dict) -> dict:
    info = f["info"]
    inc, bal = f["income_statement"], f["balance_sheet"]

    revenue = _latest(inc, "Total Revenue")
    net_income = _latest(inc, "Net Income", "Net Income Common Stockholders")
    equity = _latest(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    assets = _latest(bal, "Total Assets")

    def div(a, b):
        return round(a / b, 4) if a is not None and b not in (None, 0) else None

    # both legs from one period — see paired_latest
    coverage, coverage_period = interest_coverage(inc)

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
            "interest_coverage": round(coverage, 4) if coverage is not None else None,
            "interest_coverage_period": coverage_period,
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


def _wacc(f: dict, tax_rate: float, peers: list[dict] | None = None) -> dict:
    info = f["info"]
    beta, beta_source = resolve_beta(info, peers, tax_rate)
    # HK issuers keep the USD 10Y: the HKD peg makes it an acceptable proxy
    rf = risk_free_rate(RISK_FREE_RATE)
    cost_of_equity = rf + beta * EQUITY_RISK_PREMIUM
    market_cap = info.get("marketCap") or 0
    # the capital-structure weights compare a trading-currency market cap with a
    # reporting-currency debt balance, so the debt leg is converted first
    fx, _ = _to_trading(info)
    total_debt = (info.get("totalDebt") or 0) * (fx if fx is not None else 1.0)
    spread, coverage, coverage_period = _credit_spread(f)
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
        "interest_coverage_period": coverage_period,
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
                  peers: list[dict] | None = None) -> dict:
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
    # Levered -> unlevered. Gate on the adjusted figure, since that is what gets
    # discounted; a company only positive before the add-back is still a DCF.
    interest_addback, fcff_basis = _fcff_interest_addback(
        f["cash_flow"], statement[0] if statement else None, tax_rate)
    if fcf is not None:
        fcf += interest_addback
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

    wacc_parts = _wacc(f, tax_rate, peers)
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
    # Missing is not zero. An unreported totalDebt makes the bridge read as a
    # debt-free company and lifts fair value with nothing on screen to say why —
    # simulated on AAPL 2026-08-10, dropping totalDebt moved fair value 143.99 ->
    # 147.41 and net debt +21.9bn -> -62.4bn, silently. `ratio_analysis` already
    # returns None for the same input. The DCF keeps computing, because refusing
    # to value a company over one absent field is worse, but it names the leg it
    # had to assume so the reader can discount the answer accordingly.
    total_debt, total_cash = info.get("totalDebt"), info.get("totalCash")
    net_debt = (total_debt or 0) - (total_cash or 0)
    net_debt_assumed = [name for name, value in
                        (("total_debt", total_debt), ("total_cash", total_cash))
                        if value is None]
    equity_value = ev - net_debt
    shares = info.get("sharesOutstanding")
    price = info.get("currentPrice") or info.get("regularMarketPrice")

    # Everything computed above is in the *reporting* currency: the cash flows
    # come from the statements and net debt from totalDebt/totalCash, which
    # follow them. The price does not. `conv` is applied at the output boundary
    # only — the ratios below (terminal share, implied exit multiple) divide two
    # reporting-currency figures and are unit-free already, so converting them
    # would break what conversion is meant to fix.
    fx, fx_mismatch = _to_trading(info)
    fx_basis = ("single_currency" if not fx_mismatch
                else "converted" if fx is not None else "rate_unavailable")
    conv = fx if fx is not None else 1.0
    fair_value = equity_value * conv / shares if shares else None

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
                row["values"].append(
                    round((enterprise_value(w, g) - net_debt) * conv / shares, 2))
        sensitivity.append(row)

    terminal_share = round(terminal_pv / ev, 4) if ev else None

    return {
        "assumptions": {
            "base_fcf": fcf,
            "fcf_source": fcf_source,
            "fcf_period": statement[0] if statement else None,
            # 0.0 with a basis of anything but "cash_interest_paid" means the
            # figure above is still levered — see _fcff_interest_addback.
            "fcf_interest_addback": round(interest_addback),
            "fcff_basis": fcff_basis,
            "growth_rate_year1": round(growth_rate, 4),
            "growth_source": growth_source,
            "terminal_growth": terminal_growth,
            "tax_rate": tax_rate,
            "projection_years": PROJECTION_YEARS,
            "stage1_years": STAGE1_YEARS,
            "stage2_years": STAGE2_YEARS,
            **wacc_parts,
            "wacc_used": round(wacc, 4),
            # every figure below is quoted in `currency`; `fx_basis` says whether
            # that took a conversion, and `reporting_currency` names what the
            # statements were denominated in before it
            "currency": info.get("currency"),
            "reporting_currency": info.get("financialCurrency"),
            "fx_basis": fx_basis,
            "fx_rate_used": round(conv, 6) if fx_mismatch and fx is not None else None,
        },
        "enterprise_value": round(ev * conv),
        "net_debt": net_debt * conv,
        "equity_value": round(equity_value * conv),
        "fair_value_per_share": round(fair_value, 2) if fair_value else None,
        "current_price": price,
        # Suppressed when the statements and the shares are in different
        # currencies and no rate could be fetched: comparing a reporting-currency
        # fair value against a trading-currency price is the defect this whole
        # boundary exists to remove, and printing it anyway would restore it.
        "upside_pct": round((fair_value / price - 1) * 100, 1)
                      if fair_value and price and fx_basis != "rate_unavailable" else None,
        "diagnostics": {
            # >75% is the conventional warning line: above it the valuation is
            # driven by the terminal assumption, not by the explicit forecast.
            "terminal_value_share": terminal_share,
            "terminal_value_high": terminal_share is not None and terminal_share > 0.75,
            "implied_exit_ev_ebitda": implied_exit_multiple,
            "current_ev_ebitda": info.get("enterpriseToEbitda"),
            # empty is the healthy case: both legs of the bridge were reported
            "net_debt_assumed_zero": net_debt_assumed,
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


def full_analysis(f: dict, peers: list[dict] | None = None) -> dict:
    return {
        "ticker": f["ticker"],
        "company": {k: f["info"].get(k) for k in
                    ["longName", "sector", "industry", "currency", "marketCap",
                     "targetMeanPrice", "recommendationKey", "numberOfAnalystOpinions"]},
        "ratios": ratio_analysis(f),
        "dcf": dcf_valuation(f, peers=peers),
        "revenue_trend": revenue_trend(f),
    }
