"""The scorecard consuming the models a DCF cannot build.

Until 2026-08-29 a bank's excess return valuation drew a bar on the football
field and the valuation pillar could not see it, so JPM trading 8% above its own
fair value did not touch its grade. This file is about closing that, and about
the two ways closing it could go wrong: scoring a valuation the chart refuses to
draw, and scoring one built on a different beta from the one the chart used.
"""
from __future__ import annotations

import pytest

from conftest import load_fundamentals, load_market_bars

from backend import financial_models as fm
from backend import scoring
from backend import sector_weights as sw


@pytest.fixture
def bank():
    return load_fundamentals("JPM")


@pytest.fixture
def scored(bank):
    return scoring.score_company(bank, market_bars=load_market_bars("JPM"))


# ── which profiles ask the question ───────────────────────────────────

@pytest.mark.parametrize("classification,scored_here", [
    ("financials_bank", True),
    ("financials_insurance", True),
    ("real_estate_reit", False),
    ("technology", False),
    ("default", False),
    ("pre_profit_growth", False),
])
def test_only_the_profiles_whose_model_can_be_observed_score_it(classification, scored_here):
    """REITs route to the dividend discount model and are still left out.

    Not an oversight and not a gap in the model: O is the only REIT fixture and
    that model refuses on it once real market bars are supplied, so scoring it
    there would ship a metric this repository has never observed produce a
    value. The bar still gets drawn — `VALUATION_MODELS` and the scoring profile
    are separate answers to separate questions, which is the distinction P2
    exists to keep.
    """
    metrics = sw.get_profile(classification)["metrics"]
    active = [m for lst in metrics.values() for m in lst]
    assert ("valuation_upside_pct" in active) is scored_here

    if classification == "real_estate_reit":
        assert sw.valuation_model_for(classification) == "dividend_discount"


def test_the_two_upside_metrics_share_one_curve_object():
    """Shared by reference, not copied. Two identical lists would drift the
    first time either is recalibrated, and the drift would be invisible: both
    would still be well-formed anchor tables."""
    assert scoring.METRIC_ANCHORS["valuation_upside_pct"] is scoring.UPSIDE_ANCHORS
    assert scoring.METRIC_ANCHORS["dcf_upside_pct"] is scoring.UPSIDE_ANCHORS


def test_no_profile_scores_both_upsides_at_once():
    """They answer the same question through different models, so a profile
    holding both would count one company's intrinsic valuation twice."""
    for classification in sw.SECTOR_PROFILES:
        active = [m for lst in sw.get_profile(classification)["metrics"].values()
                  for m in lst]
        assert not ("dcf_upside_pct" in active and "valuation_upside_pct" in active), \
            classification


# ── what it does to the bank ──────────────────────────────────────────

def test_a_bank_priced_above_its_fair_value_now_says_so(scored):
    """The whole point, in one assertion. JPM's excess return model puts it at
    330.52 against a price of 359.24 — 8% expensive — and before this the
    valuation pillar's three metrics could not express it."""
    v = scored["pillars"]["valuation"]

    assert v["metrics"]["valuation_upside_pct"]["raw"] == pytest.approx(-8.0, abs=0.1)
    assert v["metrics"]["valuation_upside_pct"]["score"] == 39
    assert v["score"] == 55
    assert scored["composite_score"] == 70
    # Still solidly inside the tier, which is what makes this a signal rather
    # than a re-grading: 70.3 against a floor of 65.
    assert scored["tier"] == "A"
    assert scored["coverage_pct"] == 100


def test_the_metric_is_the_justified_price_to_book_gap(bank):
    """Worth pinning because it is the one real objection to this metric sitting
    beside `p_b` in the same pillar: for a bank the two share a denominator.

        upside = (equity value / book) / (price / book) - 1

    so it is `justified P/B over actual P/B`, and `p_b` is the second term. The
    identity is exact rather than approximate, which is why the profile comment
    states the overlap rather than leaving it to be discovered.
    """
    v = fm.excess_returns_valuation(bank, market_bars=load_market_bars("JPM"))
    justified = v["equity_value"] / v["book_value_of_equity"]
    actual = v["diagnostics"]["price_to_book"]

    assert justified == pytest.approx(2.5660, abs=0.001)
    assert actual == pytest.approx(2.7890, abs=0.001)
    assert (justified / actual - 1) * 100 == pytest.approx(v["upside_pct"], abs=0.01)


# ── the two ways this could disagree with the chart ───────────────────

def test_a_supplied_valuation_is_used_rather_than_recomputed(bank):
    """`main._score_and_record` resolves the model with peers before scoring,
    exactly as it already does for the DCF, because `score_company` has no
    `peers` parameter to pass on. If the injected result were ignored the
    scorecard would quietly score a different beta from the chart's.

    Injected with a value no fixture produces, so a recomputation cannot
    coincidentally match it.
    """
    injected = scoring.score_company(bank, market_bars=load_market_bars("JPM"),
                                     valuation={"upside_pct": 40.0})
    v = injected["pillars"]["valuation"]

    assert v["metrics"]["valuation_upside_pct"]["raw"] == pytest.approx(40.0)
    assert v["metrics"]["valuation_upside_pct"]["score"] == 90
    assert v["score"] != 55, "the injected figure has to move the pillar"


def test_the_fallback_threads_the_bars_it_was_given(bank):
    """Without bars the reported beta of 0.977 gives -6.0% upside; with the bars
    the chart uses, a regression gives 1.0013 and -8.0%. Both are valid answers
    to different questions and only one is the chart's, so the fallback has to
    carry whatever it was handed rather than quietly running bare.
    """
    with_bars = scoring.score_company(bank, market_bars=load_market_bars("JPM"))
    without = scoring.score_company(bank)

    assert with_bars["pillars"]["valuation"]["metrics"][
        "valuation_upside_pct"]["raw"] == pytest.approx(-8.0, abs=0.1)
    assert without["pillars"]["valuation"]["metrics"][
        "valuation_upside_pct"]["raw"] == pytest.approx(-6.0, abs=0.1)


def test_a_refused_model_lowers_coverage_instead_of_the_score(bank):
    """A refusal is missing data, not a bad valuation. It leaves the pillar mean
    to the three metrics that did resolve and shows up as coverage — which is
    the behaviour that let REITs be left out of the profile rather than scored
    at zero forever."""
    refused = scoring.score_company(bank, market_bars=load_market_bars("JPM"),
                                    valuation={"error": "not applicable"})
    v = refused["pillars"]["valuation"]

    assert "valuation_upside_pct" not in v["metrics"]
    assert "valuation_upside_pct" in refused["missing_metrics"]
    assert v["score"] == 60, "the other three metrics score exactly as before"
    assert v["available_fraction"] == 0.75
    # 100 - 0.30 x 0.25 x 100 = 92.5, and 92 rather than 93 because `round`
    # takes halves to even. Pinned as measured rather than as calculated.
    assert refused["coverage_pct"] == 92
    assert refused["confidence"] == "HIGH"
    assert refused["composite_score"] == 72


def test_production_hands_the_scorer_the_same_valuation_the_chart_drew(monkeypatch, bank):
    """The one line that keeps the two tabs on one beta, pinned.

    `score_company` has no `peers` parameter, so its own fallback can only ever
    build a bare-beta valuation; production is correct solely because
    `_score_and_record` resolves the model with peers first and injects it. That
    line is invisible to every other test in this suite — deleting
    `valuation=valuation` from the call left all 760 passing, found by mutation
    2026-08-29 — because the endpoint needs a network to reach.

    So the network is removed and the call is inspected instead. This asserts
    wiring, not arithmetic: that what the scorer receives is what the chart's
    own resolution produced, peers and bars included.
    """
    from backend import main

    bars = load_market_bars("JPM")
    sentinel_peers = [{"beta": 1.1, "market_cap": 1e11, "total_debt": 1e10}]
    monkeypatch.setattr(main, "_fundamentals", lambda t, fresh_price=True: bank)
    monkeypatch.setattr(main, "_market_bars", lambda t: bars)
    monkeypatch.setattr(main, "_peer_beta_inputs", lambda f: sentinel_peers)
    monkeypatch.setattr(main.store, "record_score", lambda *a, **k: None)
    monkeypatch.setattr(main.forensics, "forensic_checks", lambda *a, **k: {})

    sentinel = {"upside_pct": 12.34, "resolved": "here, once"}
    resolved_with = {}

    def fake_intrinsic(f, classification=None, **kwargs):
        resolved_with.update(kwargs)
        return sentinel

    seen = {}

    def capture(f, dcf=None, market_bars=None, valuation=None):
        seen.update(dcf=dcf, market_bars=market_bars, valuation=valuation)
        return {"classification": "financials_bank", "flags": []}

    monkeypatch.setattr(main.financial_models, "intrinsic_valuation", fake_intrinsic)
    monkeypatch.setattr(main.scoring, "score_company", capture)
    main._score_and_record("JPM")

    # A sentinel rather than a recomputed valuation, so that a `score_company`
    # falling back to its own resolution cannot coincidentally match.
    assert seen["valuation"] is sentinel
    assert seen["market_bars"] is bars
    assert resolved_with["market_bars"] is bars
    assert resolved_with["peers"] is sentinel_peers

    # And the DCF beside it is resolved from the same two inputs, which is what
    # makes "the same beta" a property of the endpoint rather than a coincidence.
    assert seen["dcf"] is not None


# ── the dispatch ──────────────────────────────────────────────────────

@pytest.mark.parametrize("stem,model_fn", [
    ("JPM", fm.excess_returns_valuation),
    ("O", fm.dividend_discount_valuation),
    ("AAPL", None),
    ("RIVN", None),
])
def test_the_helper_routes_each_company_to_its_own_model(stem, model_fn):
    """The expected function is named here, never looked up in
    `INTRINSIC_MODELS`.

    The first version of this test asserted `fm.INTRINSIC_MODELS[expected](f)
    == out`, which reads the answer out of the same table the dispatcher reads.
    Swapping the two entries moves both sides together and the test goes on
    passing while JPM is valued by the REIT model — demonstrated in adversarial
    review 2026-08-29. Naming the function is what makes a wrong table entry
    visible.
    """
    f = load_fundamentals(stem)
    out = fm.intrinsic_valuation(f)

    if model_fn is None:
        assert out is None
        return
    assert out == model_fn(f)
    # And the other model gives a different answer, or the line above would
    # pass under a swapped table too.
    other = (fm.dividend_discount_valuation if model_fn is fm.excess_returns_valuation
             else fm.excess_returns_valuation)
    assert out != other(f)


def test_the_helper_trusts_the_classification_it_is_given(bank):
    """`score_company` has already classified by the time it asks, and passing
    that in is what stops the scorecard and the chart from being able to decide
    a company is two different things."""
    assert fm.intrinsic_valuation(bank, "technology") is None
    assert fm.intrinsic_valuation(bank, "financials_bank") == fm.excess_returns_valuation(bank)
