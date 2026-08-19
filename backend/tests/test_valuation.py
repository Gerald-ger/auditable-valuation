"""Valuation-engine behaviour: beta resolution, credit spread, two-stage
projection, jurisdiction tax and the DCF trust diagnostics.

These cover the pure logic. The one part that is not pure — fetching peer betas
when a reported beta is implausible — is wired in main.py and smoke-tested live,
because pulling the network into this suite would defeat its purpose.
"""
from __future__ import annotations

import copy
import math

import pytest

from conftest import (FIXTURES, TEST_CNY_HKD, load_bars, load_fundamentals,
                      load_market_bars)

from backend import data_provider
from backend import financial_models as fm
from backend import statements


# ── beta resolution (item 1) ─────────────────────────────────────────

def _peer(beta, debt=None, market_cap=None):
    """A peer snapshot as data_provider.get_peer_snapshot returns it.

    debt/market_cap default to None so a test opts in to the unlever path only
    when it means to — without leverage, resolve_beta uses the levered median.
    """
    return {"beta": beta, "total_debt": debt, "market_cap": market_cap}


def test_credible_reported_beta_is_kept_and_peers_ignored():
    beta, source = fm.resolve_beta({"beta": 1.09}, [_peer(0.8), _peer(0.9)])
    assert (beta, source) == (1.09, "reported")


@pytest.mark.parametrize("bad", [0.173, 0.0, -0.5, 3.4, None])
def test_implausible_beta_falls_back_to_peer_median(bad):
    """yfinance reported 0.173 for XOM, which swung its DCF upside ~79 points."""
    beta, source = fm.resolve_beta({"beta": bad},
                                   [_peer(0.85), _peer(0.95), _peer(1.05)])
    assert source == "peer_median"
    assert beta == pytest.approx(0.95)


def test_peer_betas_are_themselves_filtered_for_credibility():
    beta, source = fm.resolve_beta(
        {"beta": 0.1}, [_peer(0.2), _peer(0.9), _peer(1.1), _peer(4.0)])
    assert source == "peer_median"
    assert beta == pytest.approx(1.0), "implausible peers must not enter the median"


def test_a_single_surviving_peer_is_not_treated_as_a_median():
    """XOM's real peer set: CVX 0.488, COP 0.123, SHEL -0.218, BP -0.212.
    Only one clears the credibility band, and it is still implausible for an oil
    major — yfinance's betas are broken sector-wide here, not just for XOM."""
    beta, source = fm.resolve_beta(
        {"beta": 0.173},
        [_peer(0.488), _peer(0.123), _peer(-0.218), _peer(-0.212)])
    assert source == "default"
    assert beta == fm.BETA_FALLBACK


def test_no_credible_beta_anywhere_falls_back_to_one():
    assert fm.resolve_beta({"beta": None}, []) == (fm.BETA_FALLBACK, "default")
    assert fm.resolve_beta({}, None) == (fm.BETA_FALLBACK, "default")


# ── unlever / re-lever (reference doc §1.1.2) ────────────────────────

def test_peer_betas_are_unlevered_and_relevered_to_the_target():
    """A levered peer beta carries the peer's balance sheet, not the target's.

    Peers are levered 1.0x D/E with beta 1.10; the target is debt-free, so the
    substituted beta must be the *asset* beta, below the peers' levered median.
        Bu = 1.10 / (1 + 0.79 * 1.0) = 0.6145 ; target D/E = 0 -> Bl = 0.6145
    """
    peers = [_peer(1.10, debt=100.0, market_cap=100.0),
             _peer(1.10, debt=50.0, market_cap=50.0)]
    beta, source = fm.resolve_beta(
        {"beta": None, "totalDebt": 0.0, "marketCap": 1000.0}, peers, tax_rate=0.21)
    assert source == "peer_median_relevered"
    assert beta == pytest.approx(0.6145, abs=1e-4)
    assert beta < 1.10, "an unlevered target must not inherit the peers' leverage"


def test_relevering_raises_beta_for_a_more_levered_target():
    peers = [_peer(1.0, debt=0.0, market_cap=100.0),
             _peer(1.0, debt=0.0, market_cap=100.0)]
    lo, _ = fm.resolve_beta({"totalDebt": 0.0, "marketCap": 100.0}, peers, 0.21)
    hi, _ = fm.resolve_beta({"totalDebt": 100.0, "marketCap": 100.0}, peers, 0.21)
    assert hi > lo, "more leverage is more equity risk"
    assert hi == pytest.approx(1.79, abs=1e-4)


def test_relevered_beta_is_held_inside_the_credibility_band():
    """A very levered target must not re-lever its way out of the band."""
    peers = [_peer(2.0, debt=0.0, market_cap=100.0),
             _peer(2.0, debt=0.0, market_cap=100.0)]
    beta, source = fm.resolve_beta(
        {"totalDebt": 900.0, "marketCap": 100.0}, peers, 0.21)
    assert source == "peer_median_relevered"
    assert beta == fm.BETA_MAX


def test_unknown_peer_leverage_degrades_to_the_levered_median():
    """Unlevering needs each peer's own D/E; without it, the old path stands."""
    beta, source = fm.resolve_beta(
        {"beta": None, "totalDebt": 0.0, "marketCap": 100.0},
        [_peer(0.9), _peer(1.1)], 0.21)
    assert source == "peer_median"
    assert beta == pytest.approx(1.0)


def test_unknown_target_leverage_degrades_to_the_levered_median():
    beta, source = fm.resolve_beta(
        {"beta": None},  # no totalDebt / marketCap
        [_peer(0.9, 10.0, 100.0), _peer(1.1, 10.0, 100.0)], 0.21)
    assert source == "peer_median"
    assert beta == pytest.approx(1.0)


def test_xom_reported_beta_is_replaced_by_the_peer_median(monkeypatch):
    """The whole point of item 1: yfinance's 0.173 made XOM look cheap."""
    f = load_fundamentals("XOM")
    assert f["info"]["beta"] < fm.BETA_MIN, "fixture must still exercise this path"

    a = fm.dcf_valuation(f, peers=[_peer(0.85), _peer(0.9), _peer(1.0), _peer(0.95)])["assumptions"]
    assert a["beta_source"] == "peer_median"
    assert a["beta"] == pytest.approx(0.925)
    assert a["beta_reported"] == pytest.approx(0.173), "the raw value stays auditable"

    no_peers = fm.dcf_valuation(f)["assumptions"]
    assert no_peers["beta_source"] == "default"
    assert no_peers["beta"] == fm.BETA_FALLBACK


@pytest.mark.parametrize("stem", ["XOM", "AAPL"])
def test_fair_value_falls_as_beta_rises(stem, monkeypatch):
    """The invariant the 0.173 reading violated: more risk cannot be worth more."""
    f = load_fundamentals(stem)
    # peers only take effect when the reported beta is not credible
    f["info"]["beta"] = 0.0
    values = [
        fm.dcf_valuation(f, peers=[_peer(b), _peer(b)])["fair_value_per_share"]
        for b in (0.4, 0.8, 1.2, 1.6)
    ]
    assert values == sorted(values, reverse=True), values


# ── credit spread ladder (item 4) ────────────────────────────────────

def _with_coverage(ebit, interest):
    return {"income_statement": {"2025-12-31": {"EBIT": ebit, "Interest Expense": interest}}}


@pytest.mark.parametrize("ebit,interest,expected", [
    (130.0, 10.0, 0.006),    # 13.0x -> investment grade
    (90.0, 10.0, 0.0085),    # 9.0x
    (50.0, 10.0, 0.014),     # 5.0x
    (25.0, 10.0, 0.030),     # 2.5x
    (10.0, 10.0, 0.070),     # 1.0x -> distressed
])
def test_credit_spread_tracks_interest_coverage(ebit, interest, expected):
    spread, coverage, period = fm._credit_spread(_with_coverage(ebit, interest))
    assert spread == expected
    assert coverage == pytest.approx(ebit / interest)
    assert period == "2025-12-31"


def test_credit_spread_defaults_when_coverage_is_unavailable():
    assert fm._credit_spread({"income_statement": {}}) == (fm.DEFAULT_CREDIT_SPREAD, None, None)


# ── both legs of a ratio must come from one period ───────────────────
#
# `_latest` walks back until it finds anything, so two independent calls will
# pair this year's numerator with a years-old denominator. Measured on the AAPL
# fixture 2026-08-10: EBIT resolved 2025-09-30 while Interest Expense resolved
# 2023-09-30 (yfinance stopped reporting the row), giving a displayed interest
# coverage of 33.83x built from two different businesses. Pinned, it reads 29.06x
# for 2023-09-30 — both score 100, so no composite moved and the goldens cannot
# police this.

def test_interest_coverage_never_crosses_two_periods():
    income = {"2025-12-31": {"EBIT": 500.0},                        # no interest row
              "2023-12-31": {"EBIT": 300.0, "Interest Expense": 10.0}}
    coverage, period = statements.interest_coverage(income)
    assert period == "2023-12-31"
    assert coverage == pytest.approx(30.0)        # 300/10, not 500/10


def test_interest_coverage_prefers_the_newest_complete_period():
    income = {"2025-12-31": {"EBIT": 500.0, "Interest Expense": 10.0},
              "2023-12-31": {"EBIT": 300.0, "Interest Expense": 10.0}}
    assert statements.interest_coverage(income) == (pytest.approx(50.0), "2025-12-31")


def test_interest_coverage_is_none_when_no_period_reports_both():
    assert statements.interest_coverage({"2025-12-31": {"EBIT": 500.0}}) == (None, None)


def test_aapl_interest_coverage_reads_one_year(monkeypatch):
    """The fixture this was found on. The pinned period is stale — yfinance has
    not reported AAPL's interest since 2023 — but stale-and-consistent is a
    ratio, and fresh-over-stale is not."""
    f = load_fundamentals("AAPL")
    coverage, period = statements.interest_coverage(f["income_statement"])
    assert period == "2023-09-30"
    ebit = statements.value_at(f["income_statement"], period, "EBIT", "Operating Income")
    interest = statements.value_at(f["income_statement"], period, "Interest Expense")
    assert coverage == pytest.approx(ebit / abs(interest))
    # the ratio the two-call version produced, for the record
    assert coverage != pytest.approx(
        statements.latest(f["income_statement"], "EBIT", "Operating Income") / abs(interest))


def test_ratio_analysis_reports_the_period_its_coverage_came_from():
    ratios = fm.ratio_analysis(load_fundamentals("AAPL"))
    assert ratios["solvency"]["interest_coverage_period"] == "2023-09-30"


# ── a missing bridge leg is named, not silently zeroed ───────────────

def test_net_debt_names_the_leg_it_had_to_assume(monkeypatch):
    """`or 0` keeps the DCF working when one field is absent, but an unreported
    totalDebt otherwise reads as a debt-free company: AAPL 143.99 -> 147.41."""
    f = load_fundamentals("AAPL")
    assert fm.dcf_valuation(f)["diagnostics"]["net_debt_assumed_zero"] == []

    f["info"]["totalDebt"] = None
    assert fm.dcf_valuation(f)["diagnostics"]["net_debt_assumed_zero"] == ["total_debt"]


def test_both_missing_bridge_legs_are_named(monkeypatch):
    f = load_fundamentals("AAPL")
    f["info"]["totalDebt"] = f["info"]["totalCash"] = None
    diagnostics = fm.dcf_valuation(f)["diagnostics"]
    assert diagnostics["net_debt_assumed_zero"] == ["total_debt", "total_cash"]


# ── statements and shares can be in different currencies ─────────────
#
# 0700.HK reports CNY and trades HKD (verified live 2026-08-10; 9988.HK and
# 1810.HK the same). The DCF builds enterprise value from statement cash flows
# and bridges with totalDebt/totalCash, which follow the statements — then
# compared the result against a trading-currency price. Unconverted, upside read
# +30.5%; converted at the pinned test rate of 1.10 it reads +44.5%.
#
# The FX rate is pinned in conftest, so these assert the plumbing, not a quote.

def test_a_cross_currency_dcf_is_quoted_in_the_trading_currency():
    f = load_fundamentals("0700_HK")
    dcf = fm.dcf_valuation(f)
    a = dcf["assumptions"]
    assert (a["currency"], a["reporting_currency"]) == ("HKD", "CNY")
    assert a["fx_basis"] == "converted"
    assert a["fx_rate_used"] == pytest.approx(TEST_CNY_HKD)


def test_conversion_scales_the_valuation_by_exactly_the_rate():
    """Fair value, EV and equity value all move together; nothing is left behind
    in the reporting currency.

    WACC is pinned on both sides because conversion is *not* a pure scaling:
    the capital-structure weights compare a trading-currency market cap against a
    reporting-currency debt balance, so correcting that legitimately moves the
    discount rate too (0700.HK 7.69% -> 7.66%). Holding it fixed isolates the one
    thing under test here.

    **Terminal growth has to be pinned as well, since 2026-08-19.** `wacc_override`
    used to be enough because both variants shared one risk-free rate. They no
    longer do: the CNY side is priced off the CGB curve and the HKD side off the
    US proxy, and the rate drives `min(TERMINAL_GROWTH, rf)` as well as the WACC —
    which `wacc_override` does not reach. Left unpinned the two sides run
    different terminal growth and the scaling identity fails for a reason that
    has nothing to do with FX.
    """
    f = load_fundamentals("0700_HK")
    # same company, told its statements are already in HKD -> no conversion
    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"

    wacc = fm.dcf_valuation(g)["assumptions"]["wacc_used"]
    pins = {"wacc_override": wacc, "terminal_growth": 0.025}
    converted = fm.dcf_valuation(f, **pins)
    unconverted = fm.dcf_valuation(g, **pins)

    assert unconverted["assumptions"]["fx_basis"] == "single_currency"
    for key in ("fair_value_per_share", "enterprise_value", "equity_value"):
        assert converted[key] == pytest.approx(
            unconverted[key] * TEST_CNY_HKD, rel=1e-3), key


def test_correcting_the_currency_also_corrects_the_wacc_weights():
    """The other half: a reporting-currency debt balance weighed against a
    trading-currency market cap understated the debt weight, and with it the
    share of the cheaper after-tax cost of debt.

    The ERP is pinned across both runs. `financialCurrency` now carries a second
    job — it also selects the market premium — so flipping it to build the mixed
    case would move the cost of equity too, and this test would stop measuring
    the weighting effect it is named for.
    """
    f = load_fundamentals("0700_HK")
    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fm, "equity_risk_premium_for", lambda c: (0.05, "test", None))
        corrected = fm.dcf_valuation(f)["assumptions"]
        mixed = fm.dcf_valuation(g)["assumptions"]
    assert corrected["weight_equity"] < mixed["weight_equity"]
    assert corrected["wacc"] < mixed["wacc"]


def test_conversion_leaves_the_unit_free_diagnostics_alone():
    """Terminal share and the implied exit multiple divide two reporting-currency
    figures, so scaling them would reintroduce the very mismatch being removed.

    The WACC is compared separately: its capital-structure weights *do* change,
    because they weigh a trading-currency market cap against a reporting-currency
    debt balance and that comparison was mixed before.

    Terminal growth is pinned alongside the WACC for the reason given in
    `test_conversion_scales_the_valuation_by_exactly_the_rate`: the two variants
    now draw their risk-free rate from different curves, and the rate sets the
    growth ceiling as well as the discount rate.
    """
    f = load_fundamentals("0700_HK")
    converted = fm.dcf_valuation(f)

    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"
    unconverted = fm.dcf_valuation(g, terminal_growth=0.025)

    # hold WACC and the growth ceiling fixed so only the conversion is under test
    same_wacc = fm.dcf_valuation(f, terminal_growth=0.025,
                                 wacc_override=unconverted["assumptions"]["wacc_used"])
    for key in ("terminal_value_share", "implied_exit_ev_ebitda"):
        assert same_wacc["diagnostics"][key] == pytest.approx(
            unconverted["diagnostics"][key], rel=1e-6), key
    assert converted["diagnostics"]["terminal_value_share"] is not None


def test_the_sensitivity_grid_is_converted_with_everything_else():
    """A grid left in the reporting currency would put the football field's DCF
    bar in one unit and the price rule in another."""
    f = load_fundamentals("0700_HK")
    dcf = fm.dcf_valuation(f)
    grid = [v for row in dcf["sensitivity"]["rows"] for v in row["values"] if v is not None]
    assert min(grid) < dcf["fair_value_per_share"] < max(grid)
    assert dcf["fair_value_per_share"] > 600   # HKD; the CNY figure was 628 -> 695


def test_upside_is_withheld_when_no_rate_can_be_fetched(monkeypatch):
    """The comparison, not the valuation, is what breaks without a rate — so the
    fair value is still reported and only the cross-currency claim is dropped."""
    monkeypatch.setattr(fm, "fx_rate", lambda a, b: 1.0 if a == b else None)
    dcf = fm.dcf_valuation(load_fundamentals("0700_HK"))
    assert dcf["assumptions"]["fx_basis"] == "rate_unavailable"
    assert dcf["assumptions"]["fx_rate_used"] is None
    assert dcf["upside_pct"] is None
    assert dcf["fair_value_per_share"] is not None


def test_a_single_currency_issuer_is_untouched_by_any_of_this(monkeypatch):
    """No rate is even looked up, so a currency outage cannot affect a US name."""
    def explode(a, b):
        raise AssertionError(f"looked up {a}/{b} for a single-currency issuer")
    monkeypatch.setattr(fm, "fx_rate", explode)
    dcf = fm.dcf_valuation(load_fundamentals("AAPL"))
    assert dcf["assumptions"]["fx_basis"] == "single_currency"
    # 143.99 under the old 5-year growth plateau; 129.29 once the explicit stage
    # matched the one-year horizon of the consensus that feeds it; 141.17 once
    # the US premium was Damodaran's published 4.46% rather than a flat 5%;
    # 146.49 now that the equity bridge adds AAPL's marked investment securities
    assert dcf["fair_value_per_share"] == pytest.approx(146.49, rel=1e-3)


def test_peer_leverage_is_put_on_one_basis_before_unlevering():
    """A peer's debt is reporting-currency and its market cap trading-currency,
    so its D/E needs the peer's own rate — not the target's."""
    hk_peer = {"beta": 1.2, "market_cap": 1_000.0 * TEST_CNY_HKD, "total_debt": 1_000.0,
               "currency": "HKD", "financial_currency": "CNY"}
    us_peer = {"beta": 1.2, "market_cap": 1_000.0, "total_debt": 1_000.0,
               "currency": "USD", "financial_currency": "USD"}
    # same true leverage (1.0x) once both are on one basis, so same unlevered beta
    info = {"beta": None, "totalDebt": 1_000.0, "marketCap": 1_000.0,
            "currency": "USD", "financialCurrency": "USD"}
    from_hk = fm.resolve_beta(info, [hk_peer, hk_peer])
    from_us = fm.resolve_beta(info, [us_peer, us_peer])
    assert from_hk == from_us
    assert from_hk[1] == "peer_median_relevered"


def test_credit_spread_differentiates_real_companies(monkeypatch):
    """Previously every company paid an identical flat +1.5%."""
    spreads = {}
    for stem in ("AAPL", "MSFT", "XOM", "O"):
        spreads[stem] = fm._credit_spread(load_fundamentals(stem))[0]
    assert len(set(spreads.values())) > 1, f"still flat across issuers: {spreads}"
    # O (REIT, ~2.0x coverage) must not be charged the same as MSFT (~55x)
    assert spreads["O"] > spreads["MSFT"]


# ── two-stage projection (item 3) ────────────────────────────────────

def test_growth_path_is_flat_then_fades_to_terminal():
    path = fm._growth_path(0.20, 0.025)
    assert len(path) == fm.PROJECTION_YEARS == 10
    assert path[:fm.STAGE1_YEARS] == [0.20] * fm.STAGE1_YEARS
    assert path[-1] == pytest.approx(0.025), "final year must reach terminal growth"
    fade = path[fm.STAGE1_YEARS:]
    assert fade == sorted(fade, reverse=True), "stage 2 must decline monotonically"


# The projection arithmetic itself. Until `_project` was lifted out of
# `dcf_valuation` this loop was a closure, so every one of the ~70 tests that
# reached it did so by running a whole valuation over a fixture — which pins the
# answer for seven companies and pins the *arithmetic* for none. These do the
# opposite: no fundamentals, no fixtures, just the identities the model claims.

def test_projection_discounts_a_flat_cash_flow_to_its_closed_form():
    """Zero growth throughout reduces the whole model to a textbook perpetuity."""
    w, fcf = 0.10, 100.0
    pv, terminal_pv, growth_factor = fm._project(fcf, 0.0, w, 0.0)

    assert pv == sum(fcf / (1 + w) ** y for y in range(1, fm.PROJECTION_YEARS + 1))
    assert terminal_pv == (fcf / w) / (1 + w) ** fm.PROJECTION_YEARS
    assert growth_factor == 1.0, "nothing grew, so the base year must not scale"
    # And the two legs together are exactly what a no-growth perpetuity is worth.
    assert pv + terminal_pv == pytest.approx(fcf / w)


def test_projection_is_homogeneous_of_degree_one_in_the_base():
    """`_project`'s docstring claims the base override "scales the result exactly
    and nothing damps it". `dcf_valuation` relies on that when it prices the
    normalised base year, so the claim is load-bearing rather than descriptive."""
    args = (0.12, 0.10, 0.025)  # growth, wacc, terminal
    assert fm._enterprise_value(200.0, *args) == 2 * fm._enterprise_value(100.0, *args)
    assert (fm._enterprise_value(100.0, *args, base=700.0)
            == 2 * fm._enterprise_value(100.0, *args, base=350.0))


def test_a_base_override_replaces_the_reported_cash_flow_entirely():
    # The normalised base-year valuation would otherwise blend two base years.
    args = (0.12, 0.10, 0.025)
    assert (fm._enterprise_value(1.0, *args, base=350.0)
            == fm._enterprise_value(999.0, *args, base=350.0))


def test_a_growth_override_replaces_the_starting_rate_entirely():
    # What makes the growth sensitivity a sweep of one assumption rather than a
    # blend of two.
    swept = fm._project(100.0, 0.12, 0.10, 0.025, g_start=0.30)
    assert swept == fm._project(100.0, 0.30, 0.10, 0.025)


def test_the_growth_factor_is_the_compounded_path():
    """The implied exit multiple divides by this, so it has to be the product of
    the path rather than the final year's rate."""
    growth, terminal = 0.12, 0.025
    _, _, growth_factor = fm._project(100.0, growth, 0.10, terminal)
    assert growth_factor == math.prod(1 + g for g in fm._growth_path(growth, terminal))


def test_enterprise_value_is_the_sum_of_the_two_legs():
    pv, terminal_pv, _ = fm._project(100.0, 0.12, 0.10, 0.025)
    assert fm._enterprise_value(100.0, 0.12, 0.10, 0.025) == pv + terminal_pv


def test_two_stage_raises_valuation_versus_a_single_five_year_fade(monkeypatch):
    """A durable compounder gets more than five years before the fade starts."""
    f = load_fundamentals("MSFT")
    ten_year = fm.dcf_valuation(f)

    monkeypatch.setattr(fm, "STAGE1_YEARS", 1)
    monkeypatch.setattr(fm, "STAGE2_YEARS", 4)
    monkeypatch.setattr(fm, "PROJECTION_YEARS", 5)
    five_year = fm.dcf_valuation(f)

    assert ten_year["fair_value_per_share"] > five_year["fair_value_per_share"]


# ── trust diagnostics (items 2 and 6) ────────────────────────────────

@pytest.mark.parametrize("stem", ["AAPL", "MSFT", "XOM", "0700_HK"])
def test_dcf_reports_terminal_share_and_implied_exit_multiple(stem, monkeypatch):
    d = fm.dcf_valuation(load_fundamentals(stem))
    diag = d["diagnostics"]
    assert 0 < diag["terminal_value_share"] < 1
    assert diag["terminal_value_high"] == (diag["terminal_value_share"] > 0.75)
    assert diag["implied_exit_ev_ebitda"] > 0


def test_terminal_share_rises_as_wacc_approaches_terminal_growth(monkeypatch):
    f = load_fundamentals("AAPL")
    tight = fm.dcf_valuation(f, wacc_override=0.05)["diagnostics"]["terminal_value_share"]
    wide = fm.dcf_valuation(f, wacc_override=0.12)["diagnostics"]["terminal_value_share"]
    assert tight > wide


def test_implied_exit_multiple_is_absent_without_ebitda(monkeypatch):
    f = load_fundamentals("AAPL")
    f["info"]["ebitda"] = None
    assert fm.dcf_valuation(f)["diagnostics"]["implied_exit_ev_ebitda"] is None


@pytest.mark.parametrize("stem", ["AAPL", "MSFT", "XOM", "0700_HK", "O"])
def test_market_implied_growth_reproduces_the_traded_multiple(stem, monkeypatch):
    """The exit-multiple check run backwards, and the direction that answers a
    question: what perpetual growth does today's price already assume?

    It has to invert the forward diagnostic exactly, or the number is a
    decoration. Feeding the solved rate back through
    `conv x (1+g)/(WACC-g)` must land on the traded multiple.
    """
    f = load_fundamentals(stem)
    d = fm.dcf_valuation(f)
    diag, a = d["diagnostics"], d["assumptions"]

    g = diag["market_implied_terminal_growth"]
    conversion = a["base_fcf"] / f["info"]["ebitda"]
    round_trip = conversion * (1 + g) / (a["wacc"] - g)

    assert round_trip == pytest.approx(diag["current_ev_ebitda"], rel=0.01)
    assert g < a["wacc"]


def test_market_implied_growth_is_flagged_against_nominal_gdp(monkeypatch):
    """Measured 2026-08-12: AAPL's price needs 7.30% perpetual free-cash-flow
    growth, above the ~4% an economy grows; 0700.HK needs 3.23% and does not.
    That difference is the whole point of the flag — it separates 'the market is
    pricing supernormal growth' from 'the DCF disagrees about the forecast'."""
    aapl = fm.dcf_valuation(load_fundamentals("AAPL"))["diagnostics"]
    tencent = fm.dcf_valuation(load_fundamentals("0700_HK"))["diagnostics"]

    assert aapl["market_implied_terminal_growth"] > fm.NOMINAL_GDP_GROWTH
    assert aapl["market_implied_growth_high"] is True
    assert tencent["market_implied_terminal_growth"] < fm.NOMINAL_GDP_GROWTH
    assert tencent["market_implied_growth_high"] is False
    assert aapl["nominal_gdp_growth"] == fm.NOMINAL_GDP_GROWTH


def test_a_negative_consensus_is_used_rather_than_floored_at_zero(monkeypatch):
    """A company forecast to shrink must be modelled as shrinking.

    XOM's consensus is **-1.9%**. Flooring that to 0% grew a declining company at
    zero and inflated its fair value by 15.7% (75.30 against 66.65 on this
    fixture) — an *overstatement*, which is the dangerous direction for a
    valuation tool. The ceiling stays, because erring there produces
    conservatism; the floor is now only a data-validity bound.
    """
    f = load_fundamentals("XOM")
    d = fm.dcf_valuation(f)
    a = d["assumptions"]

    assert a["growth_rate_published"] < 0
    assert a["growth_rate_year1"] == a["growth_rate_published"]   # used, not floored
    assert fm.reconcile_to_price(f, d)["growth_input_substituted"] is False


def test_an_implausible_consensus_is_rejected_not_truncated(monkeypatch):
    """The distinction the whole design turns on.

    Truncation substitutes a number no source produced (25%) and the reader
    cannot trace. Rejection discards the bad figure, falls back to the next
    source, and says so — provenance survives. A consensus of 900% is corrupt
    data; one of 42.6% from 55 analysts is not, and the model must tell them
    apart rather than capping both.
    """
    f = load_fundamentals("AAPL")
    f["estimates"] = {"revenue_growth_fwd": 9.0}
    f["info"]["revenueGrowth"] = 0.08
    a = fm.dcf_valuation(f)["assumptions"]

    assert a["growth_source"] == "consensus_rejected_implausible"
    assert a["growth_rate_year1"] == pytest.approx(0.08)   # fell back, not capped
    assert a["growth_rate_published"] == 9.0               # and the rejected figure survives


def test_a_high_but_credible_consensus_is_used_as_published(monkeypatch):
    """NVDA's 42.6% from 55 analysts and AMD's 72.1% are observations, not noise.
    The old 25% ceiling truncated both, which produced the whole of NVDA's
    -58.7% verdict."""
    f = load_fundamentals("AAPL")
    f["estimates"] = {"revenue_growth_fwd": 0.7212}
    a = fm.dcf_valuation(f)["assumptions"]

    assert a["growth_source"] == "analyst_consensus_fwd"
    assert a["growth_rate_year1"] == pytest.approx(0.7212)


def test_the_explicit_stage_matches_the_horizon_of_its_input(monkeypatch):
    """The consensus forecasts one year, so it is applied for one year. Holding
    it flat for five invented four years nobody forecast — on AMD's 72.1% that
    compounded free cash flow 15.1x before any fade began."""
    assert fm.STAGE1_YEARS == 1
    assert fm.STAGE1_YEARS + fm.STAGE2_YEARS == fm.PROJECTION_YEARS == 10
    path = fm._growth_path(0.4257, 0.025)
    assert path[0] == pytest.approx(0.4257)      # year 1 as forecast
    assert path[1] < path[0]                     # and decaying from year 2
    assert path[-1] == pytest.approx(0.025)


def test_a_synthesised_default_growth_is_not_reported_as_measured(monkeypatch):
    """With no consensus and no trailing figure the model falls back to 5%. That
    number was previously labelled `trailing_revenue_growth` — indistinguishable
    downstream from a figure somebody actually measured, which is the silent
    assumption the platform is meant not to make."""
    f = load_fundamentals("AAPL")
    f["estimates"] = {}
    f["info"]["revenueGrowth"] = None
    a = fm.dcf_valuation(f)["assumptions"]

    assert a["growth_rate_year1"] == fm.DEFAULT_GROWTH_RATE
    assert a["growth_source"] == "default_assumed"


def test_each_growth_provenance_gets_its_own_label(monkeypatch):
    f = load_fundamentals("AAPL")
    f["estimates"] = {"revenue_growth_fwd": 0.11}
    assert fm.dcf_valuation(f)["assumptions"]["growth_source"] == "analyst_consensus_fwd"

    f["estimates"] = {}
    f["info"]["revenueGrowth"] = 0.07
    assert fm.dcf_valuation(f)["assumptions"]["growth_source"] == "trailing_revenue_growth"


def test_a_reconcilable_gap_names_the_assumption_that_closes_it(monkeypatch):
    """0700.HK's DCF sits above the price and the model can still name what would
    close it. That is a forecast disagreement, and saying so is different from
    saying the market is wrong.

    **Which assumption closes it changed on 2026-08-19**, and the change is the
    finding rather than a break. On the US proxy the gap shut on the *terminal*
    rate (-0.78%, below what an economy grows). Priced off the CGB curve the gap
    is far wider, no terminal rate inside the model's own band reaches it — so
    `required_terminal_growth` is `None`, which is the documented way of saying
    exactly that — and the reconciliation falls through to the near-term leg,
    where roughly -9.6% closes it.

    The verdict is unchanged and that is the point: the platform still refuses to
    call the market wrong, it has simply moved which forecast it is disagreeing
    about.
    """
    f = load_fundamentals("0700_HK")
    r = fm.reconcile_to_price(f, fm.dcf_valuation(f))
    assert r["verdict"] == "reconcilable"
    assert r["required_terminal_growth"] is None
    assert r["required_growth_rate"] < 0
    assert fm.GROWTH_VALIDITY_RANGE[0] <= r["required_growth_rate"]


@pytest.mark.parametrize("stem", ["AAPL", "MSFT"])
def test_an_irreconcilable_gap_says_so_rather_than_blaming_the_company(stem, monkeypatch):
    """Measured 2026-08-13 at a 4.3% risk-free rate: AAPL needs 6.87% terminal
    growth or 24.06% near-term to meet its price — the first above what an
    economy grows, the second two and a half times its own 9.74% consensus.
    Neither is defensible, so the honest reading is that a perpetuity cannot
    express what the market is pricing, not that the stock is expensive.

    Note the second leg is *reachable* (it sits inside the model's 0-25% band)
    and still not *plausible*. Testing reachability alone flipped this verdict on
    a 42bp move in the risk-free rate; testing it against consensus holds it
    steady from 4.0% to 5.2%.
    """
    f = load_fundamentals(stem)
    d = fm.dcf_valuation(f)
    r = fm.reconcile_to_price(f, d)

    assert r["verdict"] == "irreconcilable"
    assert r["required_terminal_growth"] > fm.NOMINAL_GDP_GROWTH
    g1 = r["required_growth_rate"]
    consensus = d["assumptions"]["growth_rate_year1"]
    assert g1 is None or g1 > consensus * fm.GROWTH_PLAUSIBILITY_FACTOR


def test_the_verdict_does_not_flip_on_a_small_move_in_the_risk_free_rate(monkeypatch):
    """A classification that changes when the 10Y moves 40bp is not a
    classification. Judging the near-term leg against the model's guardrail did
    exactly that on AAPL; judging it against consensus does not."""
    f = load_fundamentals("AAPL")
    verdicts = set()
    for rate in (0.040, 0.043, 0.0472, 0.052):
        monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda v=rate: v)
        verdicts.add(fm.reconcile_to_price(f, fm.dcf_valuation(f))["verdict"])
    assert verdicts == {"irreconcilable"}


def test_a_small_gap_is_left_alone(monkeypatch):
    """Within 10% there is no binding assumption to name, and naming one would
    be reading noise."""
    f = load_fundamentals("AAPL")
    d = fm.dcf_valuation(f)
    d["current_price"] = d["fair_value_per_share"] * 1.04
    r = fm.reconcile_to_price(f, d)
    assert r["verdict"] == "aligned"
    assert r["required_terminal_growth"] is None


def test_the_back_solver_returns_none_outside_its_reachable_band(monkeypatch):
    """The generalised solver underneath both back-solves. 'No rate in this band
    gets you there' is the result that makes a gap irreconcilable."""
    f = load_fundamentals("AAPL")
    assert fm.solve_for_fair_value(f, 1e9, "growth_rate", 0.0, 0.25) is None
    hit = fm.solve_for_fair_value(
        f, fm.dcf_valuation(f, growth_rate=0.12)["fair_value_per_share"],
        "growth_rate", 0.0, 0.25)
    assert hit == pytest.approx(0.12, abs=0.002)


def test_the_base_fcf_bridge_is_auditable_and_sums(monkeypatch):
    """Every row is a filed line item, and they must add up to the figure shown.

    The bridge is built instead of a median of past free cash flows on purpose:
    a median is a statistical smear the reader cannot decompose, while each term
    here can be looked up in the filing. Under a no-hidden-adjustments rule the
    more transparent construction wins even though it looks more aggressive.
    """
    q = fm.dcf_valuation(load_fundamentals("MSFT"))["diagnostics"]["base_fcf_quality"]

    assert q["anomalous"] is True
    assert sum(r["value"] for r in q["bridge"]) == pytest.approx(q["normalised_fcf"], abs=2)


def test_a_normalised_base_never_replaces_the_reported_one(monkeypatch):
    """The platform can detect an anomaly but cannot read the notes to identify
    its cause, so the adjustment stays an alternative shown beside the headline.
    Substituting it would be exactly the silent correction the design forbids."""
    f = load_fundamentals("MSFT")
    d = fm.dcf_valuation(f)
    reported = statements.statement_fcf(f["cash_flow"])[1]
    q = d["diagnostics"]["base_fcf_quality"]

    assert q["normalised_fcf"] != reported          # an alternative exists
    assert d["assumptions"]["base_fcf"] >= reported  # ...and the DCF did not use it
    assert d["assumptions"]["base_fcf"] - reported == d["assumptions"]["fcf_interest_addback"]


def test_growth_alone_does_not_trip_the_base_anomaly_detector(monkeypatch):
    """Cash conversion is the trigger, not the level of free cash flow. Measured
    2026-08-13, an FCF-vs-own-median test fired on NVDA (+120%) and AMD (+144%)
    where nothing was wrong; both sit inside 8% on conversion."""
    f = load_fundamentals("AAPL")
    # triple the newest year's cash flow and earnings together: the business got
    # bigger, its conversion did not change, so nothing should be flagged
    newest = sorted(f["cash_flow"])[-1]
    for row in ("Operating Cash Flow", "Capital Expenditure"):
        if f["cash_flow"][newest].get(row) is not None:
            f["cash_flow"][newest][row] *= 3
    if f["income_statement"].get(newest, {}).get("Net Income") is not None:
        f["income_statement"][newest]["Net Income"] *= 3

    assert fm.base_fcf_quality(f, newest)["anomalous"] is False


def test_a_base_anomaly_needs_at_least_two_comparison_years(monkeypatch):
    """One prior year is not a history, and a reference drawn from it would be
    an opinion rather than a measurement."""
    f = load_fundamentals("MSFT")
    periods = sorted(f["cash_flow"], reverse=True)
    f["cash_flow"] = {p: f["cash_flow"][p] for p in periods[:2]}
    q = fm.base_fcf_quality(f, periods[0])
    assert q["anomalous"] is False and q["deviation"] is None


def test_market_implied_growth_is_absent_without_a_traded_multiple(monkeypatch):
    """No multiple, no question to ask — and a fabricated one would be worse
    than silence, the same rule the exit multiple above follows."""
    f = load_fundamentals("AAPL")
    f["info"]["enterpriseToEbitda"] = None
    diag = fm.dcf_valuation(f)["diagnostics"]
    assert diag["market_implied_terminal_growth"] is None
    assert diag["market_implied_growth_high"] is False


# ── jurisdiction tax (item 8) ────────────────────────────────────────

def test_tax_rate_follows_the_listing_currency():
    assert fm.tax_rate_for({"currency": "HKD"}) == 0.165
    assert fm.tax_rate_for({"currency": "USD"}) == 0.21
    assert fm.tax_rate_for({"currency": "EUR"}) == fm.DEFAULT_TAX_RATE
    assert fm.tax_rate_for({}) == fm.DEFAULT_TAX_RATE


def test_a_reit_is_not_charged_corporation_tax():
    """A REIT deducts what it distributes, so there is no shield to price. Its
    own statements agree: O reports 85.3m of tax on 1,155m of pre-tax income,
    an effective 7.4%, and that residual is its taxable subsidiaries rather than
    the trust. The exception is structural, so it keys on the classification
    rather than on the currency the listing happens to trade in."""
    f = load_fundamentals("O")
    assert f["info"]["currency"] == "USD"          # would otherwise be 21%
    assert fm.tax_rate_for(f["info"]) == 0.0

    inc = f["income_statement"][sorted(f["income_statement"])[-1]]
    effective = inc["Tax Provision"] / inc["Pretax Income"]
    assert effective < 0.10, "fixture no longer shows a REIT-like effective rate"


def test_only_the_reit_moved(monkeypatch):
    """The exception must not leak into anything else. Every other fixture keeps
    the rate its listing currency implies."""
    expected = {"AAPL": 0.21, "MSFT": 0.21, "XOM": 0.21, "JPM": 0.21,
                "RIVN": 0.21, "0700_HK": 0.165, "0002_HK": 0.165, "O": 0.0}
    # "Every other fixture" has to mean every one. This list is hand-written
    # where test_scoring and test_fixtures parametrize over `sorted(FIXTURES)`
    # and pick a new name up for free, so it silently covered 7 of 8 the moment
    # an eighth arrived. The assertion below closes that.
    assert set(expected) == set(FIXTURES)
    for stem, rate in expected.items():
        assert fm.tax_rate_for(load_fundamentals(stem)["info"]) == rate, stem


def test_charging_a_reit_tax_understated_its_cost_of_capital(monkeypatch):
    """The reason the exception is worth having: the shield it wrongly granted
    was the difference between a 6.05% and a 6.58% WACC on the committed
    fixture, and a fair value of 36.00 against 27.04."""
    f = load_fundamentals("O")
    now = fm.dcf_valuation(f)
    charged = fm.dcf_valuation(f, tax_rate=0.21)
    assert now["assumptions"]["wacc"] > charged["assumptions"]["wacc"]
    assert now["fair_value_per_share"] < charged["fair_value_per_share"]


def test_hk_listing_uses_the_hk_rate(monkeypatch):
    d = fm.dcf_valuation(load_fundamentals("0700_HK"))
    assert d["assumptions"]["tax_rate"] == 0.165


def test_explicit_tax_rate_still_overrides(monkeypatch):
    d = fm.dcf_valuation(load_fundamentals("0700_HK"), tax_rate=0.30)
    assert d["assumptions"]["tax_rate"] == 0.30


# ── period pinning (item 5) ──────────────────────────────────────────

def test_statement_fcf_returns_the_period_it_used():
    period, fcf = statements.statement_fcf(load_fundamentals("MSFT")["cash_flow"])
    assert period == "2026-06-30"
    assert fcf == pytest.approx(66_987_000_000.0)


def test_statement_fcf_requires_both_legs_in_one_period():
    cash_flow = {
        "2025-12-31": {"Operating Cash Flow": 100.0},               # no CapEx
        "2024-12-31": {"Operating Cash Flow": 90.0, "Capital Expenditure": -30.0},
    }
    assert statements.statement_fcf(cash_flow) == ("2024-12-31", 60.0)


def test_value_at_does_not_reach_into_another_period():
    statement = {"2025-12-31": {"Net Income": 100.0}, "2024-12-31": {"Net Income": 90.0}}
    assert statements.value_at(statement, "2025-12-31", "Net Income") == 100.0
    assert statements.value_at(statement, "2023-12-31", "Net Income") is None


def test_dcf_reports_the_fcf_period(monkeypatch):
    d = fm.dcf_valuation(load_fundamentals("AAPL"))
    assert d["assumptions"]["fcf_period"] == "2025-09-30"
    assert d["assumptions"]["fcf_source"] == "cash_flow_statement"


def test_dcf_still_falls_back_to_info_freecashflow(monkeypatch):
    f = copy.deepcopy(load_fundamentals("AAPL"))
    f["cash_flow"] = {}
    d = fm.dcf_valuation(f)
    assert d["assumptions"]["fcf_source"] == "info_freecashflow"
    assert d["assumptions"]["fcf_period"] is None


# ── FCFF: levered -> unlevered before discounting at WACC ────────────
#
# The golden snapshots cannot police this. XOM's dcf_upside_pct is clipped at the
# -40 anchor floor, so moving it from -53.4% to -50.3% leaves every stored score
# identical. These tests are the only thing standing between a silent change in
# the add-back and a silently different valuation.

def test_interest_in_financing_gets_no_addback():
    """IFRS may classify interest paid as financing, leaving CFO already
    unlevered. 0700.HK does; adding interest back would overstate FCFF."""
    f = load_fundamentals("0700_HK")
    period, _ = statements.statement_fcf(f["cash_flow"])
    addback, basis = statements.fcff_interest_addback(f["cash_flow"], period, 0.165)
    assert (addback, basis) == (0.0, "not_required_interest_in_financing")


def test_us_gaap_cash_interest_is_added_back_after_tax():
    """XOM discloses 1,752M paid in the same period its FCF comes from."""
    f = load_fundamentals("XOM")
    period, _ = statements.statement_fcf(f["cash_flow"])
    addback, basis = statements.fcff_interest_addback(f["cash_flow"], period, 0.21)
    assert basis == "cash_interest_paid"
    assert addback == pytest.approx(1_752_000_000.0 * 0.79)


def test_unverifiable_classification_is_left_alone():
    """MSFT reports no interest row in any captured period. Guessing which side
    of the cash-flow statement it sits on would be worse than not adjusting."""
    f = load_fundamentals("MSFT")
    period, _ = statements.statement_fcf(f["cash_flow"])
    addback, basis = statements.fcff_interest_addback(f["cash_flow"], period, 0.21)
    assert (addback, basis) == (0.0, "unverified_interest_classification")


def test_no_statement_period_means_no_addback():
    """The info["freeCashflow"] fallback has no period to pin interest to."""
    assert statements.fcff_interest_addback({}, None, 0.21) == (0.0, "no_statement_fcf")


def test_addback_uses_magnitude_not_sign():
    cash_flow = {"2025-12-31": {"Interest Paid Supplemental Data": -400.0}}
    addback, _ = statements.fcff_interest_addback(cash_flow, "2025-12-31", 0.25)
    assert addback == pytest.approx(300.0)


def test_financing_classification_wins_over_a_cash_interest_row():
    """If both appear, operating cash flow is still unlevered — do not add back."""
    cash_flow = {"2025-12-31": {"Interest Paid Cff": -400.0,
                                "Interest Paid Supplemental Data": 400.0}}
    assert statements.fcff_interest_addback(cash_flow, "2025-12-31", 0.21)[1] == \
        "not_required_interest_in_financing"


def test_statement_fcf_stays_levered_for_the_scoring_metrics():
    """fcf_yield divides by market cap and fcf_conversion by net income, both of
    which are after interest. Unlevering here would corrupt both."""
    f = load_fundamentals("XOM")
    period, fcf = statements.statement_fcf(f["cash_flow"])
    rows = f["cash_flow"][period]
    assert fcf == pytest.approx(rows["Operating Cash Flow"] + rows["Capital Expenditure"])


def test_dcf_raises_fair_value_when_interest_is_added_back(monkeypatch):
    f = load_fundamentals("XOM")
    with_addback = fm.dcf_valuation(f)

    stripped = copy.deepcopy(f)
    for rows in stripped["cash_flow"].values():
        rows.pop("Interest Paid Supplemental Data", None)
    without = fm.dcf_valuation(stripped)

    assert with_addback["assumptions"]["fcff_basis"] == "cash_interest_paid"
    assert without["assumptions"]["fcff_basis"] == "unverified_interest_classification"
    assert with_addback["fair_value_per_share"] > without["fair_value_per_share"]


def test_dcf_reports_the_addback_it_applied(monkeypatch):
    a = fm.dcf_valuation(load_fundamentals("0700_HK"))["assumptions"]
    assert a["fcf_interest_addback"] == 0
    assert a["fcff_basis"] == "not_required_interest_in_financing"


# ── terminal growth: a policy with visible ceilings ──────────────────

def test_the_terminal_rate_is_the_anchor_when_both_ceilings_are_slack():
    a = fm.dcf_valuation(load_fundamentals("AAPL"))["assumptions"]
    assert a["terminal_growth"] == fm.TERMINAL_GROWTH
    assert a["terminal_growth_source"] == "platform_default"


def test_both_ceilings_are_reported_even_when_neither_binds():
    """A limit the reader cannot see is a limit the reader cannot check."""
    a = fm.dcf_valuation(load_fundamentals("AAPL"))["assumptions"]
    assert a["terminal_growth_ceilings"] == {
        "nominal_gdp_growth": fm.NOMINAL_GDP_GROWTH,
        "risk_free_rate": a["risk_free_rate"],
    }
    assert a["terminal_growth_anchor"] == fm.TERMINAL_GROWTH


def test_a_low_rate_regime_pulls_the_terminal_rate_down(monkeypatch):
    """The case the cap exists for: a 0.60% ten-year, as in 2020.

    A fixed 2.5% there assumes perpetual growth four times what the bond market
    prices. This is the only branch that changes a valuation, so it is the one
    worth pinning.
    """
    # One patch, not two: `pinned_risk_free_rate` reads `fm.RISK_FREE_RATE` when
    # it is called, so moving the constant moves the pinned rate with it.
    monkeypatch.setattr(fm, "RISK_FREE_RATE", 0.006)
    a = fm.dcf_valuation(load_fundamentals("AAPL"))["assumptions"]
    assert a["terminal_growth"] == 0.006
    assert a["terminal_growth_source"] == "capped_at_risk_free_rate"


def test_an_explicit_rate_overrides_both_ceilings():
    """Guards the reconciliation.

    `solve_for_fair_value` sweeps terminal growth far past the ceilings on
    purpose. Capping it there would report the most useful sentence the
    reconciliation produces — "closing this gap needs 7% perpetual growth" — as
    an unreachable target, i.e. as None.
    """
    a = fm.dcf_valuation(load_fundamentals("AAPL"), terminal_growth=0.07)["assumptions"]
    assert a["terminal_growth"] == 0.07
    assert a["terminal_growth_source"] == "user"


def test_the_ceiling_does_not_break_the_back_solve():
    f = load_fundamentals("AAPL")
    dcf = fm.dcf_valuation(f)
    rec = fm.reconcile_to_price(f, dcf)
    required = rec["required_terminal_growth"]
    assert required is not None, "the ceiling has swallowed the reconciliation"
    assert required > fm.NOMINAL_GDP_GROWTH, (
        "AAPL's gap needs perpetual growth above what an economy grows — that "
        "is the finding, and it must survive the cap")


# ── base year: representative, or a bias? ────────────────────────────

@pytest.mark.parametrize("stem", ["AAPL", "MSFT", "XOM", "0700_HK"])
def test_the_margin_decomposition_is_exact(stem):
    """FCF/revenue = CFO/revenue - capex/revenue, with no residual.

    This is what lets the panel say "spending more" rather than "earning less"
    without assuming anything. If the two legs stopped summing to the whole, the
    attribution would be a guess wearing arithmetic's clothes.
    """
    f = load_fundamentals(stem)
    ctx = fm.base_year_context(f, statements.statement_fcf(f["cash_flow"])[0])
    assert ctx["history"], f"{stem} produced no history"
    for h in ctx["history"]:
        assert h["fcf_margin"] == pytest.approx(
            h["operating_margin_cash"] - h["capex_to_revenue"], abs=2e-4), h["period"]


def test_normalisation_moves_names_in_opposite_directions():
    """The anti-tuning property, and the reason this change is defensible.

    A correction that narrowed every gap to price would be a price tracker.
    0700.HK's newest year is *above* its own mean, so normalising moves it down
    while moving MSFT and XOM up. Pinning both directions means a future change
    that quietly made this one-way would fail here.
    """
    def band(stem):
        d = fm.dcf_valuation(load_fundamentals(stem))
        b = d["diagnostics"]["base_year"]
        return d["fair_value_per_share"], b["fair_value_normalised"]

    reported_hk, normalised_hk = band("0700_HK")
    assert normalised_hk < reported_hk, "0700.HK's base year is above its own mean"

    for stem in ("MSFT", "XOM", "AAPL"):
        reported, normalised = band(stem)
        assert normalised > reported, f"{stem}'s base year is below its own mean"


def test_the_band_is_linear_in_the_base_year():
    """Fair value is homogeneous of degree one in base free cash flow, which is
    why a depressed base is a permanent level error rather than a damped one.

    Stated as a test because the whole case for showing the band rests on it.
    """
    f = load_fundamentals("MSFT")
    d = fm.dcf_valuation(f)
    b = d["diagnostics"]["base_year"]
    scale = b["mean_fcf_margin"] / b["latest_fcf_margin"]

    # equity value, not fair value: the net-debt bridge is a constant, so only
    # the enterprise leg scales
    ev_reported = d["enterprise_value"]
    ev_normalised = (b["fair_value_normalised"] * f["info"]["sharesOutstanding"]
                     + d["net_debt"])
    assert ev_normalised / ev_reported == pytest.approx(scale, rel=0.02)


def test_the_driver_separates_spending_more_from_earning_less():
    """MSFT's capex ran 13.3% -> 34.9% of revenue while operating cash held up.
    AAPL's capex barely moved. The label must tell those apart."""
    def driver(stem):
        f = load_fundamentals(stem)
        return fm.base_year_context(f, statements.statement_fcf(f["cash_flow"])[0])["driver"]

    assert driver("MSFT") == "capital_spending"
    assert driver("XOM") == "capital_spending"
    assert driver("AAPL") == "operating_cash"


def test_a_representative_year_names_no_driver():
    """There is nothing to explain when the base year is already normal, and
    naming a driver anyway would invent a story out of rounding."""
    f = load_fundamentals("AAPL")
    period = statements.statement_fcf(f["cash_flow"])[0]
    inc = f["income_statement"]
    # force the newest year onto the mean by rebuilding it from the others
    ctx = fm.base_year_context(f, period)
    others = [h["fcf_margin"] for h in ctx["history"][:-1]]
    target = sum(others) / len(others)
    revenue = inc[period]["Total Revenue"]
    capex = f["cash_flow"][period]["Capital Expenditure"]
    f["cash_flow"][period]["Operating Cash Flow"] = target * revenue - capex

    assert fm.base_year_context(f, period)["driver"] is None


def test_two_periods_offer_no_band():
    """Two observations cannot establish what is normal."""
    f = load_fundamentals("AAPL")
    keep = sorted(f["cash_flow"])[-2:]
    f["cash_flow"] = {k: v for k, v in f["cash_flow"].items() if k in keep}
    ctx = fm.base_year_context(f, keep[-1])
    assert ctx["history"] == []
    assert ctx["normalised_statement_fcf"] is None


def test_the_reported_year_stays_the_headline():
    """The band is shown beside the answer, never substituted for it."""
    f = load_fundamentals("MSFT")
    d = fm.dcf_valuation(f)
    statement_fcf = statements.statement_fcf(f["cash_flow"])[1]
    assert d["assumptions"]["base_fcf"] == statement_fcf + d["assumptions"]["fcf_interest_addback"]
    assert d["diagnostics"]["base_year"]["fair_value_normalised"] != d["fair_value_per_share"]


def test_the_decomposition_reconciles_against_the_average_on_screen():
    """One baseline, not two.

    The panel shows a table of years, an average, a ratio, and two legs. All
    four have to be computable from each other or the reader cannot check any of
    them: latest margin minus the stated average must equal the operating leg
    minus the capital leg, exactly.
    """
    for stem in ("MSFT", "XOM", "AAPL", "0700_HK"):
        f = load_fundamentals(stem)
        ctx = fm.base_year_context(f, statements.statement_fcf(f["cash_flow"])[0])
        gap = ctx["latest_fcf_margin"] - ctx["mean_fcf_margin"]
        # The identity is exact on the underlying figures. Four of them are
        # rounded to 4dp for display, so the reconciliation of the *published*
        # numbers carries up to 2e-4 — a hundredth of a percentage point, below
        # anything the panel prints.
        assert gap == pytest.approx(ctx["operating_delta"] - ctx["capex_delta"],
                                    abs=2.5e-4), stem


# The six ways the two legs can combine. Only three occur in the fixtures, and
# an earlier draft derived this from `driver` alone — which rendered 0700.HK as
# "operating cash is the larger leg" followed by "a business spending more", a
# sentence contradicting itself. Each branch is constructed here so none can
# regress unseen.

def _synthetic(margins):
    """Fundamentals carrying an exact (ocf, capex) history at constant revenue.

    `margins` is [(ocf_margin, capex_intensity), ...] oldest-first.
    """
    revenue = 1_000.0
    cf, inc = {}, {}
    for i, (ocf_m, capex_i) in enumerate(margins):
        period = f"202{i}-12-31"
        cf[period] = {"Operating Cash Flow": ocf_m * revenue,
                      "Capital Expenditure": -capex_i * revenue}
        inc[period] = {"Total Revenue": revenue}
    return {"cash_flow": cf, "income_statement": inc}, sorted(cf)[-1]


@pytest.mark.parametrize("margins,driver,note", [
    # capex driven, operating cash rose -> spending more, not earning less
    ([(0.40, 0.10), (0.40, 0.10), (0.45, 0.30)],
     "capital_spending", "spending_more_not_earning_less"),
    # capex driven, operating cash fell -> both legs hurt
    ([(0.40, 0.10), (0.40, 0.10), (0.36, 0.30)],
     "capital_spending", "both_adverse"),
    # capex driven downward, operating cash fell slightly -> net better
    ([(0.40, 0.30), (0.40, 0.30), (0.38, 0.10)],
     "capital_spending", "spending_less_offset_weaker_earnings"),
    # operating driven, both rose -> earned more despite spending more
    ([(0.40, 0.10), (0.40, 0.10), (0.60, 0.12)],
     "operating_cash", "earning_more_despite_spending_more"),
    # operating driven down, capex also down -> earning less, not spending more
    ([(0.40, 0.10), (0.40, 0.10), (0.25, 0.09)],
     "operating_cash", "earning_less_not_spending_more"),
    # operating up, capex down -> everything in free cash flow's favour
    ([(0.40, 0.10), (0.40, 0.10), (0.55, 0.08)],
     "operating_cash", "both_favourable"),
])
def test_every_driver_combination_is_named_correctly(margins, driver, note):
    f, period = _synthetic(margins)
    ctx = fm.base_year_context(f, period)
    assert ctx["driver"] == driver
    assert ctx["driver_note"] == note


def test_a_representative_year_names_neither_driver_nor_note():
    f, period = _synthetic([(0.40, 0.10), (0.40, 0.10), (0.40, 0.10)])
    ctx = fm.base_year_context(f, period)
    assert ctx["driver"] is None
    assert ctx["driver_note"] is None


def test_the_note_never_contradicts_the_driver_on_real_data():
    """0700.HK is the case: operating-cash-driven with both legs up. A note
    claiming "spending more" there would contradict the leg named beside it."""
    spending_notes = {"spending_more_not_earning_less",
                      "spending_less_offset_weaker_earnings"}
    for stem in ("MSFT", "XOM", "AAPL", "0700_HK"):
        f = load_fundamentals(stem)
        ctx = fm.base_year_context(f, statements.statement_fcf(f["cash_flow"])[0])
        if ctx["driver"] == "operating_cash":
            assert ctx["driver_note"] not in spending_notes, stem


# ── equity risk premium: sourced per market, not one number for the world ──
#
# `EQUITY_RISK_PREMIUM = 0.05` was invented — no source, no date, one figure for
# every market and every year. These pin the replacement: Damodaran's published
# country table, vendored as a dated snapshot, keyed on the currency the
# discounted cash flows are actually denominated in.

def test_erp_resolves_per_market():
    """USD, HKD and CNY each get their own published figure."""
    usd, src, market = fm.equity_risk_premium_for("USD")
    assert (usd, market) == (0.0446, "United States")
    assert src.startswith("damodaran_")

    assert fm.equity_risk_premium_for("HKD")[::2] == (0.0501, "Hong Kong")
    assert fm.equity_risk_premium_for("CNY")[::2] == (0.0514, "China")


# ── the other half of CAPM: the risk-free rate ───────────────────────
#
# The premium above has been currency-aware since the Damodaran snapshot landed.
# The rate was not, which meant 0002.HK was priced off Hong Kong's 5.01% premium
# and a United States risk-free rate — a pairing that exists in no market. These
# pin the disclosure that fixes it. They pin a *label*, not a number: every
# currency still resolves to the US 10-year, deliberately.

def test_a_non_usd_currency_says_the_rate_is_a_stand_in(monkeypatch):
    """Same number, different provenance — which is the entire deliverable."""
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0431)

    assert data_provider.risk_free_rate(0.043, "USD") == (0.0431, "us_treasury_10y")
    # None is the "caller did not say" case: a company with no financialCurrency
    # is treated as USD rather than as a stand-in, which is what the code did
    # before this parameter existed.
    assert data_provider.risk_free_rate(0.043, None) == (0.0431, "us_treasury_10y")

    # CNY is deliberately absent: since 2026-08-19 it has a curve of its own and
    # is covered by test_cny_is_priced_off_chinas_own_curve_net_of_its_default_
    # spread. These are the currencies that still have no local source.
    for ccy in ("HKD", "JPY", "EUR"):
        rate, source = data_provider.risk_free_rate(0.043, ccy)
        assert (rate, source) == (0.0431, "usd_proxy"), ccy

    # Matched exactly, like the two other consumers of this same code. An
    # unrecognised spelling degrades to the proxy in all three rather than
    # half-resolving in one — see
    # test_a_misspelled_currency_degrades_instead_of_half_resolving.
    assert data_provider.risk_free_rate(0.043, "usd")[1] == "usd_proxy"

    # Reads off a vendor payload, so it must not turn a junk value into a crash
    # inside the WACC. `equity_risk_premium_for` already degrades rather than
    # raising on the same input; this keeps the two halves equally survivable.
    assert data_provider.risk_free_rate(0.043, 3.14)[1] == "usd_proxy"


def test_the_rate_follows_the_reporting_currency_not_the_traded_one():
    """The same choice `equity_risk_premium_for` makes, and for the same reason:
    a discount rate matches the currency of the cash flows, not of the shares.

    No fixture can catch this on its own. 0002.HK trades and reports HKD; 0700.HK
    trades HKD and reports CNY, and both are non-USD, so reading the wrong field
    gives the right answer for both. It takes a filer that straddles the USD
    boundary, and there is none — so one is built here.
    """
    f = load_fundamentals("AAPL")  # trades USD, reports USD
    f["info"]["financialCurrency"] = "EUR"  # ... now reports EUR

    a = fm.dcf_valuation(f)["assumptions"]
    assert a["risk_free_source"] == "usd_proxy"


def test_an_unreachable_feed_is_named_apart_from_a_substituted_currency(monkeypatch):
    """Two different failures that used to be one silent number.

    `platform_default` says the Fed feed was unreachable. `usd_proxy` says a
    rate for this currency was never attempted. A reader looking at a wrong
    valuation needs to know which of those happened.
    """
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: None)
    assert data_provider.risk_free_rate(0.043, "USD") == (0.043, "platform_default")
    # Still `usd_proxy`, not `platform_default`: the material fact for a Hong
    # Kong filer is that no HKD rate was used, and that holds either way.
    assert data_provider.risk_free_rate(0.043, "HKD") == (0.043, "usd_proxy")


def test_the_hkd_filer_discloses_the_mismatch_between_its_two_capm_halves():
    """0002.HK is the fixture this was added for: a Hong Kong premium against a
    US rate. The valuation is unchanged and the disclosure is new."""
    a = fm.dcf_valuation(load_fundamentals("0002_HK"))["assumptions"]
    assert a["risk_free_source"] == "usd_proxy"
    assert a["equity_risk_premium_market"] == "Hong Kong"

    # The USD control, so this test fails if `usd_proxy` were returned for
    # everything — which would look identical on the HK assertion alone.
    us = fm.dcf_valuation(load_fundamentals("AAPL"))["assumptions"]
    assert (us["risk_free_source"],
            us["equity_risk_premium_market"]) == ("us_treasury_10y", "United States")
    assert us["risk_free_rate"] == a["risk_free_rate"]  # same number, still


# ── CNY gets a rate of its own ───────────────────────────────────────
#
# The one currency where a stand-in was not merely undisclosed but wrong:
# 0700.HK's cash flows are CNY, and CNY is not pegged to anything. These pin the
# arithmetic, the failure contract, and the boundary — that the spread comes off
# a *local* sovereign yield and never off the US one.

def test_cny_is_priced_off_chinas_own_curve_net_of_its_default_spread(monkeypatch):
    """A local government yield is not risk-free: China's 10Y carries China's
    own default risk, and the country-inclusive ERP paired with it carries that
    same spread again. Subtracting once removes the double count."""
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: 0.016864)

    rate, source = data_provider.risk_free_rate(0.043, "CNY", 0.006)
    assert (round(rate, 6), source) == (0.010864, "cgb_10y_less_spread")

    # The spread is the caller's, read from the same table the ERP comes from,
    # so the two legs cannot disagree about a market.
    assert fm.sovereign_default_spread("CNY") == 0.006


def test_the_default_spread_never_comes_off_the_us_rate(monkeypatch):
    """`USD.default_spread` is 0.0023 and is deliberately *not* netted. The US
    10Y is the mature-market base the whole Damodaran table is built on;
    subtracting there would move every USD valuation for no corresponding gain,
    and would be this change leaking out of its own scope."""
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)
    monkeypatch.setattr(data_provider, "_cgb_10y",
                        lambda: pytest.fail("the USD path must not touch the CGB curve"))

    assert fm.sovereign_default_spread("USD") == 0.0023  # published, and unused
    assert data_provider.risk_free_rate(0.043, "USD", 0.0023) == (0.0472, "us_treasury_10y")


def test_a_misspelled_currency_degrades_instead_of_half_resolving(monkeypatch):
    """The three consumers of `financialCurrency` must agree about what they do
    not recognise.

    `risk_free_rate` case-folded while `sovereign_default_spread` and
    `equity_risk_premium_for` matched exactly, so `"cny"` took the CGB branch,
    missed the spread lookup and got `0.0`, and fell to the mature-market
    premium — China's **raw** yield against a no-country ERP, and still labelled
    `cgb_10y_less_spread`. That is the two-countries defect this whole change
    exists to remove, reintroduced by a convenience. `usd_proxy` is the honest
    answer and is what the code did before the branch existed.
    """
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: 0.016864)
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)

    assert fm.sovereign_default_spread("cny") == 0.0
    assert fm.equity_risk_premium_for("cny")[2] is None
    assert data_provider.risk_free_rate(0.043, "cny", 0.0) == (0.0472, "usd_proxy")


@pytest.mark.parametrize("cgb", [0.0059, 0.006, 0.003, 0.0])
def test_a_yield_below_the_spread_never_becomes_a_negative_rate(monkeypatch, cgb):
    """`_cgb_10y`'s sanity band guards the *published* yield; the spread comes
    off afterwards, so a low enough print nets to zero or below.

    Left unchecked this is not a crash but something worse: the rate caps
    terminal growth through `min(TERMINAL_GROWTH, rf)`, so the model would
    assert perpetual *shrinkage* for a going concern — negative terminal-growth
    column headers and all — with no error and no flag. It needs a 109bp rally
    from the 1.6864% of 2026-08-19, or one Damodaran refresh that raises the
    0.60% spread.
    """
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: cgb)
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)

    rate, source = data_provider.risk_free_rate(0.043, "CNY", 0.006)
    assert (rate, source) == (0.0472, "usd_proxy"), cgb


def test_an_unreachable_chinabond_degrades_to_the_old_behaviour(monkeypatch):
    """The failure contract that matters: a bad day at ChinaBond must return the
    platform to what it did before this existed — the US rate, labelled as the
    stand-in it is — never an error and never a stale CNY number."""
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: None)
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)

    assert data_provider.risk_free_rate(0.043, "CNY", 0.006) == (0.0472, "usd_proxy")


def test_an_unknown_market_is_left_double_counted_rather_than_guessed(monkeypatch):
    """No published spread means no subtraction. The sovereign risk stays double
    counted, which is visible in the number, rather than corrected by a figure
    nobody sourced."""
    assert fm.sovereign_default_spread("JPY") == 0.0
    assert fm.sovereign_default_spread(None) == 0.0


def _cgb_page(rows):
    """A ChinaBond response, shaped like the real one.

    Real payloads carry three curves per date — government, commercial-bank AAA
    and CP&Note AAA — which is why the parse matches on the curve name rather
    than on position. `rows` is (curve, date, yield-as-published-percent).
    """
    body = "".join(f"<tr><td>{c}</td><td>{d}</td><td>{y}</td></tr>" for c, d, y in rows)
    return ("<html><body><table>"
            "<tr><th>Yield Curve Name</th><th>Date</th><th>10Y</th></tr>"
            f"{body}</table></body></html>")


# `conftest.pinned_risk_free_rate` replaces `_cgb_10y` for every test, so the
# real one has to be held at import — otherwise these would assert against the
# stub and pass no matter what the parse did.
_real_cgb_10y = data_provider._cgb_10y


def _stub_cgb(monkeypatch, html):
    """Replace the HTTP call, not the function, so the parse itself runs."""
    class _Resp:
        def read(self): return html.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(data_provider, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    return _real_cgb_10y()


def _days_ago(n):
    """A date the freshness check will accept (or, for a large `n`, reject).

    Relative rather than literal: `_cgb_10y` compares the newest published row
    against `datetime.now()`, so a hard-coded 2026-08-18 in these fixtures would
    quietly start failing a fortnight after it was written.
    """
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


GOV = "ChinaBond Government Bond Yield Curve"
CP = "ChinaBond CP&Note Yield Curve (AAA)"


def test_the_cgb_parse_takes_the_newest_government_row_as_a_ratio(monkeypatch):
    """The three things the parse has to get right, none of which has a contract.

    Dates deliberately out of order: the live table happens to arrive
    newest-first and nothing documents that it always will, so the parse takes
    the max by date rather than the first row.
    """
    rate = _stub_cgb(monkeypatch, _cgb_page([
        (CP, _days_ago(0), "2.0493"),      # a different curve, higher — must lose
        (GOV, _days_ago(1), "1.6924"),
        (GOV, _days_ago(0), "1.6864"),     # newest, but not first
        (GOV, _days_ago(4), "1.6964"),
    ]))
    # published as percent, consumed as a ratio
    assert rate == pytest.approx(0.016864)


def test_two_rows_on_one_date_do_not_become_the_higher_yield(monkeypatch):
    """`max(rows)` on (date, yield) tuples silently breaks ties on the *yield*,
    so a duplicated date would serve the larger number — and a spurious 9.99%
    clears the sanity band, arriving as a plausible 0.0999 rate. Keyed on the
    date alone, the first row for that date wins and the tie-break never runs."""
    rate = _stub_cgb(monkeypatch, _cgb_page([
        (GOV, _days_ago(0), "1.6864"),
        (GOV, _days_ago(0), "9.9999"),
    ]))
    assert rate == pytest.approx(0.016864)


@pytest.mark.parametrize("rows, why", [
    ([], "empty table — what a >1yr range or a holiday week returns, with HTTP 200"),
    ([(CP, _days_ago(0), "2.0493")], "no government row, only other curves"),
    ([(GOV, _days_ago(0), "68.64")], "absurd level — a units change would look like this"),
    ([(GOV, _days_ago(0), "--")], "non-numeric placeholder"),
    ([(GOV, _days_ago(15), "3.1500")], "a frozen feed: one day past the staleness bound"),
    ([(GOV, _days_ago(2500), "3.1500")], "a frozen feed: years old"),
])
def test_the_cgb_parse_returns_none_rather_than_a_wrong_number(monkeypatch, rows, why):
    """Every one of these degrades CNY to the US proxy, which is the pre-2026-08-19
    behaviour — never an exception and never a plausible-looking wrong rate."""
    assert _stub_cgb(monkeypatch, _cgb_page(rows)) is None, why


def test_an_all_tenor_row_is_not_read_as_the_ten_year(monkeypatch):
    """The `len(cells) == 3` guard is the only thing standing between the parse
    and the short end of the curve.

    `gjqx=10` filters to one tenor, so rows arrive as (curve, date, 10Y). Drop
    that filter — or have ChinaBond ignore it — and a row carries every tenor
    from 3M to 30Y, at which point `cells[2]` is the **3-month** yield: 1.1858%
    where the 10Y is 1.6864%. Plausible, wrong, and silent.
    """
    body = ("<table><tr>"
            + "".join(f"<td>{c}</td>" for c in
                      [GOV, _days_ago(0), "1.1858", "1.1936", "1.2008",
                       "1.2493", "1.3842", "1.5121", "1.6864", "2.1509"])
            + "</tr></table>")
    assert _stub_cgb(monkeypatch, f"<html><body>{body}</body></html>") is None


def test_a_failed_cgb_fetch_is_never_cached(monkeypatch):
    """The property the whole failure contract rests on, and it was asserted in
    two docstrings and pinned by nothing.

    If a miss were cached for the day, one bad moment would hold every CNY
    valuation on the US proxy until midnight — and the two rates are 30% of
    Tencent's fair value apart. Because it is not, a miss costs one request.
    """
    calls = []

    class _Boom:
        def __enter__(self): raise OSError("connection reset")
        def __exit__(self, *a): return False

    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    monkeypatch.setattr(data_provider, "urlopen",
                        lambda *a, **k: (calls.append(1), _Boom())[1])

    assert [_real_cgb_10y() for _ in range(3)] == [None, None, None]
    assert len(calls) == 3, "a failure was cached — the retry never happened"
    assert data_provider._CGB_CACHE is None


def test_a_successful_cgb_fetch_is_cached_for_the_day(monkeypatch):
    """The other half: one fetch per calendar day, not one per request. A DCF
    runs on every scorecard, and `score_batch` fans a watchlist across threads."""
    calls = []
    html = _cgb_page([(GOV, _days_ago(0), "1.6864")])

    class _Resp:
        def read(self): return html.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    monkeypatch.setattr(data_provider, "urlopen",
                        lambda *a, **k: (calls.append(1), _Resp())[1])

    assert [_real_cgb_10y() for _ in range(3)] == [pytest.approx(0.016864)] * 3
    assert len(calls) == 1, "the day cache did not hold"


def test_the_cny_fixture_now_carries_a_chinese_rate_end_to_end(monkeypatch):
    """0700_HK through the real model, which is the only place the pairing is
    visible: a Chinese premium and a Chinese rate, where it was a Chinese
    premium and an American rate until 2026-08-19."""
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: 0.016864)
    f = load_fundamentals("0700_HK")

    a = fm.dcf_valuation(f, market_bars=load_market_bars("0700_HK"))["assumptions"]
    assert a["risk_free_source"] == "cgb_10y_less_spread"
    assert a["equity_risk_premium_market"] == "China"
    assert a["risk_free_rate"] == round(0.016864 - 0.006, 4)
    # The growth ceiling binds, which is where most of the valuation change
    # comes from — see docs/currency-consistent-discounting.md §5.
    assert a["terminal_growth_source"] == "capped_at_risk_free_rate"
    assert a["terminal_growth"] == pytest.approx(0.0109, abs=1e-4)


def test_the_audit_row_carries_the_precision_of_the_beta_it_used(monkeypatch):
    """XOM is the case this exists for: the panel printed 0.2888 with the same
    authority as AAPL's 1.1546, while the index explains under 3% of XOM's
    movement and its interval spans 0.08 to 0.49."""
    a = fm._wacc(load_fundamentals("XOM"), 0.21, None,
                 (load_bars("XOM"), load_bars("_GSPC")))
    assert a["beta_source"] == "computed"
    assert a["beta_r_squared"] == pytest.approx(0.028, abs=0.002)
    lo, hi = a["beta_confidence_interval"]
    assert lo < 0.1 and hi > 0.45

    # and the clamp is legible rather than silent
    assert a["beta_regressed"] == pytest.approx(0.2888, abs=1e-3)
    assert a["beta"] == fm.BETA_MIN
    assert a["beta_regressed"] < a["beta"]


def test_a_well_fitted_beta_is_visibly_different_from_a_badly_fitted_one(monkeypatch):
    """The comparison the reader could not previously make on screen."""
    good = fm._wacc(load_fundamentals("0700_HK"), 0.165, None,
                    (load_bars("0700_HK"), load_bars("_HSI")))
    poor = fm._wacc(load_fundamentals("XOM"), 0.21, None,
                    (load_bars("XOM"), load_bars("_GSPC")))
    assert good["beta_r_squared"] > 0.65
    assert poor["beta_r_squared"] < 0.05


def test_only_a_regressed_beta_claims_a_precision(monkeypatch):
    """The other rungs of the ladder are a vendor scalar, a peer median and a
    constant. None has residuals, so none may carry an interval — publishing one
    would invent a precision claim instead of describing one."""
    a = fm._wacc(load_fundamentals("AAPL"), 0.21, None, None)
    assert a["beta_source"] == "reported"
    for key in ("beta_regressed", "beta_standard_error",
                "beta_r_squared", "beta_confidence_interval"):
        assert a[key] is None, key


def test_a_vendor_ev_multiple_is_restated_onto_one_currency():
    """`enterpriseToEbitda` arrives pre-divided, and its legs are not in the same
    unit: EV comes from marketCap (trading) and EBITDA from the statements
    (reporting). For 0700.HK that is HKD over CNY, overstated by the whole rate.

    Both directions matter. A rule that only ever divides would quietly rescale
    every US issuer too, and the test would not notice."""
    f = load_fundamentals("0700_HK")
    vendor = f["info"]["enterpriseToEbitda"]
    assert vendor == 15.705

    ev_ebitda, ev_revenue = fm.ev_multiples_for(f["info"])
    assert ev_ebitda == round(vendor / TEST_CNY_HKD, 4) == 14.2773
    assert ev_revenue == round(f["info"]["enterpriseToRevenue"] / TEST_CNY_HKD, 4)

    # a single-currency issuer is passed through untouched
    aapl = load_fundamentals("AAPL")["info"]
    assert aapl["currency"] == aapl["financialCurrency"]
    assert fm.ev_multiples_for(aapl) == (aapl["enterpriseToEbitda"],
                                         aapl["enterpriseToRevenue"])


def test_an_unfetchable_rate_withholds_the_multiple_rather_than_mixing_units(monkeypatch):
    """Same stance the DCF takes on upside: no rate means no number, because a
    multiple with one leg in each currency is worse than an absent one."""
    monkeypatch.setattr(fm, "fx_rate", lambda a, b: None)
    f = load_fundamentals("0700_HK")
    assert fm.ev_multiples_for(f["info"]) == (None, None)
    # and a same-currency issuer still resolves, because no rate was needed
    assert fm.ev_multiples_for(load_fundamentals("AAPL")["info"])[0] is not None


def test_the_traded_multiple_the_diagnostics_report_is_the_corrected_one(monkeypatch):
    """The panel divides the implied exit multiple by this one. The exit figure
    is built from statements and is reporting-currency throughout, so reading it
    against an HKD-over-CNY multiple overstated the implied compression."""
    f = load_fundamentals("0700_HK")
    diag = fm.dcf_valuation(f)["diagnostics"]
    assert diag["current_ev_ebitda"] == 14.2773
    assert diag["current_ev_ebitda"] < f["info"]["enterpriseToEbitda"]


def test_tencent_is_priced_off_china_not_hong_kong():
    """The distinction the whole keying rests on. 0700.HK *trades* in HKD and
    *reports* in CNY, and the discount rate has to match the currency of the
    cash flows it discounts — so China's premium applies, not Hong Kong's.
    `tax_rate_for` deliberately keys the other way: tax follows the filing
    jurisdiction, a discount rate follows the money."""
    f = load_fundamentals("0700_HK")
    assert f["info"]["currency"] == "HKD"
    assert f["info"]["financialCurrency"] == "CNY"

    a = fm.dcf_valuation(f)["assumptions"]
    assert a["equity_risk_premium_market"] == "China"
    assert a["equity_risk_premium"] == 0.0514
    assert fm.tax_rate_for(f["info"]) == 0.165  # still Hong Kong, on purpose


def test_the_country_risk_premium_is_never_added_on_top():
    """Damodaran's country figure is additive — total = mature + CRP — so using
    `total_erp` *and* adding the CRP would count the country twice. This pins
    both halves: the snapshot's arithmetic, and that the resolver returns the
    total unmodified."""
    data = fm._market_premiums()
    mature = data["mature_market_erp"]
    for ccy, entry in data["markets"].items():
        assert round(mature + entry["country_risk_premium"], 4) == entry["total_erp"], ccy
        assert fm.equity_risk_premium_for(ccy)[0] == entry["total_erp"], ccy


def test_an_unknown_market_falls_back_to_the_mature_premium():
    erp, src, market = fm.equity_risk_premium_for("JPY")
    assert (erp, src, market) == (fm._market_premiums()["mature_market_erp"],
                                  "mature_market", None)


def test_a_missing_reference_file_degrades_the_number_not_the_endpoint(monkeypatch):
    """Same rule as risk_free_rate falling back to RISK_FREE_RATE when the Fed
    feed is unreachable: the valuation still runs, and says which number it used.
    """
    monkeypatch.setattr(fm, "_MARKET_PREMIUMS", None)
    monkeypatch.setattr(fm, "MARKET_PREMIUMS_PATH",
                        fm.MARKET_PREMIUMS_PATH.with_name("does-not-exist.json"))

    assert fm.equity_risk_premium_for("USD") == (fm.EQUITY_RISK_PREMIUM,
                                                 "platform_default", None)
    d = fm.dcf_valuation(load_fundamentals("AAPL"))
    assert not d.get("error")
    assert d["assumptions"]["equity_risk_premium_source"] == "platform_default"


def test_every_valuation_reports_where_its_premium_came_from():
    for stem in ("AAPL", "MSFT", "XOM", "0700_HK", "O"):
        a = fm.dcf_valuation(load_fundamentals(stem))["assumptions"]
        assert a["equity_risk_premium_source"], stem
        assert a["equity_risk_premium"] > 0, stem


def test_sourcing_the_premium_is_not_one_directional():
    """The direction-blindness check, pinned. Replacing a flat 5% with published
    figures *raises* US valuations (4.46% is below 5%) and *lowers* Tencent's
    (China is 5.14%, above it). A change that only ever moved values one way
    would be tuning wearing a citation; this one cannot be, and the test fails
    if a future snapshot update quietly makes it so."""
    def fair_value(stem, erp):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(fm, "equity_risk_premium_for", lambda c: (erp, "test", None))
            return fm.dcf_valuation(load_fundamentals(stem))["fair_value_per_share"]

    flat = 0.05
    assert fair_value("AAPL", 0.0446) > fair_value("AAPL", flat)
    assert fair_value("MSFT", 0.0446) > fair_value("MSFT", flat)
    assert fair_value("0700_HK", 0.0514) < fair_value("0700_HK", flat)


# ── the EV -> equity bridge ──────────────────────────────────────────
#
# The reference doc states five terms; the model implemented one. These pin the
# three that were added, the one that deliberately was not, and the two exact
# identities the whole approach rests on.

def _bridge(stem):
    return fm.dcf_valuation(load_fundamentals(stem))["diagnostics"]["equity_bridge"]


def test_the_investment_lines_nest_exactly():
    """The blocker that kept this unimplemented: adding associates, JVs and
    `Long Term Equity Investment` together double-counts, because the third is
    the sum of the first two. Reading the parent is what makes it safe, and this
    asserts the identity rather than trusting the row names."""
    bal = load_fundamentals("0700_HK")["balance_sheet"]
    checked = 0
    for period, rows in bal.items():
        parent = rows.get("Long Term Equity Investment")
        if parent is None:
            continue
        children = ((rows.get("Investmentsin Associatesat Cost") or 0)
                    + (rows.get("Investmentsin Joint Venturesat Cost") or 0))
        assert children == pytest.approx(parent, rel=1e-9), period
        checked += 1
    assert checked >= 2, "identity should hold on every reported period"


def test_the_securities_line_is_already_marked_to_market():
    """The argument for adding this term at all. `Investmentin Financial Assets`
    is exactly available-for-sale plus fair-value-through-profit-or-loss, and
    both of those are carried at fair value — so using it reads a filed mark
    rather than making one. If a vendor ever redefines that row, this fails."""
    bal = load_fundamentals("0700_HK")["balance_sheet"]
    checked = 0
    for period, rows in bal.items():
        total = rows.get("Investmentin Financial Assets")
        if total is None:
            continue
        parts = ((rows.get("Available For Sale Securities") or 0)
                 + (rows.get("Financial Assetsdesignatedas Fair Value Through Profitor Loss Total")
                    or rows.get("Financial Assets Designatedas Fair Value Through Profitor Loss Total")
                    or 0))
        assert parts == pytest.approx(total, rel=1e-9), period
        checked += 1
    assert checked >= 2


def test_associates_at_cost_never_reach_the_headline():
    """Cost is not value. The figure is reported beside the headline, the same
    way the normalised base year is, and must not be inside it."""
    d = fm.dcf_valuation(load_fundamentals("0700_HK"))
    b = d["diagnostics"]["equity_bridge"]

    assert b["associates_at_cost"] > 0
    assert b["per_share"]["associates_at_cost"] > 0
    # the headline excludes it; the disclosed alternative is exactly it higher
    assert d["fair_value_per_share"] < b["fair_value_including_associates"]
    assert (b["fair_value_including_associates"] - d["fair_value_per_share"]
            == pytest.approx(b["per_share"]["associates_at_cost"], abs=0.02))


def test_minority_interest_is_subtracted_and_marked_securities_added():
    """Directions, pinned. Both are one-way by definition rather than by choice:
    a claim on the business reduces the equity, an asset outside it adds."""
    b = _bridge("0700_HK")
    assert b["per_share"]["minority_interest"] < 0
    assert b["per_share"]["marked_securities"] > 0
    assert b["deduction"] == pytest.approx(
        b["net_debt"] + b["minority_interest"] + b["preferred"] - b["marked_securities"])


def test_the_sensitivity_grid_uses_the_same_bridge_as_the_headline():
    """The failure most likely to slip through. `net_debt` was subtracted at four
    separate places, and a bridge applied to only some of them would print a
    sensitivity table whose centre cell disagreed with the fair value directly
    above it. The grid is built at the base WACC and base terminal growth in its
    middle cell, so that cell must *be* the headline."""
    for stem in ("0700_HK", "XOM", "AAPL"):
        d = fm.dcf_valuation(load_fundamentals(stem))
        rows = d["sensitivity"]["rows"]
        centre = rows[len(rows) // 2]["values"][len(rows[0]["values"]) // 2]
        assert centre == pytest.approx(d["fair_value_per_share"], abs=0.02), stem


def test_the_growth_sweep_uses_the_same_bridge_too():
    """Same trap, the other grid: the sweep holds WACC and terminal growth at
    base, so its middle point is also the headline."""
    for stem in ("0700_HK", "XOM"):
        d = fm.dcf_valuation(load_fundamentals(stem))
        values = d["growth_sensitivity"]["values"]
        assert values[len(values) // 2] == pytest.approx(d["fair_value_per_share"], abs=0.02), stem


def test_a_row_that_vanished_is_named_rather_than_carried_forward():
    """MSFT reports `Long Term Equity Investment` at 2025-06-30 and nothing at
    2026-06-30. `_latest` would walk back and import the year-old balance into
    today's valuation — the period-drift defect this codebase has already fought
    twice. The row reads zero, and the fact that it moved is reported."""
    b = _bridge("MSFT")
    assert b["associates_at_cost"] == 0.0
    assert "associates_at_cost" in b["disappeared"]


def test_a_row_that_was_never_reported_is_not_flagged():
    """The other half of that rule. Most companies have no preferred stock and no
    associates, so an absent row means nil — flagging it would put a warning on
    every company and train the reader to ignore warnings."""
    assert _bridge("AAPL")["disappeared"] == []
    assert _bridge("0700_HK")["disappeared"] == []


def test_a_company_with_none_of_these_rows_is_valued_exactly_as_before():
    """Regression guard: where the balance sheet carries no such lines, the
    bridge must collapse back to `EV - net debt` to the cent."""
    f = load_fundamentals("AAPL")
    for rows in f["balance_sheet"].values():
        for name in ("Minority Interest", "Preferred Stock", "Investmentin Financial Assets",
                     "Long Term Equity Investment"):
            rows.pop(name, None)

    d = fm.dcf_valuation(f)
    info = f["info"]
    expected = ((d["enterprise_value"]
                 - (info["totalDebt"] - info["totalCash"])) / info["sharesOutstanding"])
    assert d["fair_value_per_share"] == pytest.approx(round(expected, 2), abs=0.01)
    assert d["diagnostics"]["equity_bridge"]["deduction"] == pytest.approx(
        info["totalDebt"] - info["totalCash"])


def test_the_bridge_terms_are_converted_once_like_net_debt():
    """0700.HK reports CNY and trades HKD. The balance-sheet terms are reporting
    currency, exactly like net debt, so they must be converted at the output
    boundary and not before — a term converted twice would be 1.1x too large."""
    d = fm.dcf_valuation(load_fundamentals("0700_HK"))
    b = d["diagnostics"]["equity_bridge"]
    fx = d["assumptions"]["fx_rate_used"]
    shares = load_fundamentals("0700_HK")["info"]["sharesOutstanding"]

    assert d["assumptions"]["fx_basis"] == "converted"
    assert b["per_share"]["marked_securities"] == pytest.approx(
        b["marked_securities"] * fx / shares, abs=0.01)
