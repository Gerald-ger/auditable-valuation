"""Valuation-engine behaviour: beta resolution, credit spread, two-stage
projection, jurisdiction tax and the DCF trust diagnostics.

These cover the pure logic. The one part that is not pure — fetching peer betas
when a reported beta is implausible — is wired in main.py and smoke-tested live,
because pulling the network into this suite would defeat its purpose.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from conftest import (FIXTURES, HOME_INDEX, TEST_CNY_HKD, load_bars,
                      load_fundamentals, load_market_bars)

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
    # 146.49 once the equity bridge added AAPL's marked investment securities;
    # 127.91 now that stock compensation is subtracted as the cash expense it is
    # rather than added back against a share count that never moves
    assert dcf["fair_value_per_share"] == pytest.approx(127.91, rel=1e-3)


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
    # ...and the DCF used the reported year, moved only by legs it names on
    # screen. The `>=` this line used to assert stopped holding on 2026-08-26:
    # subtracting stock compensation makes the discounted figure *smaller* than
    # the statement one, which is the point of it. The equality is the stronger
    # claim anyway — it pins the whole composition, not just its direction.
    assert d["assumptions"]["base_fcf"] == (reported
                                            + d["assumptions"]["fcf_interest_addback"]
                                            - d["assumptions"]["fcf_sbc"])


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
    # Net of stock compensation on both legs since 2026-08-26. That is the
    # quantity the model discounts, so it is the quantity fair value is
    # homogeneous in; the gross statement margin stopped being either.
    scale = ((b["mean_fcf_margin"] - b["mean_sbc_margin"])
             / (b["latest_fcf_margin"] - b["latest_sbc_margin"]))

    # equity value, not fair value: the bridge is a constant, so only the
    # enterprise leg scales. The **whole** deduction, not net debt on its own —
    # MSFT's marked investment securities are 36bn of it, and adding back net
    # debt alone left a 1.66% residual that the 2% tolerance had been absorbing
    # since this test was written. Corrected here because the SBC change shrank
    # the denominator and pushed that residual to the edge of passing.
    ev_reported = d["enterprise_value"]
    ev_normalised = (b["fair_value_normalised"] * f["info"]["sharesOutstanding"]
                     + d["diagnostics"]["equity_bridge"]["deduction"])
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
    assert d["assumptions"]["base_fcf"] == (statement_fcf
                                            + d["assumptions"]["fcf_interest_addback"]
                                            - d["assumptions"]["fcf_sbc"])
    assert d["diagnostics"]["base_year"]["fair_value_normalised"] != d["fair_value_per_share"]


def test_a_missing_market_cap_refuses_the_dcf_rather_than_discounting_at_debt():
    """`marketCap or 0` made the equity weight zero and the WACC a cost of debt.

    Measured 2026-08-27, before the guard: AAPL discounted at 3.87% against its
    real 9.05% and returned **618.69** against 127.91, XOM 356.00 against 76.69,
    0700.HK 9507.31 against 912.47 — +362% to +942% across the fixtures, with no
    error, no flag, and the one field that would have shown it
    (`weight_equity`, 0.0) rendered nowhere. The scorecard moved the wrong way
    too: `dcf_upside_pct` came off its floor and AAPL's composite *rose* 65 to
    70 because an input had gone missing.

    A rate that omits the equity side is not a conservative discount rate, it is
    the wrong one, so this is refused on the same ground a missing FX rate
    withholds the upside instead of computing one across two currencies.
    """
    for stem in ("AAPL", "MSFT", "XOM", "0700_HK", "0002_HK"):
        f = load_fundamentals(stem)
        assert f["info"]["marketCap"], f"{stem} fixture has no market cap to remove"
        f["info"]["marketCap"] = None

        d = fm.dcf_valuation(f)
        assert "error" in d, stem
        assert "market capitalisation" in d["error"], stem
        assert "fair_value_per_share" not in d, stem


def test_a_caller_naming_its_own_wacc_is_not_refused_for_a_missing_market_cap():
    """The gate is on the *dependency*, not on the field.

    `solve_for_fair_value` and the sensitivity grid both sweep WACC explicitly,
    and a valuation that never consults the collapsed rate is not damaged by it.
    Refusing those too would withhold an answer that does not rest on the
    missing figure — which is the opposite of the discipline the guard exists
    to enforce.
    """
    f = load_fundamentals("AAPL")
    f["info"]["marketCap"] = None

    d = fm.dcf_valuation(f, wacc_override=0.09)
    assert "error" not in d
    assert d["fair_value_per_share"] > 0
    assert d["assumptions"]["wacc_used"] == pytest.approx(0.09)


def test_the_market_cap_gate_leaves_every_fixture_as_filed_alone():
    """A guard that moved a real valuation would be a change, not a fix."""
    for stem in sorted(FIXTURES):
        d = fm.dcf_valuation(load_fundamentals(stem))
        if "error" in d:
            assert "market capitalisation" not in d["error"], stem


def test_stock_compensation_is_subtracted_rather_than_added_back():
    """The reference doc states it as an absolute, and the engine used to breach it.

    `docs/financial-models-reference.md` permits two treatments and forbids
    their combination: *"Never add back with static share count — that
    double-counts value"*. Operating cash flow adds stock compensation back as a
    non-cash charge and the share count is `sharesOutstanding`, which never
    moves, so until 2026-08-26 the platform was doing precisely the forbidden
    thing on every issuer that reports the row.
    """
    f = load_fundamentals("MSFT")
    d = fm.dcf_valuation(f)
    a = d["assumptions"]
    reported = f["cash_flow"][a["fcf_period"]]["Stock Based Compensation"]

    assert a["sbc_basis"] == "statement_sbc"
    assert a["fcf_sbc"] == round(abs(reported))
    assert a["base_fcf"] == (statements.statement_fcf(f["cash_flow"])[1]
                             + a["fcf_interest_addback"] - a["fcf_sbc"])


def test_an_issuer_reporting_no_stock_compensation_is_left_alone():
    """0.0 with a basis that says why, never a figure estimated for it.

    XOM and 0002.HK carry no SBC row in any captured period. Inferring one from
    a peer or a margin would be exactly the assumption this platform declines to
    make when the statements do not support it — the same discipline
    `fcff_interest_addback` applies to an unverifiable interest classification.
    """
    for stem in ("XOM", "0002_HK"):
        a = fm.dcf_valuation(load_fundamentals(stem))["assumptions"]
        assert a["sbc_basis"] == "not_reported", stem
        assert a["fcf_sbc"] == 0, stem


def test_the_scoring_cash_flow_metrics_are_not_touched_by_the_adjustment():
    """The correction belongs to the DCF and must not leak into the scorer.

    `scoring.fcf_yield` divides by market cap and `fcf_conversion` by net
    income; both are already after stock compensation, so netting it a second
    time inside `statements.statement_fcf` would double-correct them. Pinned
    because that function is the tempting place to make this change, and its own
    docstring says three of its four callers want the figure left alone.
    """
    f = load_fundamentals("MSFT")
    period, fcf = statements.statement_fcf(f["cash_flow"])
    rows = f["cash_flow"][period]
    assert fcf == rows["Operating Cash Flow"] + rows["Capital Expenditure"]
    assert rows["Stock Based Compensation"]        # the row exists...
    assert fcf != rows["Operating Cash Flow"] + rows["Capital Expenditure"] \
        - rows["Stock Based Compensation"]         # ...and was not applied here


def test_the_normalised_base_nets_a_normal_year_of_stock_compensation():
    """Both legs normalised, or the panel sets one normal year against one
    reported one.

    MSFT's SBC margin runs 4.54% -> 3.74% across the captured periods, so
    netting the newest figure rather than the mean would flatter the alternative
    by the whole of that drift while claiming to describe a normal year.
    """
    f = load_fundamentals("MSFT")
    b = fm.dcf_valuation(f)["diagnostics"]["base_year"]

    # the two differ, which is what makes the choice between them load-bearing
    assert b["mean_sbc_margin"] > b["latest_sbc_margin"]
    assert b["normalised_statement_fcf"] == pytest.approx(
        (b["mean_fcf_margin"] - b["mean_sbc_margin"]) * b["latest_revenue"],
        rel=1e-3)


def test_the_two_mean_margins_subtract_exactly_at_two_decimals():
    """The base-year panel prints `mean − mean sbc = net` for the reader to check,
    and an equation on screen has to hold on screen.

    Both means are rounded to four places on the way out, so a difference shown at
    two is exact by construction. At **one** place it was not: MSFT rendered
    26.0% − 4.2% = 21.7%, wrong by inspection, because each term rounded on its own
    and 0.1pp went missing. This pins the four-place rounding those two decimals
    depend on — drop it to three and the panel starts lying again, quietly.
    """
    for stem in ("MSFT", "AAPL", "0700_HK"):
        b = fm.dcf_valuation(load_fundamentals(stem))["diagnostics"]["base_year"]
        gross, sbc = b["mean_fcf_margin"], b["mean_sbc_margin"]
        shown = lambda x: round(x * 100, 2)   # noqa: E731 - mirrors pct(v, 2)
        assert shown(gross) - shown(sbc) == pytest.approx(
            shown(gross - sbc), abs=1e-9), stem


def test_the_fcf_margin_identity_survives_the_stock_compensation_leg():
    """`sbc_to_revenue` is carried beside the identity, never folded into it.

    The panel's attribution rests on `fcf_margin == CFO/rev - capex/rev` with no
    residual. A third term inside that sum would turn "spending more" back into
    a guess, which is why the adjustment is a separate column.
    """
    for stem in ("MSFT", "AAPL", "0700_HK"):
        f = load_fundamentals(stem)
        ctx = fm.base_year_context(f, statements.statement_fcf(f["cash_flow"])[0])
        for h in ctx["history"]:
            assert h["fcf_margin"] == pytest.approx(
                h["operating_margin_cash"] - h["capex_to_revenue"], abs=2e-4)
            assert h["sbc_to_revenue"] >= 0


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

    # CNY and HKD are deliberately absent: each has a curve of its own since
    # 2026-08-19 and 2026-08-26 respectively, covered by
    # test_cny_is_priced_off_chinas_own_curve_net_of_its_default_spread and
    # test_hkd_is_priced_off_hong_kongs_own_benchmark_net_of_its_default_spread.
    # These are the currencies that still have no local source.
    for ccy in ("JPY", "EUR"):
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
    # Still `usd_proxy`, not `platform_default`: the material fact for a filer in
    # a currency with no curve is that no rate of its own was used, and that
    # holds whether or not the US feed answered.
    #
    # JPY rather than HKD since 2026-08-26. HKD used to be the example here and
    # stopped being one the moment it got a source — which is the point of the
    # distinction this test draws, arriving from the other direction.
    assert data_provider.risk_free_rate(0.043, "JPY") == (0.043, "usd_proxy")


def test_the_hkd_filer_now_has_both_capm_halves_in_its_own_market():
    """0002.HK is the fixture this was added for, and it has changed sides.

    It used to pin the *mismatch* — a Hong Kong equity premium paired with a US
    risk-free rate, disclosed as `usd_proxy` because nothing better existed.
    Since 2026-08-26 both halves come from Hong Kong, so what is pinned now is
    that they agree, and that the US control still differs from them.
    """
    a = fm.dcf_valuation(load_fundamentals("0002_HK"))["assumptions"]
    assert a["risk_free_source"] == "hkgb_10y_less_spread"
    assert a["equity_risk_premium_market"] == "Hong Kong"

    # The USD control, so this test fails if one source were returned for
    # everything — which would look identical on the HK assertion alone.
    us = fm.dcf_valuation(load_fundamentals("AAPL"))["assumptions"]
    assert (us["risk_free_source"],
            us["equity_risk_premium_market"]) == ("us_treasury_10y", "United States")
    # The assertion that inverted. It read `==` while HKD borrowed the US rate;
    # a rate of Hong Kong's own is only meaningful if it is a *different* number.
    assert us["risk_free_rate"] != a["risk_free_rate"]


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
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: (0.016864, True))

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
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: (0.016864, True))
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
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: (cgb, True))
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)

    rate, source = data_provider.risk_free_rate(0.043, "CNY", 0.006)
    assert (rate, source) == (0.0472, "usd_proxy"), cgb


def test_an_unreachable_chinabond_degrades_to_the_old_behaviour(monkeypatch):
    """The failure contract that matters: with no rate available *at all*,
    ChinaBond's bad day must return the platform to what it did before this
    existed — the US rate, labelled as the stand-in it is — never an error.

    `_cgb_10y` returning `None` is now the case where the fetch failed **and**
    the store had nothing usable either; a stored reading inside
    `CGB_MAX_STALE_DAYS` returns a rate and is covered by
    `test_a_stored_reading_carries_the_outage`. This docstring said "never a
    stale CNY number" until 2026-08-20, which stopped being the contract that
    day — the point of the store is that a CNY yield a few days old beats a US
    one today.
    """
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: None)
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)

    assert data_provider.risk_free_rate(0.043, "CNY", 0.006) == (0.0472, "usd_proxy")


def test_an_unknown_market_is_left_double_counted_rather_than_guessed(monkeypatch):
    """No published spread means no subtraction. The sovereign risk stays double
    counted, which is visible in the number, rather than corrected by a figure
    nobody sourced."""
    assert fm.sovereign_default_spread("JPY") == 0.0
    assert fm.sovereign_default_spread(None) == 0.0


TENORS = ("3M", "6M", "1Y", "3Y", "5Y", "7Y", "10Y", "30Y")

# The other seven columns, taken from a real 2026-08-19 payload. Deliberately
# *plausible*: every one of them clears the sanity band, so a parse that picked
# the wrong column would return a believable number rather than failing. That is
# the whole failure this shape exists to expose, and it is why these are spread
# across the curve instead of being filler.
DECOYS = {"3M": "1.1906", "6M": "1.1936", "1Y": "1.1987", "3Y": "1.2455",
          "5Y": "1.3899", "7Y": "1.5215", "30Y": "2.1355"}

# The filter form that sits above the table. Its first cell is *also* "Yield
# Curve Name", so a header match on that alone picks it up and reads its
# dropdown as the tenor list. Included in every page below rather than in one
# dedicated test, so every CGB assertion carries the hazard.
_CHROME = ("<tr><td>Yield Curve Name</td><td>All\r\n\tChinaBond Government Bond"
           " Yield Curve</td><td>From:</td><td>To:</td><td>Maturity:</td>"
           "<td>All\r\n\t3M\r\n\t6M\r\n\t10Y</td></tr>")


def _cgb_page(rows, tenors=TENORS, drop=()):
    """A ChinaBond response, shaped like the real one.

    Real payloads carry three curves per date — government, commercial-bank AAA
    and CP&Note AAA — which is why the parse matches on the curve name rather
    than on position, and every tenor from 3M to 30Y across labelled columns,
    which is why it matches the *column* by its header rather than by index.
    `rows` is (curve, date, the 10-year yield as published, in percent); the
    other columns are filled from `DECOYS`.

    `drop` removes named columns from the data rows only, leaving the header
    intact — the shape a lost column actually takes, and the one that shifts
    every later value one place left.
    """
    kept = [t for t in tenors if t not in drop]
    header = "".join(f"<th>{t}</th>" for t in tenors)
    body = ""
    for curve, date, ten_year in rows:
        # "10Y" literally, NOT `data_provider.CGB_TENOR`. Reading the constant
        # made this helper move with it: mutating CGB_TENOR to "7Y" relabelled
        # the fixture's column too, so every value assertion went on passing and
        # only one test noticed. A fixture that tracks the code under test
        # cannot fail because of it.
        cells = "".join(
            f"<td>{ten_year if t == '10Y' else DECOYS.get(t, '1.0000')}</td>"
            for t in kept)
        body += f"<tr><td>{curve}</td><td>{date}</td>{cells}</tr>"
    return ("<html><body><table>"
            f"{_CHROME}"
            f"<tr><th>Yield Curve Name</th><th>Date</th>{header}</tr>"
            f"{body}</table></body></html>")


# `conftest.pinned_risk_free_rate` replaces `_cgb_10y` for every test, so the
# real one has to be held at import — otherwise these would assert against the
# stub and pass no matter what the parse did.
_real_cgb_10y = data_provider._cgb_10y


def _stub_cgb(monkeypatch, html):
    """Replace the HTTP call, not the function, so the parse itself runs.

    Returns the rate alone. `_cgb_10y` answers `(rate, live)` since the store
    arrived, and every assertion below is about the *parse* — unwrapping here
    keeps them so, and the `live` flag has its own tests rather than being
    carried through twenty that do not care about it.
    """
    class _Resp:
        def read(self): return html.encode("utf-8")
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(data_provider, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    out = _real_cgb_10y()
    return None if out is None else out[0]


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


def test_the_ten_year_is_taken_from_the_column_the_header_names(monkeypatch):
    """The point of asking for every tenor: the choice is made by label.

    Before 2026-08-20 the tenor was a URL parameter (`gjqx=10`) and the value
    was whatever came back, so a wrong tenor was unrepresentable *in a test* —
    the offline suite supplies its own HTML and never sees the URL. Now the
    column is found by its `10Y` heading, which is something a payload can be
    written to get wrong.

    Asserted against a page whose seven other columns are all plausible and all
    different, so picking any of them returns a believable number rather than
    failing: 1.1906 at the near end, 2.1355 at the far one.
    """
    rate = _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(0), "1.6831")]))
    assert rate == pytest.approx(0.016831)
    # named explicitly, because "not 3M" is the reading that would survive a
    # parse that simply took the last column instead of the first
    assert rate != pytest.approx(0.011906), "took the 3-month"
    assert rate != pytest.approx(0.015215), "took the 7-year"
    assert rate != pytest.approx(0.021355), "took the 30-year"


def test_a_row_narrower_than_its_header_is_refused(monkeypatch):
    """A dropped column shifts every later value one place left, and the row is
    still long enough to index.

    Lose 3M and the cell sitting under the `10Y` heading is the **30-year** —
    2.1355 where the ten-year is 1.6831. Matching the header's own width is the
    only way to see that from the payload, which is why the guard is
    `len(cells) == width` rather than `> tenor_col`.
    """
    assert _stub_cgb(monkeypatch, _cgb_page(
        [(GOV, _days_ago(0), "1.6831")], drop=("3M",))) is None


def test_a_header_without_a_ten_year_column_degrades(monkeypatch):
    """The new failure mode this change introduces, stated rather than hidden.

    If ChinaBond ever relabels the column, this returns None and CNY falls to
    `usd_proxy` — where the old `gjqx=10` code would have gone on serving
    whatever single value came back. A labelled degrade beats an unlabelled
    wrong number, but it is a trade and it deserves a test.
    """
    assert _stub_cgb(monkeypatch, _cgb_page(
        [(GOV, _days_ago(0), "1.6831")],
        tenors=("3M", "6M", "1Y", "3Y", "5Y", "7Y", "10Yr", "30Y"))) is None


def test_the_filter_form_is_not_mistaken_for_the_header(monkeypatch):
    """`cells[1] == "Date"` — the check that says which "Yield Curve Name" row
    is the header.

    **It does not bind on today's payload, and that is why this test is built
    the way it is.** The form sits *above* the table and its dropdown renders as
    one blob rather than as cells, so dropping the check leaves the real header
    to overwrite it a row later and nothing changes. Removing the check and
    running the suite gave 171 passed — a guard no test could fail.

    What it actually protects against is any *other* row opening with "Yield
    Curve Name": the form re-rendered with one cell per option, or the header
    markup changing so only the form matches. Both are the same class as every
    other drift this module guards, so the check stays and this is the payload
    that makes it bind — form-as-cells, real header gone.

    Without the check that page yields 1.6831 off the form's own column layout.
    With it, there is no header and therefore no rate, which is the honest
    answer for a table this parse no longer recognises.
    """
    form_as_cells = ("<tr><td>Yield Curve Name</td><td>All</td>"
                     + "".join(f"<td>{t}</td>" for t in TENORS) + "</tr>")
    gov = ("<tr><td>" + GOV + f"</td><td>{_days_ago(0)}</td>"
           + "".join(f"<td>{DECOYS.get(t, '1.6831')}</td>" for t in TENORS)
           + "</tr>")
    page = f"<html><body><table>{form_as_cells}{gov}</table></body></html>"
    assert _stub_cgb(monkeypatch, page) is None


def test_a_failed_cgb_fetch_is_never_cached(monkeypatch):
    """The property the whole failure contract rests on, and it was asserted in
    two docstrings and pinned by nothing.

    If a miss were cached for the day, one bad moment would hold every CNY
    valuation on whatever it fell back to until midnight — and the US proxy is
    30% of Tencent's fair value away. Because it is not, a miss costs one
    request.

    **This covers the no-store case only, and that is worth saying out loud.**
    The autouse fixture points the store at an empty `tmp_path`, so what runs
    here is "fetch failed and there was nothing to fall back on". Having a store
    is the steady state in production, and the same property there is pinned by
    `test_a_transient_failure_does_not_pin_the_stored_reading_all_day` — which
    exists because the property held here and was broken there.
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

    assert [_real_cgb_10y() for _ in range(3)] == [(pytest.approx(0.016864), True)] * 3
    assert len(calls) == 1, "the day cache did not hold"
    # The cached tuple has to carry the `live` flag too. Caching the rate alone
    # and rebuilding the flag would report every repeat call as live — including
    # the repeats of a day whose only reading came from the store.
    assert data_provider._CGB_CACHE[2] is True


def _dead_chinabond(monkeypatch):
    """ChinaBond unreachable, the way it actually fails: a timeout, not a 404."""
    def boom(*a, **k):
        raise OSError("timed out")
    monkeypatch.setattr(data_provider, "urlopen", boom)
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)


def test_a_good_reading_is_kept_for_the_next_run(monkeypatch):
    """The in-process day cache dies with the process, which is why this exists.

    What it cannot cover is the two cases that actually bite — a process that
    starts while ChinaBond is down, and the first request of a new calendar day.
    Both need the reading to outlive the run that took it.
    """
    assert _stub_cgb(monkeypatch, _cgb_page(
        [(GOV, _days_ago(1), "1.6864")])) == pytest.approx(0.016864)

    stored = data_provider._cgb_stored()
    assert stored is not None
    published, rate = stored
    assert rate == pytest.approx(0.016864)
    # the *published* date, not the fetch date — the whole staleness design
    # rests on those being the same measure in both paths
    assert published == _days_ago(1)


def test_a_stored_reading_carries_the_outage(monkeypatch):
    """The point of the whole thing, and the number that makes it worth having.

    Falling back to the US 10Y does not give a slightly worse answer, it gives a
    **US** rate on CNY cash flows — worth 30% of Tencent's fair value. A CNY
    yield a few days old keeps the currency right and costs only freshness.
    """
    _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(2), "1.6864")]))  # seed
    _dead_chinabond(monkeypatch)

    # Twice: the second call comes off the day cache, and it must still report
    # the reading as stored. Caching the rate alone and rebuilding the flag
    # would relabel every repeat call of an outage day as live.
    assert [_real_cgb_10y() for _ in range(2)] == [(pytest.approx(0.016864), False)] * 2

    # end to end through `risk_free_rate`, which needs the *real* `_cgb_10y`
    # put back — `conftest.pinned_risk_free_rate` replaces it for every test, so
    # without this the assertion would pass against the stub's own flag and
    # prove nothing about the store at all.
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    monkeypatch.setattr(data_provider, "_cgb_10y", _real_cgb_10y)
    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.0472)
    rate, source = data_provider.risk_free_rate(0.043, "CNY", 0.006)
    assert (round(rate, 6), source) == (0.010864, "cgb_10y_stored_less_spread")


def test_a_stored_reading_expires_on_the_same_bound_as_a_fetched_one(monkeypatch):
    """One constant, one meaning, both paths.

    `CGB_MAX_STALE_DAYS` is measured against the row's **published** date, so
    "this yield was published within a fortnight" says the same thing whether
    the fetch happened this morning or last Tuesday. Storing the *fetch* date
    instead would have let the two ages compound to 24 days with nobody choosing
    that.
    """
    # The value, not just the relationship. Deriving both inputs from the
    # constant made this test move with it: tightening 14 to 3 left it green,
    # because a "1 day inside" reading is inside whatever the bound is. That is
    # the same flaw as a fixture reading the code under test, one level up — the
    # relationship is worth asserting and cannot stand in for the number.
    assert data_provider.CGB_MAX_STALE_DAYS == 14
    inside = data_provider.CGB_MAX_STALE_DAYS - 1
    outside = data_provider.CGB_MAX_STALE_DAYS + 1

    _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(inside), "1.6864")]))
    _dead_chinabond(monkeypatch)
    assert _real_cgb_10y() == (pytest.approx(0.016864), False)

    data_provider._cgb_remember(_days_ago(outside), 0.016864)
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    assert _real_cgb_10y() is None, "a reading past the bound must not be served"


def test_a_broken_feed_is_not_papered_over_with_a_stored_reading(monkeypatch):
    """A fetch that *answers* with something out of band is a broken feed, not
    an absent one, and the store deliberately does not cover it.

    An outage says nothing about the data; a 68.64% print says the units moved.
    Falling back there would hide exactly the breakage the sanity band exists to
    surface.
    """
    _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(1), "1.6864")]))  # seed
    assert data_provider._cgb_stored() is not None

    assert _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(0), "68.64")])) is None


def test_a_transient_failure_does_not_pin_the_stored_reading_all_day(monkeypatch):
    """One flicker must not cost twenty-four hours, and it silently did.

    Caching the stored reading alongside the live one looked like symmetry and
    reversed the contract stated on `CGB_TIMEOUT_S`: *"a miss degrades one
    request to the USD proxy and the next request retries"* — the sentence the
    10-second timeout is justified by. With the stored reading cached, ChinaBond
    flickering for thirty seconds pinned a reading up to a fortnight old for the
    rest of the UTC day and never went back.

    The old `test_a_failed_cgb_fetch_is_never_cached` could not see it: the
    autouse fixture points the store at an empty `tmp_path`, so it only ever
    exercised the no-store case, while *having* a store is the steady state in
    production. A contract that holds in the test conditions and not the
    production ones is worse than no contract.
    """
    hits = []

    def _resp(html):
        class _R:
            def read(self): return html.encode("utf-8")
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R()

    _stub_cgb(monkeypatch, _cgb_page([(GOV, _days_ago(13), "1.6864")]))  # seed

    def down(*a, **k):
        hits.append("down")
        raise OSError("timed out")
    monkeypatch.setattr(data_provider, "urlopen", down)
    monkeypatch.setattr(data_provider, "_CGB_CACHE", None)
    assert _real_cgb_10y() == (pytest.approx(0.016864), False)
    assert data_provider._CGB_CACHE is None, "a stored reading must not be cached"

    recovered = _cgb_page([(GOV, _days_ago(0), "1.9000")])
    monkeypatch.setattr(data_provider, "urlopen",
                        lambda *a, **k: (hits.append("up"), _resp(recovered))[1])
    assert _real_cgb_10y() == (pytest.approx(0.019), True), "the retry never happened"
    assert hits.count("up") == 1


def test_the_sanity_band_retires_a_stored_reading_too(monkeypatch):
    """The band is the other check that has to mean the same thing in both
    paths, and only the staleness bound had a test saying so.

    A store written before a units change — or hand-edited — carries a number
    the live path would refuse, and refusing it there and not here would put the
    absurd rate back exactly where the band was meant to keep it out.
    """
    data_provider._cgb_remember(_days_ago(1), 0.6864)  # 68.64%, a units change
    _dead_chinabond(monkeypatch)
    assert _real_cgb_10y() is None


def test_an_unwritable_store_costs_the_fallback_and_not_the_valuation(monkeypatch):
    """A read-only checkout must lose the *next* outage its cushion, never this
    request its number — the rule every optional path in this module follows.

    The failure is injected rather than pointed at a path assumed unwritable.
    This used `Path("/nonexistent-root/...")`, which on Windows resolves under
    `C:\\` where an ordinary user *can* create directories: the write succeeded,
    the assertion passed down the success path, the test could not fail for the
    reason it existed, and every full run left a directory on the system drive.
    It also meant something different on Linux, where the same path needs root.
    """
    def boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(Path, "write_text", boom)

    assert _stub_cgb(monkeypatch, _cgb_page(
        [(GOV, _days_ago(0), "1.6864")])) == pytest.approx(0.016864)


def test_a_corrupt_store_reads_as_no_store(monkeypatch, tmp_path):
    """Half-written JSON, a hand-edit, a truncated disk. None of it may raise
    into a valuation, and none of it may read as *fresh*.

    The non-string cases are the sharp ones and they were missed first time.
    The staleness check downstream is a lexicographic comparison, so coercing
    with `str()` made it fail **open** — every one of these sorts above an ISO
    date and would have been served as permanently current. `20260819` is the
    realistic one: a date hand-written or migrated as an integer.

    The format cases guard the same comparison from the other side: `"/" > "-"`,
    so an upstream switch to `2026/08/20` would have disabled the staleness
    check entirely rather than tripping it.
    """
    bad = tmp_path / "corrupt.json"
    monkeypatch.setattr(data_provider, "CGB_STORE_PATH", bad)
    cases = [
        '{"published": "2026-08-19"',                  # truncated mid-write
        '{}', 'null', '[]',
        '{"published": "2026-08-19", "rate": "abc"}',  # unparseable rate
        '{"published": null, "rate": 0.0168}',         # -> "None", sorts high
        '{"published": true, "rate": 0.0168}',         # -> "True"
        '{"published": ["x"], "rate": 0.0168}',
        '{"published": {"a": 1}, "rate": 0.0168}',
        '{"published": 20260819, "rate": 0.0168}',     # the realistic one
        '{"published": "2026/08/19", "rate": 0.0168}',  # format change
        '{"published": "19-08-2026", "rate": 0.0168}',
        "[" * 400 + "]" * 400,                          # RecursionError in json
    ]
    for content in cases:
        bad.write_text(content, encoding="utf-8")
        assert data_provider._cgb_stored() is None, content


def test_the_cny_fixture_now_carries_a_chinese_rate_end_to_end(monkeypatch):
    """0700_HK through the real model, which is the only place the pairing is
    visible: a Chinese premium and a Chinese rate, where it was a Chinese
    premium and an American rate until 2026-08-19."""
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: (0.016864, True))
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


# ── the floor applies only where the regression cannot reject it ─────
#
# Both cases are real fixtures rather than constructed series, and they are the
# only two the floor has ever bound on. Measured across all eight, `BETA_MIN`
# sits inside exactly one confidence interval.

def test_an_imprecise_regression_below_the_floor_is_still_clamped():
    """XOM: measured 0.2888, interval [0.0828, 0.4948], R^2 0.0283.

    0.30 is **inside** that interval, so the data cannot separate the two and
    the floor keeps doing what it was written for. This is the half of the rule
    that must not change — a wide interval is exactly the thin-or-halted-series
    case `BETA_MIN` exists to catch.
    """
    a = fm._wacc(load_fundamentals("XOM"), 0.21, None,
                 (load_bars("XOM"), load_bars("_GSPC")))
    lo, hi = a["beta_confidence_interval"]
    assert lo <= fm.BETA_MIN <= hi, "this fixture stopped being the ambiguous case"
    assert a["beta_regressed"] == pytest.approx(0.2888, abs=1e-3)
    assert a["beta"] == fm.BETA_MIN


def test_a_precise_regression_below_the_floor_is_used_as_measured():
    """0002_HK: measured 0.1518, interval [0.0747, 0.2289].

    The whole interval lies **below** 0.30, so the measurement rejects the floor
    at 95% and clamping there overruled a good regression rather than guarding
    against a bad one. Worth 5.06% against 5.80% on the cost of equity, and
    74.05 against 97.27 on the fair value.
    """
    a = fm._wacc(load_fundamentals("0002_HK"), 0.165, None,
                 (load_bars("0002_HK"), load_bars("_HSI")))
    lo, hi = a["beta_confidence_interval"]
    assert hi < fm.BETA_MIN, "this fixture stopped being the decisive case"
    assert a["beta_regressed"] == pytest.approx(0.1518, abs=1e-3)
    assert a["beta"] == a["beta_regressed"], "the floor overruled a measurement"
    assert a["beta"] < fm.BETA_MIN


def test_the_ceiling_is_deliberately_left_alone():
    """`BETA_MAX` gets no interval treatment, and the absence is the decision.

    The same argument would apply to it, but no fixture comes near 2.5 — RIVN is
    the highest at 1.8371 — so changing it would be a change with no evidence
    behind it. Pinned so that "we did not touch it" stays a statement about
    evidence rather than about attention.

    **Both halves are asserted, and the first draft had only one.** It read
    `highest < BETA_MAX`, which pins the ceiling against being *lowered* into
    the data and says nothing about it being *raised* — moving 2.5 to 9.0 left
    it green, so the one direction the docstring is actually about was
    unguarded. The value is pinned outright, because "unchanged" is the claim.
    """
    assert fm.BETA_MAX == 2.5, "the ceiling moved; this test is the record that it should not"
    highest = max(
        fm._wacc(load_fundamentals(s), 0.21, None,
                 (load_bars(s), load_bars(HOME_INDEX.get(s, "_GSPC"))))["beta_regressed"]
        for s in FIXTURES)
    assert highest < fm.BETA_MAX, "a fixture now approaches the ceiling — revisit it"


def test_the_floor_and_the_values_it_decides_are_pinned():
    """The two fair values the whole beta argument is written around.

    Neither new beta test asserted them — both assert the *beta* — so `74.05`
    and `97.27` lived only in comments and the CHANGELOG and could drift without
    anything failing. The floor's own value is pinned here too: moving
    `BETA_MIN` to 0.4 was caught by the golden snapshot alone, and a golden
    failure says "something moved", not "the floor moved".
    """
    assert fm.BETA_MIN == 0.3

    def fair(stem, tax, override=None):
        return fm.dcf_valuation(load_fundamentals(stem), tax_rate=tax,
                                market_bars=load_market_bars(stem),
                                wacc_override=override)["fair_value_per_share"]

    # 0002_HK, freed by the interval — the case the change exists for.
    #
    # 97.27 until 2026-08-26, when HKD stopped borrowing the US risk-free rate.
    # The beta argument this test guards is unaffected — the floor still binds or
    # does not bind on the same interval — but the value it produces is now
    # struck at Hong Kong's own rate, so the old figure would pin a regime the
    # platform no longer runs. The two numbers below are therefore from
    # different rate regimes and are not a like-for-like pair; see the note on
    # the override.
    assert fair("0002_HK", 0.165) == pytest.approx(234.83, abs=0.01)
    # What the floor was producing instead. `override=0.0542` is a hard-coded
    # WACC, so this one is untouched by the rate change and still pins exactly
    # what it always did: what *that* WACC yields.
    assert fair("0002_HK", 0.165, override=0.0542) == pytest.approx(74.05, abs=0.01)
    # XOM, still clamped, still where it was
    assert fair("XOM", 0.21) == pytest.approx(157.30, abs=0.01)


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


# ── HKD gets a benchmark of its own ──────────────────────────────────
#
# The second currency to stop borrowing the US rate, and the second time the
# reason is that a peg fixes an exchange rate rather than a term structure:
# Hong Kong's own ten-year sat at 3.495% on 2026-08-26 against the US 4.70%.
#
# The parse is tested over a DataFrame rather than a real workbook. `xlrd` and
# `openpyxl` are both absent from `requirements-test.txt`, so a test that built
# a genuine spreadsheet could not run in CI at all — and what needs pinning is
# the grid walk, which is the new code. That pandas can read the real file is a
# different claim, and `test_provider_live.py` makes it against the real file.

_real_hkgb_10y = data_provider._hkgb_10y

# The tenors the workbook actually publishes, in order. Two 1-year floaters, so
# the ten-year is neither first nor last and an off-by-one lands on a real
# neighbour with a plausible yield — exactly the failure the label anchors exist
# to make unrepresentable.
HKGB_TENORS = ("1-year*", "1-year*", "3-year", "5-year", "7-year",
               "10-year", "15-year", "20-year")
# In-band decoys, taken from the shape of the real 2026-08-25 sheet, so a wrong
# column reads as a believable yield rather than failing loudly.
HKGB_DECOYS = {"1-year*": 2.61, "3-year": 3.11, "5-year": 3.15,
               "7-year": 3.28, "15-year": 3.82, "20-year": 4.37}


def _hkgb_book(rows, tenors=HKGB_TENORS, yield_label="Yield",
               tenor_label="Tenor", trailing_prose=True, yield_first=False):
    """A DataFrame shaped like the workbook's Benchmark sheet.

    Column 0 carries the row labels; each tenor occupies a Price column with its
    Yield in the next one. `rows` is `[(date, ten_year_yield)]`.
    """
    from datetime import datetime

    import pandas as pd
    width = 1 + 2 * len(tenors)
    grid = [[None] * width for _ in range(9)]
    grid[0][0] = "Daily HKD Institutional Government Bond Closing Reference Pricings"
    grid[4][0] = tenor_label
    grid[5][0] = "Issue code"
    grid[7][0] = "Maturity date"
    for i, t in enumerate(tenors):
        grid[4][1 + 2 * i] = t
        grid[5][1 + 2 * i] = f"{i:02d}GB3507001"
        # `yield_first` puts the Yield column *before* its Price instead of
        # after. The sheet as published is Price-then-Yield, so this is the
        # layout change that makes `tenor_col + 1` land on a price — the exact
        # off-by-one the label check exists to refuse.
        grid[8][1 + 2 * i] = yield_label if yield_first else "Price"
        grid[8][2 + 2 * i] = "Price" if yield_first else yield_label
    grid.append([None] * width)          # the blank band between header and data
    for day, ten in rows:
        row = [None] * width
        row[0] = datetime.strptime(day, "%Y-%m-%d")
        for i, t in enumerate(tenors):
            y = ten if t == "10-year" else HKGB_DECOYS.get(t, 3.0)
            row[1 + 2 * i] = y if yield_first else 99.0
            row[2 + 2 * i] = 99.0 if yield_first else y
        grid.append(row)
    if trailing_prose:
        # Rows 37-40 of the real sheet are disclaimer text sitting in the date
        # column. `iloc[-1]` reads legal prose where a date should be.
        for text in ("While The Government of the Hong Kong Special Administrative "
                     "Region endeavours to provide a continuous and timely service",
                     "By reviewing or downloading any reference yield you accept "
                     "this disclaimer and agree to its terms and conditions."):
            row = [None] * width
            row[0] = text
            # Numbers in the yield columns of a prose row. The published sheet
            # leaves them blank, and a fixture that copies that cannot tell the
            # date filter apart from the NaN check beside it — measured, the
            # `isinstance(day, datetime)` guard survived a mutation run until
            # these were added. A footnote carrying a figure is the realistic
            # shape this protects against.
            for i in range(len(tenors)):
                row[1 + 2 * i] = 9.99
                row[2 + 2 * i] = 9.99
            grid.append(row)
    return {"Daily GB Closings - Benchmark": pd.DataFrame(grid)}


def _stub_hkgb(monkeypatch, book):
    """Replace the download and the workbook read, not the function under test.

    `_hkgb_fetch` imports pandas inside itself, so patching `pandas.read_excel`
    reaches it: the import resolves the already-patched module. Everything after
    that — the three text anchors, the date filter, the newest-row choice — is
    the real code.
    """
    import pandas as pd

    class _Resp:
        def read(self): return b"not-really-a-workbook"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(data_provider, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: book)
    monkeypatch.setattr(data_provider, "_HKGB_CACHE", None)
    out = _real_hkgb_10y()
    return None if out is None else out[0]


def test_the_hkd_ten_year_is_read_by_its_own_label(monkeypatch):
    """The happy path, and the reason the label matters.

    Every tenor beside the ten-year carries a plausible in-band decoy, so a
    parse that took the wrong column would return a number no band could reject.
    """
    rate = _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(1), 3.495)]))
    assert rate == pytest.approx(0.03495)


def test_a_renamed_tenor_degrades_instead_of_taking_a_neighbour(monkeypatch):
    """If the sheet stops saying `10-year` this must refuse, not guess.

    The 7-year and 15-year sit either side at 3.28% and 3.82% — both inside any
    sane band — so guessing would be undetectable.
    """
    tenors = tuple("10Y" if t == "10-year" else t for t in HKGB_TENORS)
    assert _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(1), 3.495)], tenors=tenors)) is None

    # And the column is found rather than assumed. In the sheet as published the
    # ten-year happens to sit at index 11, so a parse that hard-coded 11 reads
    # correctly and no fixture built to match the real layout can tell —
    # measured, that mutation survived. An extra tenor in front moves it.
    shifted = ("2-year",) + HKGB_TENORS
    assert _stub_hkgb(monkeypatch,
                      _hkgb_book([(_days_ago(1), 3.495)], tenors=shifted))         == pytest.approx(0.03495)


def test_a_price_column_is_never_read_as_a_yield(monkeypatch):
    """The guard that makes an off-by-one unrepresentable.

    `yield_first` swaps the Price/Yield pair, so the cell beside the ten-year
    tenor says `Price` while a `Yield` band still exists on the row. That is the
    only shape that isolates this check: renaming the band outright is refused
    one line earlier, when no row contains `Yield` at all, so a test written
    that way passes without the guard — measured, it survived a mutation run.
    Without the check this returns 99.0, a price, as a 9900% rate.
    """
    book = _hkgb_book([(_days_ago(1), 3.495)], yield_first=True)
    assert _stub_hkgb(monkeypatch, book) is None

    # ...and the band being absent entirely is still refused, one line earlier.
    assert _stub_hkgb(monkeypatch,
                      _hkgb_book([(_days_ago(1), 3.495)], yield_label="Yld")) is None


def test_the_disclaimer_rows_are_not_read_as_data(monkeypatch):
    """`iloc[-1]` would read legal prose out of the date column.

    Asserted by giving the newest real row a value nothing else has, so a parse
    that fell off the end of the table cannot accidentally agree.
    """
    rows = [(_days_ago(3), 3.100), (_days_ago(2), 3.200), (_days_ago(1), 3.495)]
    assert _stub_hkgb(monkeypatch, _hkgb_book(rows)) == pytest.approx(0.03495)


def test_the_newest_row_wins_whatever_order_the_sheet_is_in(monkeypatch):
    """Chosen by date rather than by position — nothing documents the order."""
    rows = [(_days_ago(1), 3.495), (_days_ago(9), 1.000), (_days_ago(4), 2.000)]
    assert _stub_hkgb(monkeypatch, _hkgb_book(rows)) == pytest.approx(0.03495)


def test_a_frozen_hkgb_workbook_expires_on_its_published_date(monkeypatch):
    """A stale sheet is well-formed and plausible; only its date says otherwise.

    The bound is the constant's own value rather than a figure derived from it:
    deriving both sides lets the constant move without the test noticing, which
    is the mistake the CGB equivalent records having made.
    """
    assert data_provider.HKGB_MAX_STALE_DAYS == 14
    assert _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(13), 3.495)])) is not None
    assert _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(15), 3.495)])) is None


@pytest.mark.parametrize("published_yield", [0.0, -1.5, 25.0, 99.0])
def test_a_hkd_yield_outside_the_band_is_refused(monkeypatch, published_yield):
    """The workbook quotes percent; a switch to ratios would divide by 100, and
    a price read as a yield would arrive as 99. Both land outside 0 < r < 0.25."""
    assert _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(1), published_yield)])) is None


def test_a_transient_hkgb_failure_does_not_pin_the_stored_reading_all_day(monkeypatch):
    """The load-bearing asymmetry, mirrored from the CGB store.

    Only a *live* reading is cached. Were the stored one cached too, one timeout
    would serve a reading up to a fortnight old for the rest of the UTC day and
    never retry — which is precisely the sticky failure the timeout is not sized
    for. The count is the assertion: upstream must be contacted every time.
    """
    monkeypatch.setattr(data_provider, "_HKGB_CACHE", None)
    data_provider._hkgb_remember(_days_ago(1), 0.03495)

    calls = []

    def _down(*a, **k):
        calls.append(1)
        raise OSError("hkgb.gov.hk did not answer")
    monkeypatch.setattr(data_provider, "urlopen", _down)

    assert [_real_hkgb_10y() for _ in range(3)] == [(pytest.approx(0.03495), False)] * 3
    assert len(calls) == 3, "a stored reading must not suppress the retry"


def test_a_live_hkd_reading_is_stored_for_the_next_run(monkeypatch):
    """The store exists because the workbook is a rolling month, not an archive:
    a reading that is not kept is a reading that is gone."""
    monkeypatch.setattr(data_provider, "_HKGB_CACHE", None)
    assert _stub_hkgb(monkeypatch, _hkgb_book([(_days_ago(1), 3.495)])) is not None
    assert data_provider._hkgb_stored() == (_days_ago(1), pytest.approx(0.03495))


def test_a_corrupt_hkd_store_reads_as_no_store(monkeypatch):
    """A damaged file costs the fallback, never the valuation — and the date is
    parsed rather than coerced, so a non-string cannot sort as permanently
    fresh."""
    for junk in ('{"published": null, "rate": 0.035}',
                 '{"published": 20260825, "rate": 0.035}',
                 '{"published": "2026/08/25", "rate": 0.035}',
                 "[" * 400 + "]" * 400,
                 "not json at all"):
        data_provider.HKGB_STORE_PATH.write_text(junk, encoding="utf-8")
        assert data_provider._hkgb_stored() is None, junk[:40]


def test_an_unwritable_hkd_store_costs_the_fallback_and_not_the_valuation(monkeypatch):
    """A read-only checkout must lose the next outage its fallback, never this
    request its answer."""
    def _boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(data_provider.Path, "write_text", _boom)
    data_provider._hkgb_remember("2026-08-25", 0.03495)  # must not raise


def test_hkd_is_priced_off_hong_kongs_own_benchmark_net_of_its_default_spread(monkeypatch):
    """The same arithmetic CNY gets, and for the same reason: a government yield
    is not risk-free, and the country-inclusive ERP paired with it carries that
    spread a second time. Subtracting once removes the double count."""
    monkeypatch.setattr(data_provider, "_hkgb_10y", lambda: (0.03495, True))

    rate, source = data_provider.risk_free_rate(0.043, "HKD", 0.0051)
    assert (round(rate, 6), source) == (0.02985, "hkgb_10y_less_spread")

    # The stored reading is the same number wearing a different label, because a
    # reader deciding what to trust needs to know which one they have.
    monkeypatch.setattr(data_provider, "_hkgb_10y", lambda: (0.03495, False))
    assert data_provider.risk_free_rate(0.043, "HKD", 0.0051)[1] == \
        "hkgb_10y_stored_less_spread"

    # And an unreachable benchmark degrades to exactly what it did before.
    monkeypatch.setattr(data_provider, "_hkgb_10y", lambda: None)
    assert data_provider.risk_free_rate(0.043, "HKD", 0.0051)[1] == "usd_proxy"


@pytest.mark.parametrize("hkgb", [0.0050, 0.0051, 0.002, 0.0])
def test_a_yield_below_the_hkd_spread_never_becomes_a_negative_rate(monkeypatch, hkgb):
    """`_hkgb_10y`'s band guards the published yield; the subtraction happens
    outside it, and 51bp is enough to net a low print to zero or below. A
    negative risk-free rate caps terminal growth negative through
    `min(TERMINAL_GROWTH, rf)` — the model asserting perpetual shrinkage for a
    going concern, with no error and no flag."""
    monkeypatch.setattr(data_provider, "_hkgb_10y", lambda: (hkgb, True))
    assert data_provider.risk_free_rate(0.043, "HKD", 0.0051)[1] == "usd_proxy"


# ── the precision the fair value rests on ────────────────────────────

def test_the_terminal_spread_is_published_rather_than_thresholded():
    """`WACC - g` is the terminal value's denominator, so the answer scales as
    its reciprocal and the sensitivity as the reciprocal squared. Published so a
    reader can weigh it; no cutoff, because none has evidence behind it."""
    d = fm.dcf_valuation(load_fundamentals("0002_HK"), tax_rate=0.165,
                         market_bars=load_market_bars("0002_HK"))
    a, diag = d["assumptions"], d["diagnostics"]
    assert diag["terminal_spread"] == pytest.approx(a["wacc"] - a["terminal_growth"], abs=1e-9)
    # A utility at Hong Kong's own rate is the tight case this exists to show.
    assert diag["terminal_spread"] < 0.02
    # ...and a US mega-cap is not, so the field is not merely always small.
    us = fm.dcf_valuation(load_fundamentals("AAPL"), tax_rate=0.21,
                          market_bars=load_market_bars("AAPL"))
    assert us["diagnostics"]["terminal_spread"] > 0.05


def test_cost_of_equity_below_debt_is_flagged_and_never_corrected():
    """An inequality between two computed inputs, not a tuned threshold: a
    lender ranks ahead of a shareholder, so a share cannot require less return
    than the bond above it. CAPM produces it anyway when `beta x ERP` comes in
    under the credit spread, and the figures are reported as computed."""
    d = fm.dcf_valuation(load_fundamentals("0002_HK"), tax_rate=0.165,
                         market_bars=load_market_bars("0002_HK"))
    a, diag = d["assumptions"], d["diagnostics"]
    assert diag["cost_of_debt_pre_tax"] == pytest.approx(
        a["risk_free_rate"] + a["credit_spread"], abs=1e-9)
    assert diag["cost_of_equity_below_debt"] is True
    # Never corrected: the inversion is still there in the numbers themselves.
    assert a["cost_of_equity"] < diag["cost_of_debt_pre_tax"]

    # The control, or the flag would look identical to one that is always true.
    us = fm.dcf_valuation(load_fundamentals("AAPL"), tax_rate=0.21,
                          market_bars=load_market_bars("AAPL"))
    assert us["diagnostics"]["cost_of_equity_below_debt"] is False
