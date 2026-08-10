"""The §5.2 acceptance criteria, as assertions instead of prose.

docs/scoring-system-design.md §5.2 states what a *correct* engine must produce —
"RIVN ... Tier 3-5", "no bankrupt-adjacent name outranks a mega-cap compounder" —
and nothing ever checked it. `test_golden_score_snapshot` cannot: a golden
records what the engine *does*, so the first run of a wrong-but-stable value
canonises it. That is exactly what happened here, and the golden now carries
RIVN at 74/A as the expected answer.

The distinction this file exists for: **golden tests catch unintended change;
plausibility tests catch a wrong answer that never changes.** A composite that
has been 74 since the day it was written passes every snapshot assertion in the
suite and still violates the spec.

Known-failing cases are `xfail(strict=True)` rather than plain failures. A red
CI that is red on purpose gets ignored within a week; a strict xfail reports the
violation in every run's summary *and* turns into an error the moment a
calibration change fixes it, which is the signal we actually want when the
remedy lands. Do not relax one to a bare xfail to quieten it — delete the marker
when the behaviour is fixed.
"""
from __future__ import annotations

import pytest

from conftest import load_fundamentals

import scoring

# S/A/B/C/D are tiers 1-5 in §5.2's numbering, which is what the doc's
# "Tier 3-5" and "Tier 1-2" expectations are written against.
TIER_NUMBER = {letter: i + 1 for i, (_, letter, _) in enumerate(scoring.TIERS)}

# §5.2 exercises ten tickers; these are the five the fixture set covers.
MEGA_CAP_COMPOUNDERS = ("AAPL", "MSFT")


def composite(stem: str) -> int:
    return scoring.score_company(load_fundamentals(stem))["composite_score"]


def tier_number(stem: str) -> int:
    return TIER_NUMBER[scoring.score_company(load_fundamentals(stem))["tier"]]


# ── the criteria the engine currently meets ──────────────────────────

@pytest.mark.parametrize("stem", ["MSFT", "AAPL", "JPM"])
def test_quality_names_land_in_the_top_two_tiers(stem):
    """§5.2: MSFT and JPM "Tier 1-2", AAPL "Tier 2-ish"."""
    assert tier_number(stem) <= 2


def test_msft_quality_and_health_lead_the_set():
    """§5.2: MSFT "Q and H near top of set"."""
    cards = {stem: scoring.score_company(load_fundamentals(stem))
             for stem in ("MSFT", "AAPL", "JPM", "XOM", "O", "RIVN", "0700_HK")}
    for pillar in ("quality", "health"):
        scores = {s: c["pillars"][pillar]["score"] for s, c in cards.items()
                  if c["pillars"][pillar]["score"] is not None}
        best = max(scores.values())
        assert scores["MSFT"] >= best - 10, (
            f"MSFT {pillar} {scores['MSFT']} is not near the top of {scores}")


def test_xom_is_not_top_tier_on_trailing_cheapness():
    """§5.2: XOM "sanity: not Tier 1 purely off trailing cheapness"."""
    assert tier_number("XOM") > 1


def test_pre_profit_confidence_is_capped():
    """§5.2: RIVN "confidence <= MEDIUM"."""
    card = scoring.score_company(load_fundamentals("RIVN"))
    assert card["confidence"] in ("MEDIUM", "LOW")


def test_pre_profit_valuation_rests_on_ev_sales_and_health_on_runway():
    """§5.2: RIVN "EV/Sales-only V, runway in H"."""
    card = scoring.score_company(load_fundamentals("RIVN"))
    assert "ev_sales" in card["pillars"]["valuation"]["metrics"]
    assert "earnings_yield_fwd" not in card["pillars"]["valuation"]["metrics"]
    assert "cash_runway_q" in card["pillars"]["health"]["metrics"]


# ── the criteria it does not ─────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="A2: RIVN scores 74/A = tier 2. The pre_profit_growth profile weights "
           "the pillar it fails at 15% (quality 10 — operating margin -50.4%) and "
           "the one it aces at 35% (growth 98), and cash_runway_q reads 27.3 "
           "quarters because it divides cash by operating burn and ignores capex. "
           "Calibration remedy is a pending decision; this pins the violation.")
def test_pre_profit_growth_lands_in_the_bottom_three_tiers():
    """§5.2: RIVN "Tier 3-5"."""
    assert tier_number("RIVN") >= 3


@pytest.mark.xfail(
    strict=True,
    reason="A2: RIVN 74 outranks AAPL 67 and MSFT 73. Same root cause as above.")
@pytest.mark.parametrize("compounder", MEGA_CAP_COMPOUNDERS)
def test_a_cash_burning_name_does_not_outrank_a_mega_cap_compounder(compounder):
    """§5.2 acceptance (a).

    Parametrised over the compounders rather than asserting against the maximum,
    so the failure message names which comparison broke.
    """
    assert composite("RIVN") < composite(compounder)
