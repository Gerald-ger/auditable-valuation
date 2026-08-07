"""Valuation-engine behaviour: beta resolution, credit spread, two-stage
projection, jurisdiction tax and the DCF trust diagnostics.

These cover the pure logic. The one part that is not pure — fetching peer betas
when a reported beta is implausible — is wired in main.py and smoke-tested live,
because pulling the network into this suite would defeat its purpose.
"""
from __future__ import annotations

import copy

import pytest

from conftest import load_fundamentals

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
    spread, coverage = fm._credit_spread(_with_coverage(ebit, interest))
    assert spread == expected
    assert coverage == pytest.approx(ebit / interest)


def test_credit_spread_defaults_when_coverage_is_unavailable():
    assert fm._credit_spread({"income_statement": {}}) == (fm.DEFAULT_CREDIT_SPREAD, None)


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
