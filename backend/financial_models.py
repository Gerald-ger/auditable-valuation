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
from functools import partial
from pathlib import Path
from statistics import median

from backend import market_series
from backend import sector_weights
from backend import statements
from backend.data_provider import fx_rate, risk_free_rate

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

# A REIT distributes its taxable income and deducts the distribution, so there
# is almost no corporate tax and almost no interest tax shield. Not a lower rate
# for the same reason other companies pay less than statutory — a different
# structure. See tax_rate_for.
REIT_TAX_RATE = 0.0

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




def tax_rate_for(info: dict) -> float:
    """Statutory tax rate for the listing's jurisdiction, by currency.

    A REIT is the one exception, and it is an exception in *kind* rather than in
    degree. Everywhere else the gap between the statutory rate and the rate a
    company actually pays is tax planning, and the statutory figure is the right
    input for a debt tax shield because it is the marginal rate on the next
    dollar. A REIT deducts the dividends it distributes, so distributing the
    required share of taxable income leaves almost nothing to shield: Realty
    Income's own income statement reports 85.3m of tax on 1,155m of pre-tax
    income, an effective **7.4%**, and the residual is its taxable subsidiaries
    rather than the trust. The marginal rate is what matters here and it is
    approximately zero.

    Charging a REIT 21% overstated its interest tax shield and so understated
    its WACC — measured on the committed fixture, 6.05% against 6.58%, which is
    a fair value of 36.00 against 27.04. `dcf_applies` already declares the DCF
    itself inapplicable to this profile, but the rate also reaches `scoring`'s
    NOPAT, and a REIT's after-tax operating profit really is close to its EBIT.

    Read through `sector_weights.classify` rather than re-testing the industry
    string here, so the REIT rule keeps one home. No free cash flow is passed
    because the REIT branch is decided from sector/industry alone, before
    `classify` consults it.
    """
    if sector_weights.classify(info) == "real_estate_reit":
        return REIT_TAX_RATE
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


def sovereign_default_spread(reporting_currency: str | None) -> float:
    """This market's sovereign default spread, or 0.0 where none is published.

    The other half of the pair `equity_risk_premium_for` returns, read from the
    same vendored snapshot so the two can never disagree about a market. It is
    subtracted from a *local* sovereign yield in `data_provider.risk_free_rate`,
    which is where the reason lives.

    Zero for an unknown market is the safe default rather than a lazy one: a
    market with no published spread also has no local curve wired up, so the
    value is never reached. If one is ever added without a spread, the effect is
    to leave the sovereign risk double-counted — visible in the number rather
    than silently corrected by a figure nobody sourced.
    """
    entry = (_market_premiums().get("markets") or {}).get(reporting_currency or "")
    return (entry or {}).get("default_spread") or 0.0


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


def ev_multiple_one_currency(multiple, trading_currency, reporting_currency):
    """A vendor EV multiple with both of its legs put back into one currency.

    `enterpriseToEbitda` and `enterpriseToRevenue` arrive already divided, and
    the split documented on `statement_to_market_fx` says the two legs are not
    in the same unit: enterprise value is built from `marketCap`, which is the
    trading currency, while `ebitda` and `totalRevenue` are statement figures in
    the reporting one. For 0700.HK that is an HKD numerator over a CNY
    denominator and the ratio is overstated by the whole CNY->HKD rate —
    measured on the committed fixture, 15.705x against a consistent 14.277x,
    and EV/Revenue 5.772x against 5.247x.

    Everything else in this module converts the figures it computes itself; this
    is the one place a *pre-divided* vendor ratio arrives with the mismatch
    already baked in, which is why it survived the currency work of 2026-08-10.

    Dividing by the rate restates the denominator in the trading currency. None
    when the currencies differ and no rate is available — the same choice the
    DCF makes for upside, because a mixed-unit multiple is worse than an absent
    one.
    """
    if multiple is None:
        return None
    fx, mismatch = statement_to_market_fx(trading_currency, reporting_currency)
    if not mismatch:
        return multiple
    return None if fx is None else round(multiple / fx, 4)


def ev_multiples_for(info: dict) -> tuple[float | None, float | None]:
    """(ev_to_ebitda, ev_to_revenue) for a whole `info` dict, on one currency."""
    trading, reporting = info.get("currency"), info.get("financialCurrency")
    return (ev_multiple_one_currency(info.get("enterpriseToEbitda"), trading, reporting),
            ev_multiple_one_currency(info.get("enterpriseToRevenue"), trading, reporting))


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
                 tax_rate: float = DEFAULT_TAX_RATE,
                 bars: list[dict] | None = None,
                 index_bars: list[dict] | None = None) -> tuple[float, str]:
    """(beta, source). A measured beta wins; the vendor's is the cross-check.

    `peers`, `bars` and `index_bars` are injected by the caller — this function
    never fetches. Each peer entry is a snapshot: `beta`, `market_cap`,
    `total_debt`. The bars are weekly closes for the company and for its home
    index, and when there are enough of them the beta is *regressed* rather than
    read: cov(stock, index) / var(index) over the overlapping weeks.

    Why regression sits above the reported figure rather than beside it. The
    vendor's beta is a number computed by an undisclosed method against an
    undisclosed index, and its errors are not random — measured 2026-08-06 the
    whole energy sector was implausible at once (XOM 0.173, CVX 0.488, COP
    0.123, SHEL -0.218, BP -0.212). A credibility band catches the extremes but
    passes anything merely wrong, and a sector-wide break defeats peer
    substitution too, which is how XOM ended up at a neutral 1.0 — the least
    informative answer available, applied to the company with the most
    distinctive risk profile in the fixture set.

    Everything below the computed tier is unchanged, deliberately: when there is
    no series to regress, a credible beta for *this company* is still better
    evidence than a median of its peers, so the existing ladder keeps its order.

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
    if bars and index_bars:
        fit, _observations = market_series.beta_fit(bars, index_bars)
        if fit is not None:
            # **The floor applies only where the regression cannot rule it out.**
            #
            # `BETA_MIN` was written for a vendor figure that could not be
            # checked at all. A regression can be, and it reports how well: on
            # the committed fixtures 0.30 sits **inside** exactly one confidence
            # interval — XOM's [0.0828, 0.4948], where R^2 is 0.028 and the data
            # genuinely cannot separate 0.29 from 0.30. It sits *outside* every
            # other, and on 0002_HK it is outside by a distance: [0.0747,
            # 0.2289] against a floor of 0.30, which the measurement rejects at
            # 95%. Clamping there was not guarding against a bad regression, it
            # was overruling a good one — worth 5.06% -> 5.80% on the cost of
            # equity and **74.05 against 97.27** on the fair value.
            #
            # So the interval decides. A thin or halted series produces a wide
            # one that still contains 0.30 and is still clamped; a precise
            # measurement below the floor is used as measured. Nothing new is
            # invented for the other side: with no floor a sufficiently negative
            # beta can drive WACC under terminal growth, and `dcf_valuation`
            # already refuses that in as many words rather than printing it.
            #
            # `BETA_MAX` is deliberately untouched. The same argument would
            # apply, but no fixture approaches 2.5 — RIVN is the highest at
            # 1.8371 — so changing it would be a change with no evidence behind
            # it, which is the thing this comment is objecting to.
            #
            # `beta_fit` rather than `beta`: the latter is a thin reading of the
            # former, so this costs no extra regression, and `_wacc` already
            # calls `beta_fit` for the audit row.
            floored = (max(fit["beta"], BETA_MIN)
                       if fit["confidence_interval"][1] >= BETA_MIN
                       else fit["beta"])
            return round(min(floored, BETA_MAX), 4), "computed"

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
    set this spread was measured in; see `statements.paired_latest` for why it is one year
    rather than the newest of each leg.
    """
    coverage, period = statements.interest_coverage(f["income_statement"])
    if coverage is None:
        return DEFAULT_CREDIT_SPREAD, None, period
    for floor, spread in CREDIT_SPREAD_LADDER:
        if coverage >= floor:
            return spread, round(coverage, 2), period
    return CREDIT_SPREAD_LADDER[-1][1], round(coverage, 2), period


def ratio_analysis(f: dict) -> dict:
    info = f["info"]
    inc, bal = f["income_statement"], f["balance_sheet"]

    revenue = statements.latest(inc, "Total Revenue")
    net_income = statements.latest(inc, "Net Income", "Net Income Common Stockholders")
    equity = statements.latest(bal, "Stockholders Equity", "Total Equity Gross Minority Interest")
    assets = statements.latest(bal, "Total Assets")

    def div(a, b):
        return round(a / b, 4) if a is not None and b not in (None, 0) else None

    # both legs from one period — see statements.paired_latest
    coverage, coverage_period = statements.interest_coverage(inc)
    ev_ebitda_1c, ev_revenue_1c = ev_multiples_for(info)

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
            # both legs on one currency — see ev_multiple_one_currency
            "ev_to_ebitda": ev_ebitda_1c,
            "ev_to_revenue": ev_revenue_1c,
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


def _wacc(f: dict, tax_rate: float, peers: list[dict] | None = None,
          market_bars: tuple[list[dict], list[dict]] | None = None) -> dict:
    info = f["info"]
    # (company weekly closes, home-index weekly closes) — one parameter because
    # the two are useless apart, and threading two through five call sites that
    # only pass them along would be noise.
    bars, index_bars = market_bars or (None, None)
    beta, beta_source = resolve_beta(info, peers, tax_rate, bars, index_bars)
    # How well that regression actually fit, when a regression is what was used.
    # Only then: the ladder's other rungs are a vendor scalar, a peer median and
    # a constant, and none of them has a residual to report — attaching an
    # interval to those would invent a precision claim rather than describe one.
    #
    # `resolve_beta` is deliberately left returning (beta, source). It is called
    # from one place in the app and from roughly twenty in the suite, and
    # widening its result to carry reporting-only figures would churn all of
    # them for nothing. The two calls cannot disagree: `beta_fit` is pure and
    # both read the same two bar lists.
    beta_fit = (market_series.beta_fit(bars, index_bars)[0]
                if beta_source == "computed" else None)
    # HK issuers keep the USD 10Y: the HKD peg makes it an acceptable proxy.
    # Known to be the weaker half of this pair — 0700.HK reports CNY, which is
    # not pegged, so its cash flows and its discount rate are in different
    # currencies. Not fixed here, but the reason changed on 2026-08-17 and this
    # comment was two revisions behind it (corrected 2026-08-18):
    #   - it is not "roughly double". Measured on the 0700_HK fixture with the
    #     growth cap moving too (docs/currency-consistent-discounting.md §4),
    #     re-measured 2026-08-19 *with market_bars*, which is what every
    #     main.py endpoint passes:
    #       rf 4.30% (today)          ->   469.48   (price 481.40, so -2.5%)
    #       rf 1.70% (China 10Y raw)  ->   601.62   = +28.1%   [-260bp]
    #       rf 1.10% (10Y - spread)   ->   611.62   = +30.3%   [-320bp]
    #     The old "double" came from moving the WACC alone; the terminal growth
    #     ceiling falls with the rate, which is most of the difference.
    #     This comment carried 680.99 / 1,024.98 / 1,043.30 and "+53.2%" until
    #     2026-08-19. Those reproduce exactly *without* market_bars — i.e. on
    #     the vendor's reported beta of 0.745 rather than the 1.3192 this
    #     fixture regresses to since 2026-08-14. They were never the app's
    #     numbers, and the effect is +30.3%, not +53.2%.
    #   - the applicable cut is the -320bp row, because the CNY risk-free is the
    #     10Y net of the CNY default spread (1.70 - 0.60 = 1.10 against 4.30).
    #     Netting the spread is worth only the 1.66% between the two rows
    #     (601.62 -> 611.62), so the contestable half of the change is also the
    #     cheap half. Quote the rows together: +28.1% belongs to -260bp and
    #     +30.3% to -320bp; pairing one with the other, as a 2026-08-18 draft of
    #     this comment did, mismatches them. These two figures were themselves
    #     "1.8%" and "+50.5%" until 2026-08-19 — the same superseded no-bars
    #     numbers as the block above, left behind when the table was corrected.
    #   - spot vs forward is NOT unsettled. docs/currency-consistent-
    #     discounting.md settled it: discounting in the cash-flow currency and
    #     translating the result at spot is algebraically identical to
    #     translating each flow at its forward rate, so spot is correct and is
    #     already what this code does. Applying a forward on top would double-
    #     count the interest differential.
    # What keeps it open is the terminal-growth ceiling: a 1.1-1.7% CNY rate
    # also asserts 1.1-1.7% perpetual growth for Tencent. See TODOLIST.
    # Both halves of CAPM now read the same currency. They did not until
    # 2026-08-19: the premium was Hong Kong's while the rate was America's.
    reporting_ccy = info.get("financialCurrency")
    rf, rf_source = risk_free_rate(RISK_FREE_RATE, reporting_ccy,
                                   sovereign_default_spread(reporting_ccy))
    # The ERP half of the same pair. Both legs now read one currency and one
    # vendored table, which is what stops them naming two different countries.
    erp, erp_source, erp_market = equity_risk_premium_for(reporting_ccy)
    cost_of_equity = rf + beta * erp
    # `or 0` is kept because the arithmetic below still has to produce a number
    # for the audit row when a caller supplies its own WACC. What changed on
    # 2026-08-27 is that the *fact* now leaves this function: a zero market cap
    # is not a capital structure, it is a missing input, and `dcf_valuation`
    # refuses on it rather than discounting at a debt-only rate.
    reported_market_cap = info.get("marketCap")
    market_cap = reported_market_cap or 0
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
        # Not a diagnostic for the reader — a gate for `dcf_valuation`. Measured
        # 2026-08-27 across the fixtures, discounting at the collapsed rate this
        # function would otherwise return moved fair value +362% to +942%.
        "market_cap_missing": not reported_market_cap,
        "risk_free_rate": round(rf, 4),
        # `usd_proxy` means this rate is not this currency's. Reported beside
        # `equity_risk_premium_market` below, which names the country the *other*
        # half of CAPM came from, so a reader can see the two halves disagree —
        # a Hong Kong premium against a United States rate.
        "risk_free_source": rf_source,
        "beta": beta,
        "beta_source": beta_source,
        "beta_reported": info.get("beta"),
        # Whether the vendor's own figure would have passed the band. Decided
        # here rather than in the UI so the credibility rule lives in one place:
        # once a computed beta can outrank a perfectly credible reported one,
        # "we did not use it" and "it was not believable" stop being the same
        # statement, and only the backend knows which applies.
        "beta_reported_credible": (None if info.get("beta") is None
                                   else BETA_MIN <= info["beta"] <= BETA_MAX),
        # How much of this name's movement the index actually explains, and how
        # wide the slope's own interval is. Present only for a regressed beta.
        #
        # The point is not that a low R^2 makes a beta wrong. It is that the
        # panel printed 0.2888 for XOM and 1.1546 for AAPL in the same typeface,
        # while one is measured to +/-0.08 and the other to +/-0.21 against a
        # value five times smaller. Which of those a reader should lean on is
        # not visible in the number.
        #
        # `beta_regressed` is the slope before the credibility band clamps it,
        # so a clamp that fires is legible rather than silent — XOM regresses at
        # 0.2888 and is used at 0.30.
        "beta_regressed": (None if beta_fit is None
                           else round(beta_fit["beta"], 4)),
        "beta_standard_error": (None if beta_fit is None
                                else round(beta_fit["standard_error"], 4)),
        "beta_r_squared": (None if beta_fit is None or beta_fit["r_squared"] is None
                           else round(beta_fit["r_squared"], 4)),
        "beta_confidence_interval": (None if beta_fit is None else
                                     [round(b, 4) for b in beta_fit["confidence_interval"]]),
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


def _project(fcf: float, growth_rate: float, w: float, g_term: float,
             g_start: float | None = None,
             base: float | None = None) -> tuple[float, float, float]:
    """(PV of explicit years, PV of terminal value, final-year growth factor).

    `g_start` overrides the base growth rate so the same projection can be
    swept for the growth sensitivity below; None means the base case.
    `base` overrides the starting free cash flow the same way, for the
    base-year band — the model is homogeneous of degree one in it, so the
    override scales the result exactly and nothing damps it.

    At module level rather than nested inside `dcf_valuation`, which is where it
    used to live as a closure over `fcf` and `growth_rate`. Those two are settled
    long before the projection runs, so binding them with `partial` is exactly
    what the closure did — and out here the arithmetic can be tested on its own.
    It could not be before: every one of the DCF's tests reached this loop only
    by running the whole valuation.
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


def _enterprise_value(fcf: float, growth_rate: float, w: float, g_term: float,
                      g_start: float | None = None,
                      base: float | None = None) -> float:
    pv, terminal_pv, _ = _project(fcf, growth_rate, w, g_term, g_start, base)
    return pv + terminal_pv


def dcf_valuation(f: dict, growth_rate: float | None = None,
                  terminal_growth: float | None = None,
                  wacc_override: float | None = None,
                  tax_rate: float | None = None,
                  peers: list[dict] | None = None,
                  market_bars: tuple[list[dict], list[dict]] | None = None) -> dict:
    info = f["info"]
    if tax_rate is None:
        tax_rate = tax_rate_for(info)
    # Statement first: yfinance's info["freeCashflow"] is annual for some issuers
    # and a single quarter for others (MSFT reports ~0.24x the statement figure),
    # which silently rescales the entire valuation.
    statement = statements.statement_fcf(f["cash_flow"])
    fcf_source = "cash_flow_statement"
    fcf = statement[1] if statement else None
    if fcf is None:
        fcf, fcf_source = info.get("freeCashflow"), "info_freecashflow"
    # Levered -> unlevered. Gate on the adjusted figure, since that is what gets
    # discounted; a company only positive before the add-back is still a DCF.
    interest_addback, fcff_basis = statements.fcff_interest_addback(
        f["cash_flow"], statement[0] if statement else None, tax_rate)
    # SBC is a real cost that the cash-flow statement adds back as non-cash.
    # Subtracted here rather than inside `statement_fcf`, because that function's
    # other three callers score a levered figure against market cap and net
    # income — both already after SBC — and would be double-corrected by it.
    sbc, sbc_basis = statements.sbc_expense(
        f["cash_flow"], statement[0] if statement else None)
    if fcf is not None:
        fcf += interest_addback - sbc
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

    wacc_parts = _wacc(f, tax_rate, peers, market_bars)
    # Refused rather than approximated, for the same reason a missing FX rate
    # withholds the upside instead of computing one across two currencies.
    # Without a market capitalisation there is no equity weight, so `_wacc`
    # returns the after-tax cost of debt alone — 3.87% against AAPL's 9.05%,
    # which is not a conservative discount rate but a wrong one. Measured
    # 2026-08-27: fair value +362% (0002.HK) to +942% (0700.HK), and the
    # composite *rose* five points as `dcf_upside_pct` came off its floor.
    # Nothing failed and nothing was flagged.
    #
    # Gated on `wacc_override is None` on purpose: a caller that names its own
    # rate never consults the collapsed one, and the sensitivity grid and
    # `solve_for_fair_value` both sweep it explicitly. Refusing them too would
    # withhold a valuation that does not depend on the missing figure.
    if wacc_override is None and wacc_parts["market_cap_missing"]:
        return {"error": "No market capitalisation reported, so the equity and "
                         "debt weights cannot be formed and there is no WACC "
                         "to discount at — DCF not applicable."}
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

    # Bound to this company's base cash flow and starting growth rate, both of
    # which are settled above and never reassigned below. The two swept
    # parameters stay positional, so every call site further down reads exactly
    # as it did when these were closures. See `_project` for why they are not.
    project = partial(_project, fcf, growth_rate)
    enterprise_value = partial(_enterprise_value, fcf, growth_rate)

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
    # The other three terms of the bridge (see `statements.equity_bridge`). Read from the
    # newest balance-sheet date — a balance sheet is a snapshot, so the latest
    # one is the company's current financial position, where the FCF above is a
    # flow across a year.
    bal = f["balance_sheet"]
    bridge = statements.equity_bridge(bal, sorted(bal)[-1] if bal else None)
    # One figure, subtracted everywhere EV is turned into equity. There are four
    # such places — the headline below, the WACC x terminal-growth grid, the
    # growth sweep and the normalised base year — and they must agree, or the
    # sensitivity table would contradict the headline printed above it.
    # `associates_at_cost` is deliberately absent: it is reported, not adopted.
    bridge_deduction = (net_debt + bridge["minority_interest"]
                        + bridge["preferred"] - bridge["marked_securities"])
    equity_value = ev - bridge_deduction
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
    # `conversion` below is FCF/EBITDA, both reporting-currency and so already
    # unit-free. The traded multiple is not: it needs restating onto one
    # currency first, or `k` carries the FX rate into the solve. On 0700.HK the
    # uncorrected figure moved this diagnostic from 5.46% to 5.89%.
    current_multiple, _ = ev_multiples_for(info)
    if ebitda and ebitda > 0 and current_multiple and current_multiple > 0:
        conversion = fcf / ebitda
        if conversion > 0:
            k = current_multiple / conversion
            market_implied_growth = round((k * wacc - 1) / (1 + k), 4)

    # `rf + spread` is exactly how `_wacc` builds it (see its
    # `cost_of_debt` line); recomputing it here from the two published
    # parts keeps the flag below checkable against numbers already on
    # screen rather than resting on a figure nobody can see.
    cost_of_debt_pre_tax = (wacc_parts["risk_free_rate"]
                            + wacc_parts["credit_spread"])

    sensitivity = []
    for dw in (-0.01, -0.005, 0.0, 0.005, 0.01):
        row = {"wacc": round(wacc + dw, 4), "values": []}
        for dg in (-0.005, -0.0025, 0.0, 0.0025, 0.005):
            w, g = wacc + dw, terminal_growth + dg
            if w <= g or not shares:
                row["values"].append(None)
            else:
                row["values"].append(
                    round((enterprise_value(w, g) - bridge_deduction) * conv / shares, 2))
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
        round((enterprise_value(wacc, terminal_growth, g) - bridge_deduction) * conv / shares, 2)
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
            (enterprise_value(wacc, terminal_growth, base=normalised_fcff) - bridge_deduction)
            * conv / shares, 2)

    # The fourth bridge term, reported and not adopted. Associates are carried at
    # cost, and cost is neither a market value nor a floor — a long-held stake is
    # usually worth more than it cost and an impaired one less, and the filing
    # does not say which. Shown for the same reason the normalised base year is:
    # the reader can see the size of what the platform declines to decide.
    # `+ 0.0` normalises the negative zero that -(0.0) produces, which would
    # otherwise render as "-0.00" on a row that is simply not there.
    per_share = ((lambda x: round(x * conv / shares, 2) + 0.0) if shares
                 else (lambda x: None))
    bridge_out = {
        **bridge,
        "net_debt": net_debt,
        "deduction": bridge_deduction,
        "per_share": {k: per_share(v) for k, v in
                      (("minority_interest", -bridge["minority_interest"]),
                       ("preferred", -bridge["preferred"]),
                       ("marked_securities", bridge["marked_securities"]),
                       ("associates_at_cost", bridge["associates_at_cost"]))},
        "fair_value_including_associates": (
            per_share(ev - bridge_deduction + bridge["associates_at_cost"])
            if shares and bridge["associates_at_cost"] else None),
    }

    return {
        "assumptions": {
            "base_fcf": fcf,
            "fcf_source": fcf_source,
            "fcf_period": statement[0] if statement else None,
            # 0.0 with a basis of anything but "cash_interest_paid" means the
            # figure above is still levered — see statements.fcff_interest_addback.
            "fcf_interest_addback": round(interest_addback),
            "fcff_basis": fcff_basis,
            # Subtracted from the figure above, not added. A basis of
            # "not_reported" means the issuer disclosed no SBC row, which is
            # different from disclosing zero — see statements.sbc_expense.
            "fcf_sbc": round(sbc),
            "sbc_basis": sbc_basis,
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
            # The price's own provenance. It is the denominator of the headline
            # upside and was the only input on this screen carrying none, while
            # beta, FCF, the premium and the FX rate all state theirs. Both
            # figures come from the vendor rather than being assumed: measured on
            # 0700.HK 2026-08-14, `exchangeDataDelayedBy` was 15 and
            # `regularMarketTime` sat exactly 15.0 minutes behind the clock.
            "price_as_of": info.get("regularMarketTime"),
            "price_delayed_by_minutes": info.get("exchangeDataDelayedBy"),
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
            # How much room the perpetuity has. The terminal value is
            # `1 / (WACC - g)` times the final year's cash flow, so the answer
            # scales as the reciprocal of this number and its sensitivity to a
            # WACC error as the reciprocal *squared* — which is why a spread
            # deserves to be read, not just the share above it.
            #
            # Published rather than thresholded, the same choice made for the
            # beta regression's R² and interval on 2026-08-17 (e): a reader can
            # weigh a narrow spread, and no cutoff between "fine" and "fragile"
            # has any evidence behind it. Measured on `0002_HK` 2026-08-26,
            # 2.76% at the US proxy rate against 1.12% at Hong Kong's own — a
            # 50bp WACC error is worth 21% of the share price at the first and
            # 55% at the second.
            "terminal_spread": round(wacc - terminal_growth, 4),
            # Equity priced below debt, which cannot be true of the same
            # company: a lender is senior to a shareholder, so a share cannot
            # require less return than the bond that outranks it.
            #
            # CAPM produces it anyway whenever `beta x ERP` comes in under the
            # credit spread. On `0002_HK` that is 0.1544 x 5.01% = 77bp against
            # an 85bp spread, so the cost of equity lands 7bp *under* the
            # pre-tax cost of debt — and it does so at either risk-free rate,
            # because both legs move with the rate together. Pre-existing, and
            # invisible until now.
            #
            # This is an inequality between two computed inputs, not a tuned
            # cutoff, which is why it can be flagged without inventing a
            # threshold. Reported and never corrected: ordering the two would be
            # a modelling change, and it belongs with the open CAPM question in
            # TODOLIST rather than here.
            "cost_of_debt_pre_tax": round(cost_of_debt_pre_tax, 4),
            "cost_of_equity_below_debt": wacc_parts["cost_of_equity"] < cost_of_debt_pre_tax,
            "implied_exit_ev_ebitda": implied_exit_multiple,
            # The implied exit above is built from statement figures and is
            # already reporting-currency throughout, so the multiple it is read
            # against has to be on one currency too — the panel divides one by
            # the other. Uncorrected, 0700.HK showed 44.6% implied compression
            # where the like-for-like figure is 39.1%.
            "current_ev_ebitda": current_multiple,
            # what perpetual growth today's price already assumes, and whether
            # that is more than an economy grows
            "market_implied_terminal_growth": market_implied_growth,
            "market_implied_growth_high": (market_implied_growth is not None
                                           and market_implied_growth > NOMINAL_GDP_GROWTH),
            "nominal_gdp_growth": NOMINAL_GDP_GROWTH,
            # empty is the healthy case: both legs of the bridge were reported
            "net_debt_assumed_zero": net_debt_assumed,
            "equity_bridge": bridge_out,
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


# ─────────────────────────────────────────────────────────────────────────────
# Excess return model — banks and insurers
#
# `CFO - CapEx` is not a cash flow for a bank. Deposits and wholesale borrowing
# are not capital raised to fund reinvestment, they are the raw material the
# business buys and reprocesses into loans, so the balance-sheet accounts that
# dominate the cash flow statement swing by billions for reasons unrelated to
# either growth or maintenance. There is no meaningful capex line either: a
# bank's PP&E is branches and IT, a rounding error against its balance sheet.
# Measured on the JPM fixture 2026-08-29, `Gross PPE` is 36.2bn against
# `Total Assets` of 4,424.9bn — 0.8%.
#
# So the model values equity directly, off book value, which for a bank is a
# far more meaningful number than for an industrial: financial-instrument
# assets are marked to market far more than plant is, and book equity *is*
# regulatory capital, so falling below a threshold has operating consequences
# rather than being an accounting artefact.
#
#     Value of equity = Book value today + PV(expected excess returns)
#     Excess return_t = (ROE - cost of equity) x Book value_t
#
# which is the Damodaran/residual-income form. It is arithmetically the same
# claim a dividend discount model makes about the same company; it just tells
# the story in terms of the spread over cost of equity rather than in terms of
# the payout, which is what makes the assumption inspectable.
DIVIDEND_PAID_ROWS = ("Cash Dividends Paid", "Common Stock Dividend Paid",
                      "Cash Dividend Paid")

# The grid sweeps the two inputs the answer is most sensitive to. Wider on ROE
# than the DCF's terminal-growth steps because ROE genuinely moves that much:
# JPM's own four reported years span 3.96 points, so a +/-2-point sweep is
# narrower than this company's recent history rather than a hypothetical.
EXCESS_ROE_STEPS = (-0.02, -0.01, 0.0, 0.01, 0.02)
EXCESS_KE_STEPS = (-0.01, -0.005, 0.0, 0.005, 0.01)

# A retention ratio outside this band is not a retention ratio. It is the same
# shape of guard as GROWTH_VALIDITY_RANGE above and exists for the same reason:
# a figure either passes and is used exactly as measured, or fails and is
# rejected rather than quietly clamped into something plausible-looking.
RETENTION_VALIDITY_RANGE = (-1.0, 1.0)

# Net income and book equity live in two different statements, so the pairing
# `statements.paired_latest` enforces inside one statement has to be done here.
# The discipline is the same and the reason is the same: a ratio is only a ratio
# when both legs describe one period.
COMMON_EQUITY_ROWS = ("Common Stock Equity",)
COMMON_INCOME_ROWS = ("Net Income Common Stockholders", "Net Income")


def roe_history(f: dict) -> list[dict]:
    """Return on *common* equity per reported period, oldest first.

    Common rather than total, and that distinction is not cosmetic for the one
    company type this model exists for. Measured on the JPM fixture 2026-08-29:
    `Stockholders Equity` is 362.4bn and `Common Stock Equity` 342.4bn, the
    20.0bn difference being preferred stock. Dividing `Net Income Common
    Stockholders` by the larger figure charges the common shareholder for a
    claim that is not theirs and reports 15.36% where the answer is 16.26% —
    and yfinance's own `returnOnEquity` for that fixture, 17.79%, sits nearer
    the common figure than the total one, which is the third reading that
    settles it.

    Both legs are read from the same period or the period is skipped. Two
    independent `statements.latest` calls would happily pair this year's income
    with an older balance sheet, which is the bug `paired_latest` exists to
    stop within a statement — it cannot help across two.
    """
    out = []
    for period in sorted(f.get("balance_sheet", {})):
        equity = statements.value_at(f["balance_sheet"], period, *COMMON_EQUITY_ROWS)
        income = statements.value_at(f.get("income_statement", {}), period,
                                     *COMMON_INCOME_ROWS)
        if equity is None or income is None or equity <= 0:
            continue
        out.append({"period": period, "equity": equity, "net_income": income,
                    "roe": income / equity})
    return out


def _normalised_payout(f: dict, history: list[dict]) -> tuple[float | None, int]:
    """(mean payout ratio, periods averaged) across years that earned a profit.

    Averaged for the same reason ROE is, and refused on a loss year for a
    sharper one. A payout ratio measured against negative earnings is not a
    small number, it is a *negative* number, and `1 - payout` then exceeds one
    and drives book value growth above anything the company could earn.

    Found in adversarial review 2026-08-29, on the JPM fixture with only the
    newest year's net income changed and the real dividend held:

        net income   payout    retention   growth      fair value/share
          55.7bn      0.299      0.701      11.09%              338.32
         -30.0bn     -0.554      1.554      14.84%              158.96
          -5.0bn     -3.325      4.325      49.19%              452.82
          -1.0bn    -16.625     17.625     205.61%           23,718.76
          -0.001bn  -16,625     16,626    195,172%             1.19e28

    which is not a hypothetical for the one sector this model serves: a bank
    that takes a provisioning loss and keeps paying its dividend is 2008 and
    2020 both. The valuation diverged with no refusal, no clamp and no flag —
    the first draft guarded the equity leg of the ratio and not the income one.
    """
    cash_flow = f.get("cash_flow", {}) or {}
    ratios = []
    for period in history:
        if period["net_income"] <= 0:
            continue
        dividends = statements.value_at(cash_flow, period["period"],
                                        *DIVIDEND_PAID_ROWS)
        if not dividends:
            continue
        ratios.append(abs(dividends) / period["net_income"])
    if not ratios:
        return None, 0
    return sum(ratios) / len(ratios), len(ratios)


def _excess_return_project(book: float, roe: float, ke: float, g: float,
                           g_term: float) -> tuple[float, float, list[dict]]:
    """(PV of explicit excess returns, PV of terminal excess return, the path).

    Book value compounds at `g` along the same two-stage fade the DCF uses for
    cash flow, so the two models make the same shape of claim about how fast the
    explicit period converges on the terminal one. ROE is held flat: see
    `excess_returns_valuation` for why that is stated rather than assumed away.

    At module level for the same reason `_project` is — so the arithmetic can be
    tested without running a whole valuation.
    """
    pv = 0.0
    equity = book
    path = []
    for year, growth in enumerate(_growth_path(g, g_term), start=1):
        # The excess is earned *on the equity in place at the start of the
        # year*, then that equity grows by the retained portion. Compounding
        # first would credit the year with capital it had not yet retained.
        excess = (roe - ke) * equity
        discounted = excess / (1 + ke) ** year
        pv += discounted
        path.append({"year": year, "opening_equity": round(equity, 2),
                     "growth": round(growth, 6), "excess_return": round(excess, 2),
                     "present_value": round(discounted, 2)})
        equity *= (1 + growth)
    terminal = (roe - ke) * equity / (ke - g_term)
    return pv, terminal / (1 + ke) ** PROJECTION_YEARS, path


def excess_returns_valuation(f: dict, roe: float | None = None,
                             terminal_growth: float | None = None,
                             cost_of_equity_override: float | None = None,
                             tax_rate: float | None = None,
                             peers: list[dict] | None = None,
                             market_bars: tuple[list[dict], list[dict]] | None = None
                             ) -> dict:
    """Two-stage excess return valuation, for company types a DCF cannot value.

    Returns the same envelope `dcf_valuation` does — `assumptions`,
    `equity_value`, `fair_value_per_share`, `current_price`, `upside_pct`,
    `diagnostics`, and two sensitivity grids — or `{"error": ...}` on the same
    single-key convention. It deliberately does **not** return `enterprise_value`
    or `net_debt`: this model reaches equity directly rather than bridging to it,
    and reporting an EV it never computed would invite a comparison that does
    not exist.

    **ROE is normalised across the reported periods rather than taken from the
    newest one.** Loan-loss provisioning is procyclical and, under CECL,
    forward-looking, so a single year is a reserve-build or a reserve-release as
    much as it is a run rate. Measured on the JPM fixture 2026-08-29, reported
    ROE runs 13.55 / 15.89 / 17.51 / 16.26% across four years — a 3.96-point
    spread — and feeding the newest of those into a perpetuity is a 4-point
    error compounded forever. The mean is the headline; the newest year's own
    fair value is reported beside it in `diagnostics.fair_value_latest_roe`,
    which is the same "show both, choose neither" treatment `base_year_context`
    gives the DCF's base year.

    **ROE is held flat rather than faded toward the cost of equity**, and that
    is the single largest assumption here. Competition and regulation should
    erode a spread over cost of equity, and a model that assumes today's ROE
    survives forever is assuming the moat does too. Fading it was the
    alternative, and it was rejected because the fade rate would be a constant
    nothing in this repository can calibrate — the same reason the beta
    regression publishes its R-squared instead of applying a "fit too weak"
    threshold. What the model does instead is print the assumption:
    `diagnostics.excess_spread` is the permanent gap being claimed, and
    `diagnostics.implied_terminal_payout` is the payout ratio the terminal phase
    requires for that ROE and that growth to be mutually consistent. On JPM
    those read 7.14 points and 84.2% against a current payout of 29.9%, which is
    a stance a reader can disagree with rather than one buried in the arithmetic.

    Terminal growth is capped exactly as the DCF caps it, and for a measured
    reason rather than a tidy one: retention growth for a profitable bank
    routinely exceeds its own cost of equity. On JPM, `ROE x (1 - payout)` is
    11.09% against a cost of equity of 8.66%, so an uncapped Gordon terminal
    value is negative — not large, *negative*. The explicit stage still grows at
    the retention rate; only the perpetuity is held under the same two ceilings
    `dcf_valuation` documents at length.
    """
    info = f.get("info", {}) or {}
    history = roe_history(f)
    if not history:
        # One refusal, not two. A negative-equity issuer reaches here rather
        # than a separate guard further down, because `roe_history` already
        # drops those periods — return on equity is undefined on negative
        # equity, and a negative-equity issuer with a negative net income
        # reports a spuriously *positive* one. So an empty history means either
        # the rows are missing or the equity is not something this model can
        # start from, and the message has to name both.
        return {"error": "No period reports positive common equity together with "
                         "net income, so return on equity cannot be measured — "
                         "excess return model not applicable. A negative-equity "
                         "issuer is an option on recovering solvency rather than "
                         "a going concern earning a stable spread."}

    book = history[-1]["equity"]
    roes = [h["roe"] for h in history]
    roe_normalised = sum(roes) / len(roes)
    roe_latest = roes[-1]
    roe_source = "user"
    if roe is None:
        roe, roe_source = roe_normalised, "normalised_mean"

    tax_rate = tax_rate_for(info) if tax_rate is None else tax_rate
    wacc_parts = _wacc(f, tax_rate, peers, market_bars)
    ke = wacc_parts["cost_of_equity"] if cost_of_equity_override is None \
        else cost_of_equity_override
    ke_source = "capm" if cost_of_equity_override is None else "user"

    # Retention growth for the explicit stage. Dividends paid is the cash-flow
    # figure rather than `info["payoutRatio"]`, which yfinance reports against a
    # trailing net income this model does not otherwise use. The row name is not
    # stable across issuers — the JPM fixture reports `Cash Dividends Paid` and
    # the O fixture `Common Stock Dividend Paid` — which is what the multi-name
    # fallback in `statements.latest` is for.
    payout, payout_periods = _normalised_payout(f, history)
    if payout is None:
        return {"error": "No period reports a dividend against positive earnings, "
                         "so the retention ratio that drives book-value growth "
                         "cannot be measured — excess return model not applicable."}
    retention = 1 - payout
    if not RETENTION_VALIDITY_RANGE[0] <= retention <= RETENTION_VALIDITY_RANGE[1]:
        return {"error": f"Retention ratio of {retention:.1%} is outside "
                         f"{RETENTION_VALIDITY_RANGE[0]:.0%} to "
                         f"{RETENTION_VALIDITY_RANGE[1]:.0%} — the payout figure "
                         "is not describing a payout, so the growth it implies "
                         "cannot be used."}
    growth = roe * retention
    growth_source = "roe_x_retention"

    terminal_growth_source = "user"
    if terminal_growth is None:
        rf_cap = wacc_parts["risk_free_rate"]
        terminal_growth = min(TERMINAL_GROWTH, rf_cap)
        terminal_growth_source = ("platform_default" if terminal_growth == TERMINAL_GROWTH
                                  else "capped_at_risk_free_rate")

    if ke <= terminal_growth:
        return {"error": f"Cost of equity ({ke:.2%}) must exceed terminal growth "
                         f"({terminal_growth:.2%})."}

    pv_explicit, pv_terminal, path = _excess_return_project(
        book, roe, ke, growth, terminal_growth)
    equity_value = book + pv_explicit + pv_terminal

    # Book equity and net income are statement figures; price and share count
    # are traded ones. Converted once, here, exactly as `dcf_valuation` does —
    # and when no rate can be had the comparison is withheld rather than made
    # across two units.
    shares = info.get("sharesOutstanding")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    fx, fx_mismatch = _to_trading(info)
    fx_basis = ("single_currency" if not fx_mismatch
                else "converted" if fx is not None else "rate_unavailable")
    conv = fx if fx is not None else 1.0
    fair_value = equity_value * conv / shares if shares else None
    comparable = fair_value and price and fx_basis != "rate_unavailable"

    def _fair_value_at(r: float, k: float | None = None) -> float | None:
        """Fair value per share at an alternative ROE and cost of equity.

        Everything else is held, including the retention ratio — so a swept ROE
        moves the growth rate with it, which is the honest coupling: retention
        growth *is* a function of ROE and pinning one while sweeping the other
        would show a company that reinvests at a rate it does not earn.
        """
        k = ke if k is None else k
        if not shares or k <= terminal_growth:
            return None
        g = r * retention if retention is not None else r
        pv_e, pv_t, _ = _excess_return_project(book, r, k, g, terminal_growth)
        return round((book + pv_e + pv_t) * conv / shares, 2)

    # Pinned to the period `book` came from rather than read with `latest`,
    # which walks backward independently. A tangible-book figure from an older
    # year over this year's equity is the same mispairing `paired_latest` exists
    # to stop — found in adversarial review 2026-08-29, where dropping the row
    # from the newest JPM period silently produced 0.7598 from two fiscal years.
    tangible = statements.value_at(f.get("balance_sheet", {}),
                                   history[-1]["period"], "Tangible Book Value")

    return {
        "assumptions": {
            "book_value_of_equity": book,
            "book_value_period": history[-1]["period"],
            "book_value_basis": "common_stock_equity",
            "roe": roe,
            "roe_source": roe_source,
            "roe_normalised": roe_normalised,
            "roe_latest": roe_latest,
            "roe_periods": len(history),
            "payout_ratio": payout,
            "payout_periods": payout_periods,
            "retention_ratio": retention,
            "growth_rate_explicit": growth,
            "growth_source": growth_source,
            "terminal_growth": terminal_growth,
            "terminal_growth_source": terminal_growth_source,
            "terminal_growth_anchor": TERMINAL_GROWTH,
            "terminal_growth_ceilings": {
                "nominal_gdp_growth": NOMINAL_GDP_GROWTH,
                "risk_free_rate": wacc_parts["risk_free_rate"],
            },
            "cost_of_equity_used": ke,
            "cost_of_equity_source": ke_source,
            "tax_rate": tax_rate,
            "projection_years": PROJECTION_YEARS,
            "stage1_years": STAGE1_YEARS,
            "stage2_years": STAGE2_YEARS,
            **wacc_parts,
            "currency": info.get("currency"),
            "reporting_currency": info.get("financialCurrency"),
            "fx_basis": fx_basis,
            "fx_rate_used": round(fx, 6) if fx_mismatch and fx is not None else None,
        },
        "book_value_of_equity": book,
        "excess_return_pv": round(pv_explicit, 2),
        "terminal_value_pv": round(pv_terminal, 2),
        "equity_value": round(equity_value, 2),
        "fair_value_per_share": round(fair_value, 2) if fair_value else None,
        "current_price": price,
        "upside_pct": round((fair_value / price - 1) * 100, 1) if comparable else None,
        "diagnostics": {
            "roe_history": [{"period": h["period"], "roe": round(h["roe"], 6)}
                            for h in history],
            "roe_vendor_reported": info.get("returnOnEquity"),
            # The whole assumption, in one number: the spread this model claims
            # the company earns over its cost of equity, forever.
            "excess_spread": round(roe - ke, 6),
            # And what that spread costs to sustain. Growth needs retention, so
            # a terminal phase growing at g while earning ROE can only pay out
            # what is left: 1 - g/ROE. Where that is far from today's payout,
            # the model is quietly assuming a change in policy.
            "implied_terminal_payout": round(1 - terminal_growth / roe, 6) if roe else None,
            "current_payout": round(payout, 6) if payout is not None else None,
            "terminal_value_share": round(pv_terminal / equity_value, 6) if equity_value else None,
            "terminal_value_high": bool(equity_value and pv_terminal / equity_value > 0.75),
            "book_value_per_share": round(book * conv / shares, 2) if shares else None,
            # Gated on the same condition `upside_pct` is: price is a traded
            # figure and book a statement one, so without a rate this is two
            # currencies over each other. Left ungated in the first draft.
            "price_to_book": round(price * shares / (book * conv), 3)
                             if comparable and shares and price and book else None,
            # The newest year's own answer, beside the normalised one, chosen
            # neither way — the same treatment the DCF's base year gets.
            "fair_value_latest_roe": _fair_value_at(roe_latest),
            "fair_value_normalised_roe": _fair_value_at(roe_normalised),
            # Book value is the starting point, so how much of it is goodwill
            # rather than tangible capital is part of reading the answer. The
            # mark-to-market assumption that makes book meaningful for a bank
            # does not extend to intangibles.
            "tangible_book_value": tangible,
            "tangible_share_of_book": round(tangible / book, 4) if tangible and book else None,
            "projection": path,
        },
        # ROE against cost of equity, because those are the two inputs the
        # answer is most sensitive to and the two a reader is most likely to
        # disagree with. The DCF's grid sweeps WACC against terminal growth for
        # the same reason.
        "sensitivity": {
            "roe_cols": [round(roe + dr, 6) for dr in EXCESS_ROE_STEPS],
            "rows": [{"cost_of_equity": round(ke + dk, 6),
                      "values": [_fair_value_at(roe + dr, ke + dk)
                                 for dr in EXCESS_ROE_STEPS]}
                     for dk in EXCESS_KE_STEPS],
        },
        "roe_sensitivity": {
            "roe_values": [round(roe + dr, 6) for dr in EXCESS_ROE_STEPS],
            "values": [_fair_value_at(roe + dr) for dr in EXCESS_ROE_STEPS],
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
        ocf = statements.value_at(cf, p, "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities")
        capex = statements.value_at(cf, p, "Capital Expenditure")
        net_income = statements.value_at(inc, p, "Net Income")
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

    ocf = statements.value_at(cf, period, "Operating Cash Flow",
                    "Cash Flow From Continuing Operating Activities")
    capex = statements.value_at(cf, period, "Capital Expenditure")
    wc = statements.value_at(cf, period, "Change In Working Capital")
    normal_wc = median([w for p in cf if p != period
                        and (w := statements.value_at(cf, p, "Change In Working Capital")) is not None]
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
           "latest_sbc_margin": None, "mean_sbc_margin": None,
           "normalised_statement_fcf": None, "latest_revenue": None,
           "driver": None, "driver_note": None,
           "capex_delta": None, "operating_delta": None}
    cf, inc = f.get("cash_flow") or {}, f.get("income_statement") or {}
    if not period or period not in cf:
        return out

    # Held unrounded, and rounded once on the way out. Every statistic below is
    # a mean over these, so rounding first would let a display artefact compound
    # across periods and then show up as a panel whose columns do not add up.
    raw = []   # (period, fcf margin, operating cash margin, capex intensity, sbc)
    for p in sorted(cf):
        revenue = statements.value_at(inc, p, "Total Revenue", "Operating Revenue")
        ocf = statements.value_at(cf, p, "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities")
        capex = statements.value_at(cf, p, "Capital Expenditure")
        if not revenue or ocf is None or capex is None:
            continue
        # SBC is carried as its own leg rather than netted into `fcf_margin`.
        # That margin is pinned to the identity `CFO/rev - capex/rev` with no
        # residual, which is what lets the panel say "spending more" rather than
        # "earning less" without assuming anything; folding a third term into it
        # would turn the attribution back into a guess. A period that reports no
        # SBC row contributes 0.0, the same as statements.sbc_expense.
        sbc_p = statements.value_at(cf, p, "Stock Based Compensation")
        # capex is reported negative; carried as the positive intensity a reader
        # expects, which is why the identity below subtracts it
        raw.append((p, (ocf + capex) / revenue, ocf / revenue, -capex / revenue,
                    abs(sbc_p) / revenue if sbc_p else 0.0))

    # Two periods cannot establish what is normal, so no band is offered rather
    # than one built on a single comparison.
    if len(raw) < 3 or raw[-1][0] != period:
        return out

    out["history"] = [{"period": p, "fcf_margin": round(fcf_m, 4),
                       "operating_margin_cash": round(ocf_m, 4),
                       "capex_to_revenue": round(capex_i, 4),
                       "sbc_to_revenue": round(sbc_m, 4)}
                      for p, fcf_m, ocf_m, capex_i, sbc_m in raw]

    margins = [r[1] for r in raw]
    sbc_margins = [r[4] for r in raw]
    latest, mean_margin = margins[-1], sum(margins) / len(margins)
    mean_sbc = sum(sbc_margins) / len(sbc_margins)
    out.update(periods=len(margins),
               latest_fcf_margin=round(latest, 4),
               mean_fcf_margin=round(mean_margin, 4),
               latest_sbc_margin=round(sbc_margins[-1], 4),
               mean_sbc_margin=round(mean_sbc, 4),
               ratio_to_mean=round(latest / mean_margin, 3) if mean_margin else None)

    # Scale by the latest revenue, not by an averaged one. Revenue is the least
    # volatile and most audited line on the statement, so normalising the ratio
    # while holding the company's current size fixed changes one thing. Averaging
    # absolute past free cash flow instead would anchor to a smaller company and
    # is wrong for any grower — measured, it moves MSFT only 1.06x against the
    # 1.29x its own margin history supports.
    revenue = statements.value_at(inc, period, "Total Revenue", "Operating Revenue")
    out["latest_revenue"] = revenue
    if revenue:
        # Net of the *mean* SBC margin, not the newest one. The question this
        # figure answers is "what if this year were the company's own normal
        # year", and a normal year carries a normal SBC charge. Netting the
        # latest instead would normalise one leg and hold the other at whatever
        # the base year happened to do, which is the inconsistency the whole
        # panel exists to expose.
        out["normalised_statement_fcf"] = round((mean_margin - mean_sbc) * revenue)

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
                         rising: bool = True,
                         market_bars: tuple[list[dict], list[dict]] | None = None
                         ) -> float | None:
    """The value of `param` at which the DCF's fair value equals `target_value`.

    Fair value is monotone in each of the three assumptions the model exposes —
    rising in growth and terminal growth, falling in WACC — so a bisection is
    exact enough and needs no derivative. `rising` says which.

    Returns None when the target lies outside what `param` can reach inside
    `[lo, hi]`. That is a result, not a failure: "no rate in this band gets you
    there" is exactly what makes a gap irreconcilable rather than merely large.
    """
    def fair_value(x: float):
        out = dcf_valuation(f, peers=peers, market_bars=market_bars, **{param: x})
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
            for p, v in statements.series(f["income_statement"], "Total Revenue")]


def _classify(f: dict) -> str:
    """This company's profile, from the statement-verified free cash flow.

    `info["freeCashflow"]` is reported annually for some issuers and quarterly
    for others, so `classify` asks for the figure the caller already verified —
    see its docstring. Kept here so `full_analysis` and the comps endpoint
    cannot drift into classifying the same company differently.
    """
    statement = statements.statement_fcf(f.get("cash_flow", {}))
    return sector_weights.classify(f["info"], statement[1] if statement else None)


def full_analysis(f: dict, peers: list[dict] | None = None,
                  market_bars: tuple[list[dict], list[dict]] | None = None) -> dict:
    return {
        "ticker": f["ticker"],
        "company": {k: f["info"].get(k) for k in
                    ["longName", "sector", "industry", "currency", "marketCap",
                     "targetMeanPrice", "recommendationKey", "numberOfAnalystOpinions"]},
        "ratios": ratio_analysis(f),
        "dcf": dcf_valuation(f, peers=peers, market_bars=market_bars),
        # Alongside `dcf`, never in place of it. The Financial Models tab reads
        # `dcf` for a panel built entirely on WACC, terminal growth and an
        # equity bridge; handing it an excess-return result under that key would
        # have it call a residual-income number a DCF, print "NaN" into the WACC
        # box, and crash on `sensitivity.terminal_growth_cols`. Separate keys
        # keep the existing panel correct and untouched.
        #
        # Gated on the classification, the same way the comps endpoint gates it,
        # and the gate is the whole point rather than an optimisation. The model
        # runs happily on an ordinary industrial and the answer is nonsense:
        # buybacks leave AAPL with 73.7bn of book equity against its earnings,
        # so return on equity reads 167% and the fair value comes out at
        # 10,249.75 against a price of 311. Arithmetically right, categorically
        # wrong — and shipping it in the payload unguarded is a number waiting
        # for a future panel to render it. Measured 2026-08-29.
        "excess_return": (
            excess_returns_valuation(f, peers=peers, market_bars=market_bars)
            if sector_weights.valuation_model_for(_classify(f)) == "excess_return"
            else None),
        "revenue_trend": revenue_trend(f),
    }
