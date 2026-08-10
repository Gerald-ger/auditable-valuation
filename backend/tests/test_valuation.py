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
    share of the cheaper after-tax cost of debt."""
    f = load_fundamentals("0700_HK")
    g = load_fundamentals("0700_HK")
    g["info"]["financialCurrency"] = "HKD"

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
    assert dcf["fair_value_per_share"] == pytest.approx(143.99, rel=1e-3)


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
