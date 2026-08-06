"""Scoring validation per docs/scoring-system-design.md §5.

Replaces the hand-run assert script. Everything here runs offline against
committed fixtures, so a regression in the anchor tables, the sector profiles or
the metric extraction fails a test instead of silently changing every score.

Regenerate the golden file after a *deliberate* methodology change:
    set UPDATE_GOLDEN=1 && backend\\.venv\\Scripts\\python.exe -m pytest backend/tests
Review the diff before committing it — that diff IS the record of what changed.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from conftest import FIXTURES, load_fundamentals

import financial_models as fm
import scoring

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_scores.json"
UPDATING = os.environ.get("UPDATE_GOLDEN") == "1"


def _summary(card: dict) -> dict:
    """The parts of a card that must not drift silently."""
    return {
        "classification": card["classification"],
        "composite_score": card["composite_score"],
        "tier": card["tier"],
        "confidence": card["confidence"],
        "coverage_pct": card["coverage_pct"],
        "flags": sorted(card["flags"]),
        "pillars": {
            name: {"score": p["score"], "insufficient": p["insufficient"],
                   "metrics": {m: v["score"] for m, v in p["metrics"].items()}}
            for name, p in card["pillars"].items()
        },
    }


def _load_golden() -> dict:
    if GOLDEN_PATH.exists():
        return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return {}


# ── 5.2 golden snapshots ─────────────────────────────────────────────

@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_golden_score_snapshot(stem):
    card = scoring.score_company(load_fundamentals(stem))
    actual = _summary(card)
    golden = _load_golden()

    if UPDATING:
        golden[stem] = actual
        GOLDEN_PATH.write_text(json.dumps(golden, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip(f"golden updated for {stem}")

    assert stem in golden, (
        f"No golden entry for {stem}. Run with UPDATE_GOLDEN=1 to create it."
    )
    assert actual == golden[stem]


# ── FCF source regression (the bug this suite was written for) ────────

@pytest.mark.parametrize("stem", ["MSFT", "AAPL", "XOM", "0700_HK"])
def test_fcf_metrics_use_the_cash_flow_statement(stem):
    """info["freeCashflow"] is a single quarter for some issuers (MSFT 0.244x,
    GOOGL 0.309x of the annual statement) and annual for others. Using it
    rescaled fcf_yield and made fcf_conversion a mixed-basis ratio.
    """
    f = load_fundamentals(stem)
    raw, flags = scoring.extract_metrics(f)
    statement = fm._statement_fcf(f["cash_flow"])
    assert statement is not None, "fixture must exercise the statement path"

    mcap = f["info"]["marketCap"]
    assert raw["fcf_yield"] == pytest.approx(statement[1] / mcap, rel=1e-9)
    assert "fcf_from_info_unverified_period" not in flags


def test_fcf_conversion_legs_share_one_period():
    """FCF over net income is only a conversion rate if both legs are annual."""
    f = load_fundamentals("MSFT")
    raw, _ = scoring.extract_metrics(f)
    period, fcf = fm._statement_fcf(f["cash_flow"])
    net_income = fm._value_at(f["income_statement"], period,
                              "Net Income", "Net Income Common Stockholders")
    assert net_income is not None
    assert raw["fcf_conversion"] == pytest.approx(fcf / net_income, rel=1e-9)
    # the old info-based value was ~0.244x of this; guard the magnitude
    assert raw["fcf_conversion"] > 3 * (f["info"]["freeCashflow"] / net_income)


def test_fcf_conversion_is_dropped_when_the_period_cannot_be_verified(empty_fundamentals):
    """FCF from info["freeCashflow"] has no verified period, so pairing it with
    annual net income would recreate the mixed-basis ratio this guards against."""
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"freeCashflow": 1e9, "marketCap": 1e10}
    f["income_statement"] = {"2025-12-31": {"Net Income": 5e8}}
    raw, flags = scoring.extract_metrics(f)
    assert raw["fcf_yield"] == pytest.approx(0.1)      # yield still computable
    assert raw["fcf_conversion"] is None               # conversion is not
    assert "fcf_from_info_unverified_period" in flags


def test_fcf_conversion_flags_a_period_mismatch(empty_fundamentals):
    """Statement FCF exists but that period has no net income — drop, don't mix."""
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"marketCap": 1e10}
    f["cash_flow"] = {"2025-12-31": {"Operating Cash Flow": 2e9,
                                     "Capital Expenditure": -1e9}}
    f["income_statement"] = {"2024-12-31": {"Net Income": 5e8}}  # different period
    raw, flags = scoring.extract_metrics(f)
    assert raw["fcf_conversion"] is None
    assert "fcf_conversion_period_mismatch" in flags


def test_fcf_falls_back_to_info_with_a_flag(empty_fundamentals):
    """When the statement lacks both legs, the info value is still used — but
    the card must say so rather than pretending the period is verified."""
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"freeCashflow": 1e9, "marketCap": 1e10}
    raw, flags = scoring.extract_metrics(f)
    assert raw["fcf_yield"] == pytest.approx(0.1)
    assert "fcf_from_info_unverified_period" in flags


# ── 5.1 determinism ──────────────────────────────────────────────────

@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_identical_input_gives_identical_score(stem):
    a = scoring.score_company(load_fundamentals(stem))
    b = scoring.score_company(load_fundamentals(stem))
    a.pop("as_of"), b.pop("as_of")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_scoring_does_not_mutate_provider_output(stem):
    """The TTL cache in data_provider shares one dict between requests, so
    scoring must treat its input as read-only."""
    f = load_fundamentals(stem)
    before = json.dumps(f, sort_keys=True)
    scoring.score_company(f)
    assert json.dumps(f, sort_keys=True) == before


# ── 5.4 degenerate inputs ────────────────────────────────────────────

def test_all_none_produces_no_score(empty_fundamentals):
    card = scoring.score_company(empty_fundamentals)
    assert card["composite_score"] is None
    assert card["coverage_pct"] == 0
    assert card["confidence"] == "LOW"


def test_negative_earnings_classifies_pre_profit(empty_fundamentals):
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"currentPrice": 10, "marketCap": 1e9, "trailingEps": -2.0,
                 "freeCashflow": -5e7, "sector": "Technology", "industry": "Software"}
    card = scoring.score_company(f)
    assert card["classification"] == "pre_profit_growth"
    assert card["confidence"] != "HIGH", "pre-profit confidence must be capped"


def test_absurd_values_are_winsorized(empty_fundamentals):
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"currentPrice": 10, "marketCap": 1e9, "trailingPE": 4000,
                 "forwardPE": 4000, "trailingEps": 0.0025, "sector": "Technology",
                 "industry": "Software", "enterpriseToEbitda": 99999}
    card = scoring.score_company(f)  # must not crash
    for pillar in card["pillars"].values():
        for metric in pillar["metrics"].values():
            assert 0 <= metric["score"] <= 100


def test_negative_equity_skips_debt_to_equity(empty_fundamentals):
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"currentPrice": 10, "marketCap": 1e9, "totalDebt": 5e8,
                 "sector": "Technology", "industry": "Software"}
    f["balance_sheet"] = {"2025-12-31": {"Stockholders Equity": -1e8, "Total Assets": 1e9}}
    _, flags = scoring.extract_metrics(f)
    assert "debt_equity_skipped_negative_equity" in flags


# ── 5.3 sector profile substitutions ─────────────────────────────────

def test_bank_profile_drops_invalid_metrics():
    card = scoring.score_company(load_fundamentals("JPM"))
    assert card["classification"] == "financials_bank"
    used = {m for p in card["pillars"].values() for m in p["metrics"]}
    for invalid in ("ev_ebitda", "current_ratio", "fcf_yield", "dcf_upside_pct"):
        assert invalid not in used, f"bank profile must drop {invalid}"


def test_reit_profile_uses_ffo_not_ev_ebitda():
    card = scoring.score_company(load_fundamentals("O"))
    assert card["classification"] == "real_estate_reit"
    used = {m for p in card["pillars"].values() for m in p["metrics"]}
    assert "ffo_yield" in used
    assert "ev_ebitda" not in used


def test_hk_listing_scores_without_usd_assumptions():
    card = scoring.score_company(load_fundamentals("0700_HK"))
    assert card["composite_score"] is not None
    assert card["coverage_pct"] > 0


# ── composite integrity ──────────────────────────────────────────────

@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_composite_excludes_insufficient_pillars(stem):
    """The composite must be reproducible from the pillars the UI shows as
    counted — this is the backend half of the ScorecardTab display bug."""
    card = scoring.score_company(load_fundamentals(stem))
    if card["composite_score"] is None:
        pytest.skip("no composite for this fixture")
    usable = {n: p for n, p in card["pillars"].items()
              if p["score"] is not None and not p["insufficient"]}
    total_w = sum(p["weight"] for p in usable.values())
    expected = round(sum(p["weight"] * p["score"] for p in usable.values()) / total_w)
    assert card["composite_score"] == expected


@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_tier_matches_composite(stem):
    card = scoring.score_company(load_fundamentals(stem))
    if card["composite_score"] is None:
        assert card["tier"] is None
        return
    expected = next(t for floor, t, _ in scoring.TIERS if card["composite_score"] >= floor)
    assert card["tier"] == expected
