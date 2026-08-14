"""Valuation-engine behaviour: beta resolution, credit spread, two-stage
projection, jurisdiction tax and the DCF trust diagnostics.

These cover the pure logic. The one part that is not pure — fetching peer betas
when a reported beta is implausible — is wired in main.py and smoke-tested live,
because pulling the network into this suite would defeat its purpose.
"""
from __future__ import annotations

import copy

import pytest

from conftest import TEST_CNY_HKD, load_fundamentals

import financial_models as fm


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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    coverage, period = fm.interest_coverage(income)
    assert period == "2023-12-31"
    assert coverage == pytest.approx(30.0)        # 300/10, not 500/10


def test_interest_coverage_prefers_the_newest_complete_period():
    income = {"2025-12-31": {"EBIT": 500.0, "Interest Expense": 10.0},
              "2023-12-31": {"EBIT": 300.0, "Interest Expense": 10.0}}
    assert fm.interest_coverage(income) == (pytest.approx(50.0), "2025-12-31")


def test_interest_coverage_is_none_when_no_period_reports_both():
    assert fm.interest_coverage({"2025-12-31": {"EBIT": 500.0}}) == (None, None)


def test_aapl_interest_coverage_reads_one_year(monkeypatch):
    """The fixture this was found on. The pinned period is stale — yfinance has
    not reported AAPL's interest since 2023 — but stale-and-consistent is a
    ratio, and fresh-over-stale is not."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    coverage, period = fm.interest_coverage(f["income_statement"])
    assert period == "2023-09-30"
    ebit = fm._value_at(f["income_statement"], period, "EBIT", "Operating Income")
    interest = fm._value_at(f["income_statement"], period, "Interest Expense")
    assert coverage == pytest.approx(ebit / abs(interest))
    # the ratio the two-call version produced, for the record
    assert coverage != pytest.approx(
        fm._latest(f["income_statement"], "EBIT", "Operating Income") / abs(interest))


def test_ratio_analysis_reports_the_period_its_coverage_came_from():
    ratios = fm.ratio_analysis(load_fundamentals("AAPL"))
    assert ratios["solvency"]["interest_coverage_period"] == "2023-09-30"


# ── a missing bridge leg is named, not silently zeroed ───────────────

def test_net_debt_names_the_leg_it_had_to_assume(monkeypatch):
    """`or 0` keeps the DCF working when one field is absent, but an unreported
    totalDebt otherwise reads as a debt-free company: AAPL 143.99 -> 147.41."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    assert fm.dcf_valuation(f)["diagnostics"]["net_debt_assumed_zero"] == []

    f["info"]["totalDebt"] = None
    assert fm.dcf_valuation(f)["diagnostics"]["net_debt_assumed_zero"] == ["total_debt"]


def test_both_missing_bridge_legs_are_named(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    """
    f = load_fundamentals("0700_HK")
    # same company, told its statements are already in HKD -> no conversion
    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"

    wacc = fm.dcf_valuation(g)["assumptions"]["wacc_used"]
    converted = fm.dcf_valuation(f, wacc_override=wacc)
    unconverted = fm.dcf_valuation(g, wacc_override=wacc)

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
    """
    f = load_fundamentals("0700_HK")
    converted = fm.dcf_valuation(f)

    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"
    unconverted = fm.dcf_valuation(g)

    # hold WACC fixed so only the conversion is under test
    same_wacc = fm.dcf_valuation(f, wacc_override=unconverted["assumptions"]["wacc_used"])
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
    # matched the one-year horizon of the consensus that feeds it; 141.17 now
    # that the US premium is Damodaran's published 4.46% rather than a flat 5%
    assert dcf["fair_value_per_share"] == pytest.approx(141.17, rel=1e-3)


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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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


def test_two_stage_raises_valuation_versus_a_single_five_year_fade(monkeypatch):
    """A durable compounder gets more than five years before the fade starts."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    d = fm.dcf_valuation(load_fundamentals(stem))
    diag = d["diagnostics"]
    assert 0 < diag["terminal_value_share"] < 1
    assert diag["terminal_value_high"] == (diag["terminal_value_share"] > 0.75)
    assert diag["implied_exit_ev_ebitda"] > 0


def test_terminal_share_rises_as_wacc_approaches_terminal_growth(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    tight = fm.dcf_valuation(f, wacc_override=0.05)["diagnostics"]["terminal_value_share"]
    wide = fm.dcf_valuation(f, wacc_override=0.12)["diagnostics"]["terminal_value_share"]
    assert tight > wide


def test_implied_exit_multiple_is_absent_without_ebitda(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    f["estimates"] = {}
    f["info"]["revenueGrowth"] = None
    a = fm.dcf_valuation(f)["assumptions"]

    assert a["growth_rate_year1"] == fm.DEFAULT_GROWTH_RATE
    assert a["growth_source"] == "default_assumed"


def test_each_growth_provenance_gets_its_own_label(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    f["estimates"] = {"revenue_growth_fwd": 0.11}
    assert fm.dcf_valuation(f)["assumptions"]["growth_source"] == "analyst_consensus_fwd"

    f["estimates"] = {}
    f["info"]["revenueGrowth"] = 0.07
    assert fm.dcf_valuation(f)["assumptions"]["growth_source"] == "trailing_revenue_growth"


def test_a_reconcilable_gap_names_the_assumption_that_closes_it(monkeypatch):
    """0700.HK's DCF sits above the price, but only on the terminal assumption —
    it meets the market at a terminal rate below what an economy grows. That is
    a forecast disagreement, and saying so is different from saying the market
    is wrong."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("0700_HK")
    r = fm.reconcile_to_price(f, fm.dcf_valuation(f))
    assert r["verdict"] == "reconcilable"
    assert r["required_terminal_growth"] <= fm.NOMINAL_GDP_GROWTH


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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
        monkeypatch.setattr(fm, "risk_free_rate", lambda fb, v=rate: v)
        verdicts.add(fm.reconcile_to_price(f, fm.dcf_valuation(f))["verdict"])
    assert verdicts == {"irreconcilable"}


def test_a_small_gap_is_left_alone(monkeypatch):
    """Within 10% there is no binding assumption to name, and naming one would
    be reading noise."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("AAPL")
    d = fm.dcf_valuation(f)
    d["current_price"] = d["fair_value_per_share"] * 1.04
    r = fm.reconcile_to_price(f, d)
    assert r["verdict"] == "aligned"
    assert r["required_terminal_growth"] is None


def test_the_back_solver_returns_none_outside_its_reachable_band(monkeypatch):
    """The generalised solver underneath both back-solves. 'No rate in this band
    gets you there' is the result that makes a gap irreconcilable."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    q = fm.dcf_valuation(load_fundamentals("MSFT"))["diagnostics"]["base_fcf_quality"]

    assert q["anomalous"] is True
    assert sum(r["value"] for r in q["bridge"]) == pytest.approx(q["normalised_fcf"], abs=2)


def test_a_normalised_base_never_replaces_the_reported_one(monkeypatch):
    """The platform can detect an anomaly but cannot read the notes to identify
    its cause, so the adjustment stays an alternative shown beside the headline.
    Substituting it would be exactly the silent correction the design forbids."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("MSFT")
    d = fm.dcf_valuation(f)
    reported = fm._statement_fcf(f["cash_flow"])[1]
    q = d["diagnostics"]["base_fcf_quality"]

    assert q["normalised_fcf"] != reported          # an alternative exists
    assert d["assumptions"]["base_fcf"] >= reported  # ...and the DCF did not use it
    assert d["assumptions"]["base_fcf"] - reported == d["assumptions"]["fcf_interest_addback"]


def test_growth_alone_does_not_trip_the_base_anomaly_detector(monkeypatch):
    """Cash conversion is the trigger, not the level of free cash flow. Measured
    2026-08-13, an FCF-vs-own-median test fired on NVDA (+120%) and AMD (+144%)
    where nothing was wrong; both sit inside 8% on conversion."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    f = load_fundamentals("MSFT")
    periods = sorted(f["cash_flow"], reverse=True)
    f["cash_flow"] = {p: f["cash_flow"][p] for p in periods[:2]}
    q = fm.base_fcf_quality(f, periods[0])
    assert q["anomalous"] is False and q["deviation"] is None


def test_market_implied_growth_is_absent_without_a_traded_multiple(monkeypatch):
    """No multiple, no question to ask — and a fabricated one would be worse
    than silence, the same rule the exit multiple above follows."""
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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


def test_hk_listing_uses_the_hk_rate(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    d = fm.dcf_valuation(load_fundamentals("0700_HK"))
    assert d["assumptions"]["tax_rate"] == 0.165


def test_explicit_tax_rate_still_overrides(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    d = fm.dcf_valuation(load_fundamentals("0700_HK"), tax_rate=0.30)
    assert d["assumptions"]["tax_rate"] == 0.30


# ── period pinning (item 5) ──────────────────────────────────────────

def test_statement_fcf_returns_the_period_it_used():
    period, fcf = fm._statement_fcf(load_fundamentals("MSFT")["cash_flow"])
    assert period == "2026-06-30"
    assert fcf == pytest.approx(66_987_000_000.0)


def test_statement_fcf_requires_both_legs_in_one_period():
    cash_flow = {
        "2025-12-31": {"Operating Cash Flow": 100.0},               # no CapEx
        "2024-12-31": {"Operating Cash Flow": 90.0, "Capital Expenditure": -30.0},
    }
    assert fm._statement_fcf(cash_flow) == ("2024-12-31", 60.0)


def test_value_at_does_not_reach_into_another_period():
    statement = {"2025-12-31": {"Net Income": 100.0}, "2024-12-31": {"Net Income": 90.0}}
    assert fm._value_at(statement, "2025-12-31", "Net Income") == 100.0
    assert fm._value_at(statement, "2023-12-31", "Net Income") is None


def test_dcf_reports_the_fcf_period(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    d = fm.dcf_valuation(load_fundamentals("AAPL"))
    assert d["assumptions"]["fcf_period"] == "2025-09-30"
    assert d["assumptions"]["fcf_source"] == "cash_flow_statement"


def test_dcf_still_falls_back_to_info_freecashflow(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    period, _ = fm._statement_fcf(f["cash_flow"])
    addback, basis = fm._fcff_interest_addback(f["cash_flow"], period, 0.165)
    assert (addback, basis) == (0.0, "not_required_interest_in_financing")


def test_us_gaap_cash_interest_is_added_back_after_tax():
    """XOM discloses 1,752M paid in the same period its FCF comes from."""
    f = load_fundamentals("XOM")
    period, _ = fm._statement_fcf(f["cash_flow"])
    addback, basis = fm._fcff_interest_addback(f["cash_flow"], period, 0.21)
    assert basis == "cash_interest_paid"
    assert addback == pytest.approx(1_752_000_000.0 * 0.79)


def test_unverifiable_classification_is_left_alone():
    """MSFT reports no interest row in any captured period. Guessing which side
    of the cash-flow statement it sits on would be worse than not adjusting."""
    f = load_fundamentals("MSFT")
    period, _ = fm._statement_fcf(f["cash_flow"])
    addback, basis = fm._fcff_interest_addback(f["cash_flow"], period, 0.21)
    assert (addback, basis) == (0.0, "unverified_interest_classification")


def test_no_statement_period_means_no_addback():
    """The info["freeCashflow"] fallback has no period to pin interest to."""
    assert fm._fcff_interest_addback({}, None, 0.21) == (0.0, "no_statement_fcf")


def test_addback_uses_magnitude_not_sign():
    cash_flow = {"2025-12-31": {"Interest Paid Supplemental Data": -400.0}}
    addback, _ = fm._fcff_interest_addback(cash_flow, "2025-12-31", 0.25)
    assert addback == pytest.approx(300.0)


def test_financing_classification_wins_over_a_cash_interest_row():
    """If both appear, operating cash flow is still unlevered — do not add back."""
    cash_flow = {"2025-12-31": {"Interest Paid Cff": -400.0,
                                "Interest Paid Supplemental Data": 400.0}}
    assert fm._fcff_interest_addback(cash_flow, "2025-12-31", 0.21)[1] == \
        "not_required_interest_in_financing"


def test_statement_fcf_stays_levered_for_the_scoring_metrics():
    """fcf_yield divides by market cap and fcf_conversion by net income, both of
    which are after interest. Unlevering here would corrupt both."""
    f = load_fundamentals("XOM")
    period, fcf = fm._statement_fcf(f["cash_flow"])
    rows = f["cash_flow"][period]
    assert fcf == pytest.approx(rows["Operating Cash Flow"] + rows["Capital Expenditure"])


def test_dcf_raises_fair_value_when_interest_is_added_back(monkeypatch):
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
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
    monkeypatch.setattr(fm, "RISK_FREE_RATE", 0.006)
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: 0.006)
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
    ctx = fm.base_year_context(f, fm._statement_fcf(f["cash_flow"])[0])
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
        return fm.base_year_context(f, fm._statement_fcf(f["cash_flow"])[0])["driver"]

    assert driver("MSFT") == "capital_spending"
    assert driver("XOM") == "capital_spending"
    assert driver("AAPL") == "operating_cash"


def test_a_representative_year_names_no_driver():
    """There is nothing to explain when the base year is already normal, and
    naming a driver anyway would invent a story out of rounding."""
    f = load_fundamentals("AAPL")
    period = fm._statement_fcf(f["cash_flow"])[0]
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
    statement_fcf = fm._statement_fcf(f["cash_flow"])[1]
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
        ctx = fm.base_year_context(f, fm._statement_fcf(f["cash_flow"])[0])
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
        ctx = fm.base_year_context(f, fm._statement_fcf(f["cash_flow"])[0])
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
