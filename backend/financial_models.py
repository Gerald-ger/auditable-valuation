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

import json
from pathlib import Path
from statistics import median

from data_provider import fx_rate, risk_free_rate

# Assumption defaults (user-overridable via the API)
RISK_FREE_RATE = 0.043      # fallback only — WACC uses the live US 10Y when reachable
# Fallback only, and no longer the number a valuation normally uses: a per-market
# premium is read from market_risk_premiums.json (see equity_risk_premium_for).
# This value is what a market with no entry, or a missing reference file, falls
# back to — the same shape as RISK_FREE_RATE above backstopping the Fed feed.
EQUITY_RISK_PREMIUM = 0.05
TERMINAL_GROWTH = 0.025
DEFAULT_TAX_RATE = 0.21

# Long-run nominal GDP growth (~2% real + ~2% inflation), the line the
# market-implied terminal growth is read against — reference doc §1.1.4: the
# growth implied by an exit multiple should be below GDP growth, because nothing
# outgrows the economy forever. A fixed constant in the same spirit as the
# equity risk premium above, and the same approximation: one number for the US
# and Hong Kong both. It never enters a valuation; it only decides whether a
# diagnostic is flagged.
NOMINAL_GDP_GROWTH = 0.04

# Two-stage projection: an explicit stage at the forecast rate, then a linear
# fade to the terminal rate. The explicit stage matches the horizon of the input
# that feeds it.
#
# The growth figure is a **one-year** consensus — yfinance's `+1y` row is next
# fiscal year against the current one. Holding it flat for five years invented
# four years nobody forecast, and for a fast grower that is not a rounding
# error: measured 2026-08-13, AMD's 72.1% consensus compounded over five flat
# years multiplies free cash flow **15.1x** before any fade begins, which is why
# its fair value ran from -81.4% (capped at 25%) to +33.6% (uncapped). One year
# at the forecast rate then a linear fade gives 7.2x on NVDA against 13.5x for
# the old plateau — most of the conservatism the cap was reaching for, without
# discarding a single basis point of observed data.
#
# This is what let the 25% ceiling go. The ceiling existed to survive the
# plateau, not to express a view about growth.
STAGE1_YEARS = 1            # the one year the consensus actually forecasts
STAGE2_YEARS = 9            # linear fade from that rate to terminal
PROJECTION_YEARS = STAGE1_YEARS + STAGE2_YEARS

# Bounds that reject corrupt vendor data. NOT an opinion about growth.
#
# The old band was (0%, 25%) and both ends were economic judgements. The floor
# grew shrinking companies at zero — fourteen analysts put XOM at -2.3%, and
# flooring that inflated its fair value 15.7%. The ceiling truncated genuine,
# well-supported consensus: NVDA's 42.6% from 55 analysts became 25%, which
# produced the whole of its -58.7% "overvalued" verdict.
#
# Neither survives. What remains is wide enough that only a corrupt field trips
# it, and a value outside is **rejected** — the model falls back to the next
# source and labels it — rather than truncated to the bound. That distinction is
# the whole point: truncation substitutes a number no source produced and the
# reader cannot trace; rejection keeps provenance.
GROWTH_VALIDITY_RANGE = (-0.50, 2.00)

# Used only when neither a consensus nor a trailing figure exists. Named, so it
# can be reported as the assumption it is rather than passed off as measured.
DEFAULT_GROWTH_RATE = 0.05

# How far the stress test ranges, which is a different job from validating an
# input and so is *not* bounded by the range above. Measured 2026-08-12, holding
# the sweep inside the old input band made it one-sided at both ends: a company
# at 0% growth got upside and no downside, one at 25% the reverse, while the
# label claimed a symmetric sweep either way. A business whose cash flow shrinks
# is a real case, and a sensitivity that cannot express it cannot stress the
# downside.
GROWTH_SENSITIVITY_STEPS = (-0.04, -0.02, 0.0, 0.02, 0.04)
# Only to keep a pathological caller-supplied override from driving cash flow
# through zero — the base rate is bounded by GROWTH_VALIDITY_RANGE in every path
# the app itself takes, so this never binds in practice.
GROWTH_SENSITIVITY_FLOOR = -0.5

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


MARKET_PREMIUMS_PATH = Path(__file__).resolve().parent / "market_risk_premiums.json"
_MARKET_PREMIUMS: dict | None = None


def _market_premiums() -> dict:
    """The vendored Damodaran snapshot, read once per process.

    Returns `{}` when the file is missing or unparseable, which sends every
    caller to EQUITY_RISK_PREMIUM. Same rule as `risk_free_rate` falling back to
    RISK_FREE_RATE when the Fed feed is unreachable: a missing reference file
    degrades the number and says so, it never breaks the endpoint.
    """
    global _MARKET_PREMIUMS
    if _MARKET_PREMIUMS is None:
        try:
            _MARKET_PREMIUMS = json.loads(
                MARKET_PREMIUMS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _MARKET_PREMIUMS = {}
    return _MARKET_PREMIUMS


def equity_risk_premium_for(reporting_currency: str | None
                            ) -> tuple[float, str, str | None]:
    """(erp, source, market) for the currency the cash flows are denominated in.

    Keyed on `financialCurrency`, deliberately differing from `tax_rate_for`
    above, which keys on the trading currency. Tax follows the jurisdiction a
    company files in; a discount rate has to match the currency of the cash
    flows it discounts. 0700.HK trades HKD and reports CNY, so it is priced off
    China's premium — which is also the right economic answer for a business
    whose operations and risk are Chinese, not merely listed in Hong Kong.

    `total_erp` is used exactly as published and nothing is added to it.
    Damodaran's country figure is additive — total = mature market + country
    risk premium — so adding the CRP on top would count the country twice. The
    snapshot carries the CRP for audit only, and a test pins that it stays out
    of the arithmetic.

    Three sources, each named rather than silently blended:
      damodaran_<date>  the market has an entry
      mature_market     no entry for this currency; the floor Damodaran's own
                        table is built on, which is honest for a developed
                        market and understates a risky one
      platform_default  no reference file at all
    """
    data = _market_premiums()
    entry = (data.get("markets") or {}).get(reporting_currency or "")
    if entry and entry.get("total_erp"):
        return entry["total_erp"], f"damodaran_{data.get('as_of')}", entry.get("country")
    if data.get("mature_market_erp"):
        return data["mature_market_erp"], "mature_market", None
    return EQUITY_RISK_PREMIUM, "platform_default", None


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
    # HK issuers keep the USD 10Y: the HKD peg makes it an acceptable proxy.
    # Known to be the weaker half of this pair — 0700.HK reports CNY, which is
    # not pegged, so its cash flows and its discount rate are in different
    # currencies. Not fixed here: China's 10Y runs ~260bp below the US, which
    # would roughly double that valuation, and whether the conversion should
    # then use spot or a forward rate is unsettled. See TODOLIST.
    rf = risk_free_rate(RISK_FREE_RATE)
    # The ERP half of the same pair, and the half that can be sourced today.
    erp, erp_source, erp_market = equity_risk_premium_for(
        info.get("financialCurrency"))
    cost_of_equity = rf + beta * erp
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
        "equity_risk_premium": round(erp, 4),
        "equity_risk_premium_source": erp_source,
        "equity_risk_premium_market": erp_market,
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
                  terminal_growth: float | None = None,
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
    # What the primary source published, retained so a rejection stays visible:
    # if a consensus was discarded as implausible, the reader can see both the
    # figure that was rejected and the one used instead.
    growth_rate_published = None
    if growth_rate is None:
        # prefer analyst forward consensus over trailing growth
        # Four distinct provenances, four distinct labels. Nothing here is
        # truncated: a figure either passes the validity range and is used as
        # published, or fails it and is rejected in favour of the next source.
        # The label always says which, so no number on screen is untraceable.
        fwd = (f.get("estimates") or {}).get("revenue_growth_fwd")
        trailing = info.get("revenueGrowth")
        def valid(x):
            return x is not None and \
                GROWTH_VALIDITY_RANGE[0] <= x <= GROWTH_VALIDITY_RANGE[1]

        if valid(fwd):
            growth_rate, growth_source = fwd, "analyst_consensus_fwd"
        elif fwd is not None and valid(trailing):
            growth_rate, growth_source = trailing, "consensus_rejected_implausible"
        elif valid(trailing):
            growth_rate, growth_source = trailing, "trailing_revenue_growth"
        else:
            growth_rate, growth_source = DEFAULT_GROWTH_RATE, "default_assumed"
        # what the primary source published, kept so a rejection is visible
        growth_rate_published = fwd if fwd is not None else trailing

    wacc_parts = _wacc(f, tax_rate, peers)
    wacc = wacc_override if wacc_override is not None else wacc_parts["wacc"]

    # Terminal growth: the platform's policy, or exactly what the caller asked
    # for. The two must stay distinguishable, which is why the parameter
    # defaults to None rather than to TERMINAL_GROWTH.
    #
    # The policy is 2.5% held under two ceilings. Neither is a view about the
    # company; both are arithmetic limits on what a perpetuity may claim:
    #
    #   nominal GDP    nothing outgrows its economy forever, so a rate above
    #                  NOMINAL_GDP_GROWTH says the company eventually becomes
    #                  the economy.
    #   risk-free rate Damodaran's cap — the risk-free rate is itself roughly
    #                  expected inflation plus expected real growth, so it is a
    #                  market-implied read of long-run nominal growth. It binds
    #                  only in a low-rate regime (at a 4.30% ten-year it does
    #                  not); a 2020-style 0.6% ten-year is exactly the case it
    #                  exists for, where a fixed 2.5% would quietly assume
    #                  perpetual growth above what the bond market prices.
    #
    # Applied **only** to the default. A caller naming a rate gets that rate:
    # `solve_for_fair_value` sweeps terminal growth well past both ceilings on
    # purpose, and capping it there would turn "this gap needs 7.01% perpetual
    # growth to close" — the most useful sentence the reconciliation produces —
    # into an unreachable target reported as None.
    terminal_growth_source = "user"
    if terminal_growth is None:
        rf_cap = wacc_parts["risk_free_rate"]
        terminal_growth = min(TERMINAL_GROWTH, rf_cap)
        terminal_growth_source = ("platform_default" if terminal_growth == TERMINAL_GROWTH
                                  else "capped_at_risk_free_rate")

    if wacc <= terminal_growth:
        return {"error": f"WACC ({wacc:.2%}) must exceed terminal growth ({terminal_growth:.2%})."}

    def project(w: float, g_term: float, g_start: float | None = None,
                base: float | None = None) -> tuple[float, float, float]:
        """(PV of explicit years, PV of terminal value, final-year growth factor).

        `g_start` overrides the base growth rate so the same projection can be
        swept for the growth sensitivity below; None means the base case.
        `base` overrides the starting free cash flow the same way, for the
        base-year band — the model is homogeneous of degree one in it, so the
        override scales the result exactly and nothing damps it.
        """
        pv = 0.0
        cash_flow = fcf if base is None else base
        compounded = 1.0
        path = _growth_path(growth_rate if g_start is None else g_start, g_term)
        for year, g in enumerate(path, start=1):
            cash_flow *= (1 + g)
            compounded *= (1 + g)
            pv += cash_flow / (1 + w) ** year
        terminal = cash_flow * (1 + g_term) / (w - g_term)
        return pv, terminal / (1 + w) ** PROJECTION_YEARS, compounded

    def enterprise_value(w: float, g_term: float, g_start: float | None = None,
                         base: float | None = None) -> float:
        pv, terminal_pv, _ = project(w, g_term, g_start, base)
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

    # And the same cross-check run backwards, which is the more useful direction.
    #
    # The exit multiple above reduces to `(FCF/EBITDA) x (1+g)/(WACC-g)` — the
    # growth factor cancels — so with the terminal rate pinned at 2.5% for every
    # company the perpetuity factor is ~14-22x for all of them, and the implied
    # exit lands near 5-13x against 10-27x actually traded. Reading that as "the
    # DCF says expensive" is the wrong conclusion: it is a statement about what a
    # Gordon perpetuity can express, not about the company.
    #
    # Solving instead for the terminal growth that *today's own traded multiple*
    # requires turns it into a question the reader can settle. Measured
    # 2026-08-12: AAPL 7.30%, MSFT 7.63%, 0700.HK 3.23% — so Tencent's price
    # needs nothing unusual, while Apple's needs free cash flow compounding above
    # nominal GDP in perpetuity. Both legs are unit-free ratios, so no FX
    # conversion applies (see the boundary note above).
    #
    #   traded = conv x (1+g)/(WACC-g),  conv = FCF/EBITDA,  k = traded/conv
    #   =>  g = (k*WACC - 1) / (1 + k)
    #
    # g is always below WACC for any finite k, so the solve cannot blow up.
    market_implied_growth = None
    current_multiple = info.get("enterpriseToEbitda")
    if ebitda and ebitda > 0 and current_multiple and current_multiple > 0:
        conversion = fcf / ebitda
        if conversion > 0:
            k = current_multiple / conversion
            market_implied_growth = round((k * wacc - 1) / (1 + k), 4)

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

    # The grid above sweeps WACC and terminal growth — the two second-order
    # assumptions — and holds the first-order one fixed, so a reader watching it
    # sees a band that is narrow for the wrong reason. Measured 2026-08-12 on
    # 0700.HK the grid spans 543.96-922.81 around a 682.40 base, while moving the
    # starting rate alone from 9.38% to 4% gives 502.96: the growth assumption
    # crosses the gap to the peer-multiple read, and nothing on screen said so.
    # Deliberately *not* held inside GROWTH_VALIDITY_RANGE — see its comment: the
    # clamp bounds what the model accepts as an input, not how far a stress test
    # is allowed to look.
    growth_rates = [round(max(growth_rate + d, GROWTH_SENSITIVITY_FLOOR), 4)
                    for d in GROWTH_SENSITIVITY_STEPS]
    growth_values = [
        round((enterprise_value(wacc, terminal_growth, g) - net_debt) * conv / shares, 2)
        if shares else None
        for g in growth_rates
    ]

    terminal_share = round(terminal_pv / ev, 4) if ev else None

    # The base-year band. The headline above stays the reported year — it ticks
    # to a filing, and that property is worth keeping. This is the same model on
    # the same company with the base year set to what its own history says is
    # normal, shown beside it so the reader can see the size of that choice
    # rather than inherit it.
    #
    # Direction is the point. Normalisation moves 0700.HK *down* (+29.8% ->
    # +22.9% upside) while moving MSFT and XOM up, so it is a correction rather
    # than a nudge toward the market price — a change that narrowed every gap
    # would be a price tracker, not a model.
    #
    # The interest add-back is re-applied on top: the normalisation acts on the
    # statement quantity `CFO - CapEx`, and the unlevering that turns it into
    # FCFF is a separate step that must not be normalised away.
    base_year = base_year_context(f, statement[0] if statement else None)
    fair_value_normalised = None
    normalised = base_year.get("normalised_statement_fcf")
    if normalised and normalised > 0 and shares:
        normalised_fcff = normalised + interest_addback
        fair_value_normalised = round(
            (enterprise_value(wacc, terminal_growth, base=normalised_fcff) - net_debt)
            * conv / shares, 2)

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
            # None when the caller supplied the rate; differs from the above only
            # when the published figure was rejected as implausible
            "growth_rate_published": (round(growth_rate_published, 4)
                                      if growth_rate_published is not None else None),
            "growth_source": growth_source,
            "terminal_growth": terminal_growth,
            # Where 2.5% comes from, so it stops being a bare constant on
            # screen. Both ceilings are shown whether or not they bind — a
            # reader cannot tell that a limit was respected unless the limit
            # is visible. "user" means the caller named the rate and neither
            # ceiling was applied.
            "terminal_growth_source": terminal_growth_source,
            "terminal_growth_anchor": TERMINAL_GROWTH,
            "terminal_growth_ceilings": {
                "nominal_gdp_growth": NOMINAL_GDP_GROWTH,
                "risk_free_rate": wacc_parts["risk_free_rate"],
            },
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
            # what perpetual growth today's price already assumes, and whether
            # that is more than an economy grows
            "market_implied_terminal_growth": market_implied_growth,
            "market_implied_growth_high": (market_implied_growth is not None
                                           and market_implied_growth > NOMINAL_GDP_GROWTH),
            "nominal_gdp_growth": NOMINAL_GDP_GROWTH,
            # empty is the healthy case: both legs of the bridge were reported
            "net_debt_assumed_zero": net_debt_assumed,
            # whether the base year is a run-rate, with an auditable alternative
            # where it is not. Reported stays the headline — this is shown
            # beside it, never substituted for it.
            "base_fcf_quality": base_fcf_quality(f, statement[0] if statement else None),
            # The company's own margin history, the exact operating/capital
            # decomposition of the base year, and what the valuation becomes on
            # a normalised base. `fair_value_normalised` is the *other end of a
            # band*, never a replacement for the headline above.
            "base_year": {**base_year, "fair_value_normalised": fair_value_normalised,
                          "fair_value_normalised_upside_pct":
                              round((fair_value_normalised / price - 1) * 100, 1)
                              if fair_value_normalised and price
                              and fx_basis != "rate_unavailable" else None},
        },
        "sensitivity": {
            "terminal_growth_cols": [round(terminal_growth + d, 4)
                                     for d in (-0.005, -0.0025, 0.0, 0.0025, 0.005)],
            "rows": sensitivity,
        },
        # WACC and terminal growth held at base; only the starting rate moves,
        # so this is readable as "what the answer costs per point of growth".
        "growth_sensitivity": {
            "growth_rates": growth_rates,
            "values": growth_values,
        },
    }


# How far this year's cash conversion may sit from the company's own history
# before the base year stops being a run-rate.
#
# Deliberately keyed on FCF/net income rather than on FCF against its own median.
# Measured across nine large caps 2026-08-13, an FCF-vs-median test fired on
# five of seven and was mostly wrong: NVDA +120% and AMD +144% are growth, not
# anomalies. Cash conversion separates them — those two sit inside 8% while KO,
# whose earnings rose as its cash flow halved, breaks by 34%.
CASH_CONVERSION_BREAK = 0.25


def base_fcf_quality(f: dict, period: str | None) -> dict:
    """Whether the base year's free cash flow is a run-rate, and what it would
    be if the working-capital movement were normal.

    A DCF anchored on a contaminated year propagates that contamination through
    every projected year *and* the terminal value, and free cash flow enters
    linearly — so a 30% base error is a 30% valuation error, permanently.
    Measured on KO: net income rose 9.54 -> 13.11bn while operating cash flow
    fell 11.02 -> 7.41bn, because the working-capital line swung from -0.60 to
    -7.21bn. That is cash leaving for something the income statement never
    expensed.

    The alternative is built as a **bridge of filed line items**, not as a
    median of past free cash flows. That is the more transparent construction
    even though it looks like the more aggressive one: every term below can be
    looked up in the filing, whereas a median is a statistical smear over data
    the reader cannot decompose. A platform reading structured vendor data
    cannot read the notes, so it can *detect* an anomaly but never *identify*
    the cause — which is exactly why this returns an alternative to show
    alongside the reported figure and never replaces it.
    """
    out = {"anomalous": False, "conversion": None, "reference": None,
           "deviation": None, "normalised_fcf": None, "bridge": None}
    cf, inc = f.get("cash_flow") or {}, f.get("income_statement") or {}
    if not period or period not in cf:
        return out

    def conversion(p: str):
        ocf = _value_at(cf, p, "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities")
        capex = _value_at(cf, p, "Capital Expenditure")
        net_income = _value_at(inc, p, "Net Income")
        if ocf is None or capex is None or not net_income or net_income <= 0:
            return None
        return (ocf + capex) / net_income

    base = conversion(period)
    # Compared against the *other* years, not against a median that includes the
    # year under test — on KO two of four periods are contaminated, so a median
    # of all four is dragged by the very anomaly it is meant to measure.
    others = [c for p in cf if p != period and (c := conversion(p)) is not None]
    if base is None or len(others) < 2:
        return out

    reference = median(others)
    if not reference:
        return out
    out.update(conversion=round(base, 4), reference=round(reference, 4),
               deviation=round(base / reference - 1, 4))
    if abs(out["deviation"]) <= CASH_CONVERSION_BREAK:
        return out

    ocf = _value_at(cf, period, "Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities")
    capex = _value_at(cf, period, "Capital Expenditure")
    wc = _value_at(cf, period, "Change In Working Capital")
    normal_wc = median([w for p in cf if p != period
                        and (w := _value_at(cf, p, "Change In Working Capital")) is not None]
                       or [0.0])
    if ocf is None or capex is None or wc is None:
        # the break is real but cannot be decomposed into filed lines, so it is
        # reported without an alternative rather than with a guessed one
        out["anomalous"] = True
        return out

    out["anomalous"] = True
    out["normalised_fcf"] = round(ocf - wc + normal_wc + capex)
    out["bridge"] = [
        {"label": "Operating cash flow, as reported", "value": round(ocf)},
        {"label": "Less the reported working-capital movement", "value": round(-wc)},
        {"label": "Plus a normal working-capital movement (median of other years)",
         "value": round(normal_wc)},
        {"label": "Less capital expenditure", "value": round(capex)},
    ]
    return out


def base_year_context(f: dict, period: str | None) -> dict:
    """Is the base year representative, and what does the company's own history say?

    The DCF anchors on one cash-flow period and free cash flow enters the
    valuation linearly, so a base year 22% below normal is a valuation 22% below
    normal — permanently, through every projected year and the terminal value.
    Measured across the fixtures 2026-08-13, the newest reported year sits below
    that company's own mean FCF margin for three of the four profitable names:
    AAPL 0.90x, MSFT 0.78x, XOM 0.71x, with 0700.HK the exception at 1.06x.
    Taking whatever period the vendor reported last is therefore not a neutral
    choice. It is a one-directional bias, and unlike the terminal-growth band it
    does not wash out across names — it penalises whoever is mid-investment or
    mid-cycle, which corrupts exactly the cross-name ranking a screener is for.

    Nothing here is a forecast. Every figure is arithmetic on filed statements:

      FCF/revenue  =  CFO/revenue  -  capex/revenue          (capex is negative)

    so the movement in the base year's FCF margin decomposes **exactly** into an
    operating leg and a capital leg with no residual and no assumption. That
    decomposition is what separates a business earning less from a business
    spending more, and it is the first thing an analyst checks. MSFT is the case
    it exists for: capex ran 13.3% -> 18.1% -> 22.9% -> 34.9% of revenue over
    four years while operating cash *rose* 41.3% -> 55.1%, so its depressed free
    cash flow is a build phase, not deterioration.

    The two legs will not always tell that clean a story, and the caller must not
    assume they do. XOM's capex rose 4.6% -> 8.8% of revenue *and* its operating
    cash fell 19.3% -> 16.0%: both moved against free cash flow, and `driver`
    names only which of them moved further.

    What the platform will **not** do is decide whether that build phase ends.
    That needs a view on AI compute demand and on the returns this capex earns —
    questions whose answers are not in the accounts. Any mechanical rule
    ("capex above 1.5x D&A reverts within three years") would be a macro
    forecast wearing accounting clothes. So this returns both endpoints and
    lets the reader choose, which is the honest shape of the answer.

    The lookback is every period the statements carry rather than a chosen
    number of years, so no window was picked to suit an outcome.
    """
    out = {"history": [], "periods": 0, "latest_fcf_margin": None,
           "mean_fcf_margin": None, "ratio_to_mean": None,
           "normalised_statement_fcf": None, "latest_revenue": None,
           "driver": None, "driver_note": None,
           "capex_delta": None, "operating_delta": None}
    cf, inc = f.get("cash_flow") or {}, f.get("income_statement") or {}
    if not period or period not in cf:
        return out

    # Held unrounded, and rounded once on the way out. Every statistic below is
    # a mean over these, so rounding first would let a display artefact compound
    # across periods and then show up as a panel whose columns do not add up.
    raw = []   # (period, fcf margin, operating cash margin, capex intensity)
    for p in sorted(cf):
        revenue = _value_at(inc, p, "Total Revenue", "Operating Revenue")
        ocf = _value_at(cf, p, "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities")
        capex = _value_at(cf, p, "Capital Expenditure")
        if not revenue or ocf is None or capex is None:
            continue
        # capex is reported negative; carried as the positive intensity a reader
        # expects, which is why the identity below subtracts it
        raw.append((p, (ocf + capex) / revenue, ocf / revenue, -capex / revenue))

    # Two periods cannot establish what is normal, so no band is offered rather
    # than one built on a single comparison.
    if len(raw) < 3 or raw[-1][0] != period:
        return out

    out["history"] = [{"period": p, "fcf_margin": round(fcf_m, 4),
                       "operating_margin_cash": round(ocf_m, 4),
                       "capex_to_revenue": round(capex_i, 4)}
                      for p, fcf_m, ocf_m, capex_i in raw]

    margins = [r[1] for r in raw]
    latest, mean_margin = margins[-1], sum(margins) / len(margins)
    out.update(periods=len(margins),
               latest_fcf_margin=round(latest, 4),
               mean_fcf_margin=round(mean_margin, 4),
               ratio_to_mean=round(latest / mean_margin, 3) if mean_margin else None)

    # Scale by the latest revenue, not by an averaged one. Revenue is the least
    # volatile and most audited line on the statement, so normalising the ratio
    # while holding the company's current size fixed changes one thing. Averaging
    # absolute past free cash flow instead would anchor to a smaller company and
    # is wrong for any grower — measured, it moves MSFT only 1.06x against the
    # 1.29x its own margin history supports.
    revenue = _value_at(inc, period, "Total Revenue", "Operating Revenue")
    out["latest_revenue"] = revenue
    if revenue:
        out["normalised_statement_fcf"] = round(mean_margin * revenue)

    # Which leg moved, measured against **the same average the band uses**.
    #
    # These were compared against the mean of the *other* years, which is the
    # right instinct — `base_fcf_quality` excludes the year under test for good
    # reason — but wrong here, because the panel puts both figures in one
    # paragraph. On MSFT it read "0.777x its 4-year average" beside legs summing
    # to -7.7pp, while latest minus that same 4-year average is -5.8pp, so a
    # reader recomputing from the table on screen got a different answer than
    # the sentence beneath it. Two baselines in one story is exactly the
    # un-auditable arithmetic this panel exists to remove.
    #
    # Nothing is lost by switching. Moving the baseline from the other years to
    # all of them scales **both** legs by exactly (n-1)/n — the year under test
    # is one of n, so it dilutes each mean identically — which leaves the ratio
    # between the legs, and therefore every `driver` label, unchanged.
    mean_capex = sum(r[3] for r in raw) / len(raw)
    mean_ocf = sum(r[2] for r in raw) / len(raw)
    capex_delta = raw[-1][3] - mean_capex
    ocf_delta = raw[-1][2] - mean_ocf
    out["capex_delta"] = round(capex_delta, 4)
    out["operating_delta"] = round(ocf_delta, 4)
    # Only named when the year is actually off its own average; on a
    # representative year there is no driver to name.
    if out["ratio_to_mean"] is not None and abs(out["ratio_to_mean"] - 1) > 0.05:
        capex_driven = abs(capex_delta) > abs(ocf_delta)
        out["driver"] = "capital_spending" if capex_driven else "operating_cash"
        # `driver` alone is not a story, and reading one off it is how a panel
        # ends up contradicting itself: 0700.HK is operating-cash-driven with
        # *both* legs up, which an earlier draft rendered as "operating cash is
        # the larger of the two" immediately followed by "this is a business
        # spending more". Which leg is larger and which way each leg pushed are
        # two different facts, so the six reachable combinations are resolved
        # here — where they can be tested — rather than in JSX.
        #
        # More capital spending lowers free cash flow, so a rise in `capex_delta`
        # is adverse while a rise in `ocf_delta` is favourable.
        oper_helps, capex_helps = ocf_delta >= 0, capex_delta <= 0
        if oper_helps and capex_helps:
            out["driver_note"] = "both_favourable"
        elif not oper_helps and not capex_helps:
            out["driver_note"] = "both_adverse"
        elif capex_driven:
            out["driver_note"] = ("spending_more_not_earning_less" if oper_helps
                                  else "spending_less_offset_weaker_earnings")
        else:
            out["driver_note"] = ("earning_more_despite_spending_more" if oper_helps
                                  else "earning_less_not_spending_more")
    return out


def solve_for_fair_value(f: dict, target_value: float, param: str,
                         lo: float, hi: float, peers: list[dict] | None = None,
                         rising: bool = True) -> float | None:
    """The value of `param` at which the DCF's fair value equals `target_value`.

    Fair value is monotone in each of the three assumptions the model exposes —
    rising in growth and terminal growth, falling in WACC — so a bisection is
    exact enough and needs no derivative. `rising` says which.

    Returns None when the target lies outside what `param` can reach inside
    `[lo, hi]`. That is a result, not a failure: "no rate in this band gets you
    there" is exactly what makes a gap irreconcilable rather than merely large.
    """
    def fair_value(x: float):
        out = dcf_valuation(f, peers=peers, **{param: x})
        return None if out.get("error") else out.get("fair_value_per_share")

    f_lo, f_hi = fair_value(lo), fair_value(hi)
    if f_lo is None or f_hi is None:
        return None
    if not min(f_lo, f_hi) <= target_value <= max(f_lo, f_hi):
        return None
    for _ in range(30):
        if hi - lo < 1e-5:
            break
        mid = (lo + hi) / 2
        value = fair_value(mid)
        if value is None:
            return None
        lo, hi = (mid, hi) if (value < target_value) == rising else (lo, mid)
    return round((lo + hi) / 2, 4)


# A gap this small is not worth explaining — the methods already agree closely
# enough that naming a "binding assumption" would be reading noise.
RECONCILED_UPSIDE_TOLERANCE = 0.10

# How far above its own consensus a company's near-term growth may be pushed
# before "this rate would close the gap" stops being a defensible claim.
#
# The [0, 25%] guardrail is the wrong test here: it bounds what the *model*
# accepts, not what a *company* plausibly does. Measured 2026-08-13 on the AAPL
# fixture, closing its gap needs 24.06% near-term growth against a 9.74%
# consensus — inside the guardrail and still two and a half times what anyone
# forecasts. Judging against the guardrail alone made the verdict flip from
# irreconcilable to reconcilable on a 42bp move in the risk-free rate, which is
# far too fragile for a classification. A judgement, like the EV/Revenue margin
# tolerance, and stated in the reason so a reader can disagree with it.
GROWTH_PLAUSIBILITY_FACTOR = 1.5


def reconcile_to_price(f: dict, dcf: dict, peers: list[dict] | None = None) -> dict:
    """Which single assumption, moved alone, would make the DCF equal the price.

    Measured across eighteen large caps 2026-08-13, a DCF far below the market
    is **not** a general defect: nine of the eighteen came out within 10% of the
    price or above it. Of the nine that did not, every one needed a perpetual
    growth rate above the risk-free rate to close, and several needed one no
    business sustains. So "the DCF is too low" is sometimes a fixable
    assumption and sometimes a real statement about the price, and the two look
    identical on the chart unless something separates them.

    Back-solving does. Measured on the fixtures: 0700.HK reconciles at -0.21%
    terminal growth or 4.30% near-term growth — both ordinary, so its gap is a
    forecast disagreement. AAPL needs 7.36% terminal growth or 25.37% near-term,
    the first above what an economy grows and the second past the input
    guardrail — so no defensible assumption reconciles it, and the gap is the
    market pricing something a perpetuity cannot express.

    WACC is deliberately not among the candidates. It is the least legible of
    the three to a reader, and where it is the culprit the beta source already
    says so in the audit row.
    """
    out = {"required_terminal_growth": None, "required_growth_rate": None,
           "growth_input_substituted": False, "verdict": None, "reason": None}
    if not dcf or dcf.get("error"):
        return out
    price, fair = dcf.get("current_price"), dcf.get("fair_value_per_share")
    if not price or not fair:
        return out

    a = dcf["assumptions"]
    # Substituted means the model is not reporting the figure its primary source
    # published — either that figure failed the validity range and was rejected,
    # or none existed and a default stood in. Nothing is truncated any more, so
    # this is a question about provenance rather than about a bound.
    published, used = a.get("growth_rate_published"), a.get("growth_rate_year1")
    out["growth_input_substituted"] = a.get("growth_source") in (
        "consensus_rejected_implausible", "default_assumed")

    # A substituted input is a statement about provenance, not about the size of
    # the gap, so it outranks "aligned": a fair value that lands near the price
    # while running on a stand-in number is a coincidence, not agreement, and
    # reporting it as agreement would hide the one thing the reader needs.
    if abs(fair / price - 1) <= RECONCILED_UPSIDE_TOLERANCE \
            and not out["growth_input_substituted"]:
        out["verdict"] = "aligned"
        out["reason"] = "The DCF and the market are within 10% of each other."
        return out

    wacc = a["wacc_used"]
    out["required_terminal_growth"] = solve_for_fair_value(
        f, price, "terminal_growth", -0.02, wacc - 0.005, peers, rising=True)
    out["required_growth_rate"] = solve_for_fair_value(
        f, price, "growth_rate", GROWTH_VALIDITY_RANGE[0], GROWTH_VALIDITY_RANGE[1],
        peers, rising=True)

    tg, g1 = out["required_terminal_growth"], out["required_growth_rate"]
    raw = used
    direction = "below" if fair < price else "above"
    if out["growth_input_substituted"]:
        rejected = a.get("growth_source") == "consensus_rejected_implausible"
        out["verdict"] = "input_substituted"
        out["reason"] = (
            (f"The published consensus of {published:.1%} fell outside the range this model "
             f"will accept as data, so it was rejected and {used:.1%} used instead. "
             if rejected else
             f"Neither a consensus nor a trailing figure was available, so an assumed "
             f"{used:.1%} was used. ")
            + "This DCF is not running on a forecast for this company; read the fair value as "
              "indicative only.")
    elif tg is not None and tg <= NOMINAL_GDP_GROWTH:
        out["verdict"] = "reconcilable"
        out["reason"] = (
            f"The DCF sits {direction} the price, but only on the terminal assumption: at "
            f"{tg:.2%} terminal growth — below the {NOMINAL_GDP_GROWTH:.0%} an economy grows — "
            f"the two agree. This is a disagreement about the forecast, not about the price.")
    elif g1 is not None and _growth_is_plausible(g1, raw):
        out["verdict"] = "reconcilable"
        against = (f", against a {raw:.1%} consensus" if raw is not None else "")
        out["reason"] = (
            f"The DCF sits {direction} the price, but {g1:.2%} near-term growth closes it"
            f"{against}. The gap is about how fast this company grows, which is researchable.")
    else:
        need_tg = f"{tg:.2%} terminal growth" if tg is not None else "no reachable terminal growth"
        need_g1 = (f"{g1:.2%} near-term growth against a {raw:.1%} consensus"
                   if g1 is not None and raw is not None
                   else "no near-term growth rate this model will accept")
        out["verdict"] = "irreconcilable"
        out["reason"] = (
            f"Nothing defensible closes this gap: it would take {need_tg} — against the "
            f"{NOMINAL_GDP_GROWTH:.0%} an economy grows — or {need_g1}. The market is pricing "
            f"something a perpetuity cannot express, so the DCF and the multiples will not "
            f"agree here and neither is simply wrong.")
    return out


def _growth_is_plausible(required: float, consensus: float | None) -> bool:
    """Whether a required near-term rate is close enough to consensus to claim.

    With no consensus to compare against — a caller-supplied rate — the model's
    own guardrail is the only bound available, and `solve_for_fair_value` has
    already enforced it by returning None outside the band.
    """
    if consensus is None:
        return True
    if consensus <= 0:
        # a company forecast to shrink cannot be talked into growth by arithmetic
        return required <= 0
    return required <= consensus * GROWTH_PLAUSIBILITY_FACTOR


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
