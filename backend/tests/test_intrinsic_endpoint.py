"""Editing the assumptions of a model a DCF cannot build.

The DCF has had a what-if endpoint since long before these two models existed.
They had none, so the Financial Models tab could show a bank its valuation and
not let it ask what the valuation would be at a different return on equity —
which is most of what a valuation is for.

What this file pins is the *contract*, not the arithmetic: which overrides each
model accepts, which requests are refused before a model runs, and — the part
that matters — that an override cannot talk a model out of its own refusals.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from conftest import load_fundamentals, load_market_bars

from backend import financial_models as fm


@pytest.fixture
def endpoint(monkeypatch):
    """`custom_intrinsic` with every provider stubbed. No network.

    Called directly rather than through a client, which is how `test_comps.py`
    exercises `comps_endpoint` — there is no `TestClient` anywhere in this suite
    and adding one for a single route would be a second way to do one thing.
    """
    from backend import main

    monkeypatch.setattr(main.provider, "get_fundamentals",
                        lambda ticker: load_fundamentals(ticker.replace(".", "_")))
    monkeypatch.setattr(main, "_peer_beta_inputs", lambda f: None)
    monkeypatch.setattr(main, "_market_bars",
                        lambda ticker: load_market_bars(ticker.replace(".", "_")))
    return main.custom_intrinsic


@pytest.fixture
def body():
    from backend.main import IntrinsicAssumptions
    return IntrinsicAssumptions


# ── the default: an empty body must reproduce what the tab already shows ──

def test_an_empty_body_returns_exactly_what_the_read_only_panel_shows(endpoint, body):
    """The what-if with nothing changed is the valuation itself.

    Worth asserting rather than assuming: the endpoint resolves the
    classification, the peers and the bars on its own, and any of those drifting
    from what `full_analysis` does would put a different number under the same
    heading the moment a user pressed Recalculate without typing anything.
    """
    live = endpoint("JPM", body())
    shown = fm.excess_returns_valuation(
        load_fundamentals("JPM"), market_bars=load_market_bars("JPM"))

    assert live["fair_value_per_share"] == shown["fair_value_per_share"]
    assert live["assumptions"]["roe"] == shown["assumptions"]["roe"]
    assert live["assumptions"]["roe_source"] == "normalised_mean"
    assert live["assumptions"]["cost_of_equity_source"] == "capm"


# ── the overrides each model actually takes ──────────────────────────

def test_a_bank_takes_a_return_on_equity(endpoint, body):
    out = endpoint("JPM", body(roe=0.20))

    assert out["assumptions"]["roe"] == pytest.approx(0.20)
    assert out["assumptions"]["roe_source"] == "user"
    # Retention is held, so a swept return on equity moves the growth rate with
    # it — the coupling the model documents rather than pinning one and sweeping
    # the other.
    assert out["assumptions"]["growth_rate_explicit"] == pytest.approx(
        0.20 * out["assumptions"]["retention_ratio"])
    assert out["fair_value_per_share"] > endpoint("JPM", body())["fair_value_per_share"]


def test_a_reit_takes_a_dividend_growth_rate(endpoint, body):
    """And on O it takes a cost of equity with it, which is the point.

    The inversion refusal runs before the growth rate is used, so a body
    carrying only `growth_rate` still refuses — O's regressed beta puts its cost
    of equity at 6.20% against a 7.30% pre-tax cost of debt, and nothing about a
    dividend forecast changes that. The endpoint is therefore the only route by
    which this REIT can be valued at all: a reader who thinks 0.4263 is a
    regression artefact rather than a risk measure can say so, in a number, and
    see what the model does with it. That is the whole argument for making the
    assumptions editable rather than only visible.
    """
    assert "error" in endpoint("O", body())
    assert "error" in endpoint("O", body(growth_rate=0.06))

    out = endpoint("O", body(growth_rate=0.06, cost_of_equity=0.09))
    assert out["assumptions"]["growth_rate_explicit"] == pytest.approx(0.06)
    assert out["assumptions"]["growth_source"] == "user"
    assert out["assumptions"]["cost_of_equity_used"] == pytest.approx(0.09)
    assert out["fair_value_per_share"] > 0


@pytest.mark.parametrize("stem", ["JPM", "O"])
def test_both_take_a_cost_of_equity_and_a_terminal_growth(endpoint, body, stem):
    out = endpoint(stem, body(cost_of_equity=0.11, terminal_growth=0.015))
    a = out["assumptions"]

    assert a["cost_of_equity_used"] == pytest.approx(0.11)
    assert a["cost_of_equity_source"] == "user"
    assert a["terminal_growth"] == pytest.approx(0.015)
    assert a["terminal_growth_source"] == "user"
    # Sending a terminal growth overrides the ceilings rather than being held
    # under them — that is what a what-if is for, and the source says which.
    assert a["terminal_growth"] < a["terminal_growth_anchor"]


def test_the_tax_rate_reaches_the_peer_beta_it_is_the_only_input_to(
        endpoint, body, monkeypatch):
    """The field whose first justification for being absent was wrong.

    Neither model discounts at WACC, so a tax rate touches nothing they compute
    — measured at 21% against 45% on both fixtures, not one output moves. That
    measurement was taken without peers, and it is the whole of why the field
    was left out of `IntrinsicAssumptions` at first.

    `resolve_beta` unlevers a peer beta as `Bu = Bl / (1 + (1 - Tc) x D/E)` and
    relevers it to the target, so the tax rate sets the beta whenever the peer
    ladder is reached — which is any issuer whose own reported beta falls
    outside the credibility band, a condition `resolve_beta`'s comment records
    hitting five energy names at once.
    """
    from backend import main

    peers = [{"beta": b, "market_cap": mc, "total_debt": td,
              "currency": "USD", "financial_currency": "USD"}
             for b, mc, td in ((1.2, 2.0e11, 5.0e10), (0.9, 1.5e11, 4.0e10),
                               (1.05, 1.0e11, 3.0e10))]
    incredible = load_fundamentals("JPM")
    incredible["info"]["beta"] = 9.9
    monkeypatch.setattr(main.provider, "get_fundamentals", lambda t: incredible)
    monkeypatch.setattr(main, "_peer_beta_inputs", lambda f: peers)
    monkeypatch.setattr(main, "_market_bars", lambda t: None)

    low = endpoint("JPM", body(tax_rate=0.21))
    high = endpoint("JPM", body(tax_rate=0.45))

    assert low["assumptions"]["beta_source"] == "peer_median_relevered"
    assert low["assumptions"]["beta"] == pytest.approx(1.7855, abs=1e-4)
    assert high["assumptions"]["beta"] == pytest.approx(1.5937, abs=1e-4)
    assert low["fair_value_per_share"] == pytest.approx(192.13, abs=0.01)
    assert high["fair_value_per_share"] == pytest.approx(215.41, abs=0.01)

    # The control: with a credible reported beta the peer ladder is never
    # reached, and then the field really does change nothing — which is the
    # measurement that made the first draft's claim look true.
    monkeypatch.setattr(main.provider, "get_fundamentals",
                        lambda t: load_fundamentals("JPM"))
    assert endpoint("JPM", body(tax_rate=0.21))["fair_value_per_share"] ==         endpoint("JPM", body(tax_rate=0.45))["fair_value_per_share"]


# ── requests that do not describe this company ───────────────────────

def test_a_bank_is_told_that_dividend_growth_is_not_one_of_its_inputs(endpoint, body):
    """Refused rather than dropped. A body whose field was silently ignored
    would let a caller watch the answer not change and conclude the input did
    not matter, when in fact it was never read."""
    with pytest.raises(HTTPException) as e:
        endpoint("JPM", body(growth_rate=0.05))

    assert e.value.status_code == 400
    assert "growth_rate is not an input" in e.value.detail
    assert "excess return" in e.value.detail
    assert "it takes roe" in e.value.detail


def test_a_reit_is_told_the_same_about_return_on_equity(endpoint, body):
    with pytest.raises(HTTPException) as e:
        endpoint("O", body(roe=0.15))

    assert e.value.status_code == 400
    assert "roe is not an input" in e.value.detail
    assert "it takes growth_rate" in e.value.detail


def test_a_company_whose_dcf_applies_is_sent_to_the_dcf(endpoint, body):
    with pytest.raises(HTTPException) as e:
        endpoint("AAPL", body())

    assert e.value.status_code == 400
    assert "No intrinsic model applies to a technology" in e.value.detail
    assert "POST to /dcf instead" in e.value.detail


def test_a_company_no_model_values_says_so_without_pointing_anywhere(endpoint, body):
    """RIVN has neither. The message must not send the caller to an endpoint
    that would refuse it too."""
    with pytest.raises(HTTPException) as e:
        endpoint("RIVN", body())

    assert e.value.status_code == 400
    assert "Neither this nor a discounted cash flow does" in e.value.detail
    assert "/dcf" not in e.value.detail


def test_the_endpoint_classifies_off_the_statements_not_the_vendor_field(
        endpoint, body, monkeypatch):
    """Which model a company uses has to be one answer, not two.

    `sector_weights.classify` takes the free cash flow as an argument precisely
    so its caller can supply the statement-verified figure — `info["freeCashflow"]`
    is annual for some issuers and quarterly for others, which is why
    `financial_models._classify` exists at all.

    No committed fixture flips between the two sources, so swapping them in this
    endpoint left all 774 tests passing when it was tried as a mutation. RIVN
    with a positive vendor figure does flip — statement-verified it stays
    `pre_profit_growth` and no model applies, while the vendor figure makes it
    `consumer`, whose DCF does apply and whose 400 would send the caller
    somewhere else entirely.
    """
    from backend import main

    doctored = load_fundamentals("RIVN")
    doctored["info"]["freeCashflow"] = 5.0e9
    monkeypatch.setattr(main.provider, "get_fundamentals", lambda t: doctored)

    with pytest.raises(HTTPException) as e:
        endpoint("RIVN", body())

    assert "pre profit growth" in e.value.detail
    assert "Neither this nor a discounted cash flow does" in e.value.detail
    assert "consumer" not in e.value.detail


# ── the refusals an override must not be able to talk a model out of ──

def test_a_cost_of_equity_under_terminal_growth_still_refuses(endpoint, body):
    """A Gordon terminal value divides by `Ke - g`. At or below zero the answer
    is not large, it is meaningless — and the user supplying the rate does not
    change that. Returned as the model's own refusal with a 200, because a
    refusal is a result the panel renders."""
    out = endpoint("JPM", body(cost_of_equity=0.02, terminal_growth=0.025))

    assert "must exceed terminal growth" in out["error"]
    assert "fair_value_per_share" not in out


def test_a_reit_cost_of_equity_below_its_cost_of_debt_still_refuses(endpoint, body):
    """The guard this whole model was shaped around, held against a user.

    A lender ranks ahead of a shareholder, so a share cannot require less
    return than the bond above it — an inequality between two computed figures,
    not an opinion the platform holds and a user may overrule. O's pre-tax cost
    of debt is 7.30%; 7.29% refuses and 7.31% does not, which is the pair that
    proves the boundary is the one being tested.
    """
    assert "below this company's pre-tax cost of debt" in \
        endpoint("O", body(cost_of_equity=0.0729))["error"]
    assert endpoint("O", body(cost_of_equity=0.0731))["fair_value_per_share"] > 0


def test_the_measured_growth_band_does_not_bind_a_supplied_rate(endpoint, body):
    """`GROWTH_VALIDITY_RANGE` rejects a *measured* dividend growth outside
    -50% to 200%, because a series compounding at 250% is a corrupt series. A
    rate the caller typed is not a measurement and is not held to it — the band
    guards data quality, not opinion.

    250% deliberately: the first draft of this test used 30%, which sits inside
    the band, so it would have passed whether the skip existed or not. A test of
    an escape has to stand outside what it claims to escape. Found in
    adversarial review 2026-08-29.
    """
    outside = 2.5
    assert not (fm.GROWTH_VALIDITY_RANGE[0] <= outside <= fm.GROWTH_VALIDITY_RANGE[1])

    out = endpoint("O", body(growth_rate=outside, cost_of_equity=0.40))
    assert out["assumptions"]["growth_rate_explicit"] == pytest.approx(outside)
    assert out["assumptions"]["growth_source"] == "user"
    assert out["fair_value_per_share"] > 0

    # And the band still binds the measured series, so the skip is a skip rather
    # than the guard having been deleted: doubling O's newest dividend sixty
    # times over is refused when nothing is supplied.
    corrupt = load_fundamentals("O")
    period = sorted(corrupt["cash_flow"])[-1]
    for row in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
        corrupt["cash_flow"][period][row] *= 60
    assert "not describing a growth rate" in fm.dividend_discount_valuation(corrupt)["error"]
