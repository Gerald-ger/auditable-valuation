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
import sector_weights

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
    # FCF comes off the statements and market cap off the market, so a
    # cross-currency issuer needs the numerator converted before the division —
    # 0700.HK reports CNY and trades HKD.
    fx, _ = fm.statement_to_market_fx(f["info"].get("currency"),
                                      f["info"].get("financialCurrency"))
    assert raw["fcf_yield"] == pytest.approx(statement[1] * fx / mcap, rel=1e-9)
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


# ── denominator-sign guards: a broken ratio must not score as cheap ──
#
# The ascending anchor tables read "lower = better" for these metrics, so a
# sign flip in the denominator clipped the ratio to the *best* anchor: a
# negative-EBITDA company scored 100 on EV/EBITDA, a negative-book company 100
# on P/B, a negative-equity company 100 on ROE. Measured on synthetic clones
# 2026-08-09: valuation pillar +10, composite +3, in exactly the wrong
# direction. The goldens cannot police this — no fixture carries a negative
# denominator — so these tests pin the guards directly.

def _minimal(info, balance=None):
    return {"ticker": "SYN", "info": info, "estimates": {},
            "income_statement": {}, "balance_sheet": balance or {}, "cash_flow": {}}


def test_negative_ev_ebitda_is_excluded_not_scored_cheap():
    m, _ = scoring.extract_metrics(_minimal({"enterpriseToEbitda": -8.0}))
    assert m["ev_ebitda"] is None


def test_ev_ebitda_dropped_when_reported_ebitda_is_negative():
    """yfinance can serve a stale positive ratio next to a negative EBITDA."""
    m, _ = scoring.extract_metrics(_minimal({"enterpriseToEbitda": 9.0,
                                             "ebitda": -5_000_000_000}))
    assert m["ev_ebitda"] is None


def test_positive_ev_ebitda_still_scores():
    m, _ = scoring.extract_metrics(_minimal({"enterpriseToEbitda": 9.0,
                                             "ebitda": 5_000_000_000}))
    assert m["ev_ebitda"] == 9.0


def test_negative_price_to_book_is_excluded():
    m, _ = scoring.extract_metrics(_minimal({"priceToBook": -2.1}))
    assert m["p_b"] is None


def test_roe_dropped_and_flagged_on_negative_equity():
    balance = {"2025-12-31": {"Stockholders Equity": -10_000_000_000.0}}
    m, flags = scoring.extract_metrics(_minimal({"returnOnEquity": 0.85}, balance))
    assert m["roe"] is None
    assert "roe_skipped_negative_equity" in flags


def test_roe_kept_on_positive_equity():
    balance = {"2025-12-31": {"Stockholders Equity": 10_000_000_000.0}}
    m, flags = scoring.extract_metrics(_minimal({"returnOnEquity": 0.25}, balance))
    assert m["roe"] == 0.25
    assert "roe_skipped_negative_equity" not in flags


# ── a suspended dividend is a zero, not a missing value ──────────────
#
# yfinance omits dividendYield for a non-payer instead of sending 0, and None
# means "unreported" to piecewise_score — so the metric left the pillar average
# rather than scoring its 20-point floor, which raised the average it left
# behind. Measured on JPM 2026-08-10 before the fix: valuation 58 paying 1.68%,
# 51 paying 0.10%, and 60 paying nothing at all. Both fixtures whose profile
# scores this metric are payers, so the goldens cannot police it.

def test_a_non_payer_scores_the_yield_floor_rather_than_being_skipped():
    m, _ = scoring.extract_metrics(_minimal({}))
    assert m["dividend_yield"] == 0.0
    assert scoring.piecewise_score(
        m["dividend_yield"], scoring.METRIC_ANCHORS["dividend_yield"]) == 20


def test_dividend_yield_keeps_the_percent_convention():
    """yfinance reports 1.68 for a 1.68% yield, not 0.0168."""
    m, _ = scoring.extract_metrics(_minimal({"dividendYield": 1.68}))
    assert m["dividend_yield"] == pytest.approx(0.0168)


@pytest.mark.parametrize("yield_pct,expected_order", [(1.68, 2), (0.10, 1), (None, 0)])
def test_cutting_the_dividend_never_improves_the_valuation_pillar(yield_pct, expected_order):
    """The inversion itself: the pillar must be monotonic in the yield.

    Parametrised so the failure names which rung broke; `expected_order` is only
    used to sort the results the test collects below.
    """
    f = load_fundamentals("JPM")
    f["info"]["dividendYield"] = yield_pct
    card = scoring.score_company(f)
    assert card["pillars"]["valuation"]["metrics"]["dividend_yield"]["score"] == (
        {2: 51, 1: 22, 0: 20}[expected_order])


def test_the_valuation_pillar_falls_monotonically_with_the_dividend():
    def pillar(yield_pct):
        f = load_fundamentals("JPM")
        f["info"]["dividendYield"] = yield_pct
        return scoring.score_company(f)["pillars"]["valuation"]["score"]

    paying, token, none = pillar(1.68), pillar(0.10), pillar(None)
    assert paying > token >= none, (
        f"a dividend cut must not improve valuation: {paying} -> {token} -> {none}")


def test_the_assumed_zero_is_flagged_only_where_the_metric_counts():
    """Every non-payer would otherwise carry this flag, including profiles that
    never score a dividend — RIVN's pre_profit_growth among them."""
    bank = load_fundamentals("JPM")
    bank["info"]["dividendYield"] = None
    assert "dividend_yield_assumed_zero" in scoring.score_company(bank)["flags"]

    tech = load_fundamentals("RIVN")   # pre_profit_growth: no dividend metric
    assert tech["info"].get("dividendYield") is None
    assert "dividend_yield_assumed_zero" not in scoring.score_company(tech)["flags"]


def test_a_reported_yield_raises_no_assumption_flag():
    assert "dividend_yield_assumed_zero" not in scoring.score_company(
        load_fundamentals("O"))["flags"]


# ── the DuPont ROE cap, and where it does not belong ─────────────────

def test_a_bank_is_not_penalised_for_being_a_bank():
    """JPM's equity multiplier is 12.2 because deposit-funded intermediation is
    what a bank is. Capping its ROE cost 8 points on the metric its Quality
    pillar leans hardest on and flagged it for financial engineering."""
    card = scoring.score_company(load_fundamentals("JPM"))
    ratios = fm.ratio_analysis(load_fundamentals("JPM"))

    assert ratios["dupont"]["equity_multiplier"] > 4      # the cap's trigger
    assert card["pillars"]["quality"]["metrics"]["roe"]["score"] > 70
    assert "dupont_leverage_cap_applied" not in card["flags"]


def test_the_cap_still_fires_where_leverage_is_a_choice():
    """AAPL's 148% ROE sits on an equity base buybacks have nearly erased. That
    is exactly what the guard is for, and it must keep working."""
    card = scoring.score_company(load_fundamentals("AAPL"))
    assert card["pillars"]["quality"]["metrics"]["roe"]["score"] == 70
    assert "dupont_leverage_cap_applied" in card["flags"]


def test_a_reit_is_still_capped():
    """Structurally levered, but a REIT lifting ROE with debt is a real concern
    rather than a regulatory floor — so it is deliberately not exempt."""
    assert "real_estate_reit" not in sector_weights.LEVERAGE_IS_STRUCTURAL


# ── DCF applicability travels with the card ──────────────────────────

@pytest.mark.parametrize("stem,applicable", [
    ("AAPL", True), ("MSFT", True), ("XOM", True), ("0700_HK", True),
    ("JPM", False),    # no CFO - CapEx to speak of
    ("O", False),      # capex is property acquisition, not maintenance
    ("RIVN", False),   # pre-profit: no positive FCF to discount
])
def test_dcf_applicability_matches_the_profile(stem, applicable):
    """The Financial Models tab reads this to avoid showing O a -63% upside with
    the same weight as a valid one. It must follow the profile, not whether the
    model happened to return a number."""
    card = scoring.score_company(load_fundamentals(stem))
    assert card["dcf_applicable"] is applicable
    # the flag must track the profile's metric list, which is what scored plus
    # what the profile wanted and could not compute
    active = {m for p in card["pillars"].values() for m in p["metrics"]}
    active |= set(card["missing_metrics"])
    assert ("dcf_upside_pct" in active) is applicable
