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

Known-failing cases go in as `xfail(strict=True)` rather than plain failures. A
red CI that is red on purpose gets ignored within a week; a strict xfail reports
the violation in every run's summary *and* turns into an error the moment a
change fixes it, which is the signal actually wanted when a remedy lands. Do not
relax one to a bare xfail to quieten it — delete the marker once the behaviour
is fixed. That mechanism has already fired once: the two §5.2 tests below shipped
xfailed on 2026-08-10 and were unmarked the same day when the calibration landed.
"""
from __future__ import annotations

import pytest

from conftest import load_fundamentals

from backend import scoring

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


# ── the criteria it did not meet until 2026-08-10 ────────────────────
#
# Both of these were `xfail(strict=True)` when this file was written: RIVN
# scored 74/Tier A, two tiers above the spec and ahead of AAPL's 67. Two causes,
# fixed together — `cash_runway_q` divided cash by operating burn and ignored
# capex (27.3 quarters against 8.5 on a free-cash-flow basis), and the profile
# weighted quality 15% against growth 35%. Now 60/Tier B.
#
# The markers came off when the behaviour changed, which is what strict xfail is
# for: the moment the fix landed these reported XPASS and failed the run until
# the markers were removed.

def test_pre_profit_growth_lands_in_the_bottom_three_tiers():
    """§5.2: RIVN "Tier 3-5"."""
    assert tier_number("RIVN") >= 3


@pytest.mark.parametrize("compounder", MEGA_CAP_COMPOUNDERS)
def test_a_cash_burning_name_does_not_outrank_a_mega_cap_compounder(compounder):
    """§5.2 acceptance (a).

    Parametrised over the compounders rather than asserting against the maximum,
    so the failure message names which comparison broke.
    """
    assert composite("RIVN") < composite(compounder)
