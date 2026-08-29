"""The excess return model — the valuation a bank gets instead of a DCF.

Three of these tests exist because the number they pin was measured wrong first
and corrected during verification on 2026-08-29: the equity row, the terminal
growth cap, and the fact that a negative-equity issuer reaches the *first*
refusal rather than a second one. Each is noted in place.

Everything here is offline against the committed JPM fixture. The model is a
pure function of the fundamentals dict plus a cost of equity, and `_wacc`
degrades to its documented fallbacks without a network, so nothing in this file
reaches one.
"""
from __future__ import annotations

import copy

import pytest

from conftest import load_fundamentals

from backend import financial_models as fm


@pytest.fixture
def jpm():
    return load_fundamentals("JPM")


@pytest.fixture
def valued(jpm):
    out = fm.excess_returns_valuation(jpm)
    assert "error" not in out, out.get("error")
    return out


# ── which equity, and whose income ───────────────────────────────────

def test_book_value_is_common_equity_not_total_equity(jpm, valued):
    """The distinction is 20.0bn on this fixture, and it is the whole point.

    `Stockholders Equity` includes preferred stock; `Net Income Common
    Stockholders` does not accrue to it. Pairing the two charges the common
    shareholder for a claim that is not theirs. The first draft of this model
    used the total figure — caught in verification before it shipped, which is
    why the assertion is written against both numbers rather than one.
    """
    bal = jpm["balance_sheet"]["2025-12-31"]
    assert bal["Common Stock Equity"] == 342393000000.0
    assert bal["Stockholders Equity"] == 362438000000.0
    assert valued["book_value_of_equity"] == 342393000000.0
    assert valued["assumptions"]["book_value_basis"] == "common_stock_equity"


def test_roe_pairs_both_legs_from_one_period(jpm):
    """A period reporting only one leg is dropped, never paired across years.

    `statements.paired_latest` enforces this inside a statement and cannot help
    here: equity is on the balance sheet and income on the income statement.
    """
    f = copy.deepcopy(jpm)
    del f["income_statement"]["2024-12-31"]["Net Income Common Stockholders"]
    del f["income_statement"]["2024-12-31"]["Net Income"]

    periods = [h["period"] for h in fm.roe_history(f)]
    assert "2024-12-31" not in periods
    assert periods == ["2022-12-31", "2023-12-31", "2025-12-31"]


# ── normalisation ────────────────────────────────────────────────────

def test_roe_is_normalised_rather_than_taken_from_the_newest_year(valued):
    """Provisioning is procyclical, so one year is a reserve move as much as a
    run rate. This fixture's four years span 3.96 points."""
    a = valued["assumptions"]
    history = [h["roe"] for h in valued["diagnostics"]["roe_history"]]

    assert a["roe_periods"] == 4
    # `roe_history` is rounded to 6dp for display; compare at that precision
    # rather than asserting a payload is more exact than it says it is.
    assert a["roe"] == pytest.approx(sum(history) / len(history), abs=1e-6)
    assert a["roe_source"] == "normalised_mean"
    # And it genuinely differs from the newest year, or the normalisation would
    # be doing nothing on this fixture and the test would pass vacuously.
    assert a["roe"] != a["roe_latest"]
    assert max(history) - min(history) > 0.03


def test_the_newest_year_is_reported_beside_the_normalised_one(valued):
    """Show both, choose neither — the treatment `base_year_context` gives the
    DCF's base year."""
    d = valued["diagnostics"]
    assert d["fair_value_normalised_roe"] == valued["fair_value_per_share"]
    assert d["fair_value_latest_roe"] is not None
    assert d["fair_value_latest_roe"] != d["fair_value_normalised_roe"]


# ── the terminal cap, which is load-bearing rather than decorative ───

def test_retention_growth_alone_would_make_the_terminal_value_negative(valued):
    """The reason terminal growth is capped, stated as an assertion.

    A profitable bank retaining most of its earnings grows book value faster
    than its own cost of equity. On this fixture 11.09% against 8.66%, so an
    uncapped Gordon terminal value divides by a negative number. Measured
    2026-08-29; if this ever stops being true the cap stops being load-bearing
    and this test says so.
    """
    a = valued["assumptions"]
    assert a["growth_rate_explicit"] > a["cost_of_equity_used"]
    assert a["terminal_growth"] < a["cost_of_equity_used"]


def test_terminal_growth_is_the_same_cap_the_dcf_uses(valued):
    """Rewritten 2026-08-29 because the first version could not fail.

    It asserted `terminal_growth == min(fm.TERMINAL_GROWTH, risk_free_rate)`,
    which restates the source line — change one and the other changes with it —
    and then `terminal_growth_source in (both possible values)`, which cannot
    distinguish the branches. Deleting the `min` outright left all 737 tests
    green, found by mutation.

    Every fixture in the set reports a currency whose risk-free rate is above
    the 2.5% anchor, so the capped branch never runs on any of them. A CNY
    reporter does: `conftest` pins ChinaBond low enough that the rate wins, and
    that is the same currency-consistent discounting path the DCF already takes
    for 0700.HK — so this exercises production behaviour rather than a
    monkeypatched stand-in.
    """
    a = valued["assumptions"]
    assert a["terminal_growth"] == pytest.approx(fm.TERMINAL_GROWTH, abs=1e-9)
    assert a["terminal_growth_source"] == "platform_default"
    assert a["risk_free_rate"] > fm.TERMINAL_GROWTH, "or the cap is not the untested one"

    crossed = load_fundamentals("JPM")
    crossed["info"]["financialCurrency"] = "CNY"
    crossed["info"]["currency"] = "HKD"
    capped = fm.excess_returns_valuation(crossed)["assumptions"]

    assert capped["risk_free_rate"] == pytest.approx(0.011, abs=1e-6)
    assert capped["terminal_growth"] == pytest.approx(0.011, abs=1e-6)
    assert capped["terminal_growth_source"] == "capped_at_risk_free_rate"
    assert capped["terminal_growth"] < capped["terminal_growth_anchor"]


# ── the assumption, printed rather than buried ───────────────────────

def test_the_permanent_spread_and_its_consistency_condition_are_reported(valued):
    """ROE is held flat, so the model claims a spread over cost of equity that
    never erodes. That is a stance, and both halves of it are on the record: the
    spread itself, and the payout the terminal phase needs for that ROE and that
    growth to be mutually possible.
    """
    a, d = valued["assumptions"], valued["diagnostics"]
    assert d["excess_spread"] == pytest.approx(a["roe"] - a["cost_of_equity_used"],
                                               abs=1e-6)
    assert d["implied_terminal_payout"] == pytest.approx(
        1 - a["terminal_growth"] / a["roe"], abs=1e-6)
    # On this fixture the terminal phase needs a far higher payout than today's,
    # which is exactly the sort of quiet policy change a reader should see.
    assert d["implied_terminal_payout"] > d["current_payout"]


def test_dividends_are_read_across_the_row_names_issuers_actually_use(valued):
    """The JPM fixture reports `Cash Dividends Paid`; the O fixture reports
    `Common Stock Dividend Paid`. One name would have silently produced full
    retention and a much higher growth rate."""
    a = valued["assumptions"]
    assert a["payout_ratio"] == pytest.approx(0.305, abs=1e-3)
    assert a["payout_periods"] == 4
    assert a["growth_source"] == "roe_x_retention"


# ── arithmetic ───────────────────────────────────────────────────────

def test_zero_growth_collapses_to_the_residual_income_identity():
    """With no growth, equity is worth exactly `book x ROE / cost of equity`.

    The first version of this test asserted `equity = book + pv + terminal`,
    which is a literal source line and would have passed with the discounting
    off by a year in either direction. Adversarial review 2026-08-29 named it
    unfalsifiable and it was. This one is checkable by hand and pins the
    arithmetic instead: at g = 0 the excess is a flat perpetuity, so
    100 x 0.15/0.10 = 150 exactly, and any off-by-one in the exponent moves it.
    """
    pv, terminal_pv, path = fm._excess_return_project(
        book=100.0, roe=0.15, ke=0.10, g=0.0, g_term=0.0)

    assert 100.0 + pv + terminal_pv == pytest.approx(150.0, abs=1e-9)
    assert pv == pytest.approx(30.722835, abs=1e-6)
    assert terminal_pv == pytest.approx(19.277165, abs=1e-6)
    # Equity never grows, so every year earns the same excess on the same base.
    assert all(step["opening_equity"] == 100.0 for step in path)
    assert all(step["excess_return"] == pytest.approx(5.0) for step in path)


def test_a_spread_of_zero_is_worth_exactly_book(valued):
    """Growth creates no value once the excess is competed away — the same
    identity as ROC = WACC in the DCF, and the reason the flat-ROE assumption
    has to be shown rather than assumed."""
    pv, terminal_pv, _ = fm._excess_return_project(
        book=100.0, roe=0.09, ke=0.09, g=0.03, g_term=0.02)
    assert 100.0 + pv + terminal_pv == pytest.approx(100.0, abs=1e-9)


def test_the_excess_is_earned_on_opening_equity_not_closing(valued):
    """Compounding before charging the spread would credit each year with
    capital the company had not yet retained."""
    a = valued["assumptions"]
    path = valued["diagnostics"]["projection"]
    spread = a["roe"] - a["cost_of_equity_used"]

    assert path[0]["opening_equity"] == pytest.approx(valued["book_value_of_equity"])
    assert path[0]["excess_return"] == pytest.approx(
        spread * valued["book_value_of_equity"], rel=1e-6)
    # Year 2 opens on year 1's equity grown once, not twice.
    assert path[1]["opening_equity"] == pytest.approx(
        path[0]["opening_equity"] * (1 + path[0]["growth"]), rel=1e-6)


def test_projection_runs_the_same_horizon_as_the_dcf(valued):
    a = valued["assumptions"]
    assert len(valued["diagnostics"]["projection"]) == fm.PROJECTION_YEARS
    assert (a["stage1_years"], a["stage2_years"]) == (fm.STAGE1_YEARS, fm.STAGE2_YEARS)


# ── refusals ─────────────────────────────────────────────────────────

def test_negative_equity_is_refused_at_the_first_gate(jpm):
    """One refusal, not two.

    A separate `book <= 0` guard was written first and was unreachable: an
    issuer whose equity is negative in every period produces an empty history,
    because `roe_history` drops those periods on purpose — ROE is undefined on
    negative equity and a negative-equity issuer with a negative net income
    reports a spuriously positive one. Found by verification 2026-08-29 and
    merged into one message rather than left as decorative protection.
    """
    f = copy.deepcopy(jpm)
    for period in f["balance_sheet"]:
        f["balance_sheet"][period]["Common Stock Equity"] = -1e9

    out = fm.excess_returns_valuation(f)
    assert "negative-equity" in out["error"]
    assert set(out) == {"error"}


def test_missing_statements_are_refused(jpm):
    f = copy.deepcopy(jpm)
    f["balance_sheet"] = {}
    assert "not applicable" in fm.excess_returns_valuation(f)["error"]


def test_a_cost_of_equity_under_terminal_growth_is_refused(jpm):
    out = fm.excess_returns_valuation(jpm, cost_of_equity_override=0.02)
    assert out == {"error": "Cost of equity (2.00%) must exceed terminal growth (2.50%)."}


# ── the caller's overrides ───────────────────────────────────────────

def test_overrides_are_honoured_and_labelled(jpm):
    out = fm.excess_returns_valuation(jpm, roe=0.12, cost_of_equity_override=0.10,
                                      terminal_growth=0.02)
    a = out["assumptions"]
    assert (a["roe"], a["cost_of_equity_used"], a["terminal_growth"]) == (0.12, 0.10, 0.02)
    assert a["roe_source"] == a["cost_of_equity_source"] == "user"
    assert a["terminal_growth_source"] == "user"
    # The measured figures survive beside the overrides rather than being
    # overwritten by them.
    assert a["roe_normalised"] != 0.12


# ── the envelope a caller can rely on ────────────────────────────────

def test_the_success_envelope_matches_the_dcf_where_the_two_overlap(valued):
    """`comps.football_field` and the scorecard read these keys off whichever
    model ran, so the shared ones have to be spelled identically."""
    dcf = fm.dcf_valuation(load_fundamentals("AAPL"))
    assert "error" not in dcf
    shared = {"assumptions", "equity_value", "fair_value_per_share",
              "current_price", "upside_pct", "diagnostics", "sensitivity"}
    # Read off the live DCF rather than hardcoded, so a rename on either side
    # shows up here instead of drifting silently apart.
    assert shared <= set(dcf)
    assert shared <= set(valued)


def test_no_enterprise_value_is_reported(valued):
    """This model reaches equity directly. Reporting an enterprise value it
    never computed would invite a bridge comparison that does not exist —
    `comps.py` gates its equity-basis note on a DCF bar for exactly that
    reason."""
    assert "enterprise_value" not in valued
    assert "net_debt" not in valued


def test_sensitivity_sweeps_roe_against_cost_of_equity(valued):
    s = valued["sensitivity"]
    assert len(s["roe_cols"]) == len(fm.EXCESS_ROE_STEPS)
    assert len(s["rows"]) == len(fm.EXCESS_KE_STEPS)
    for row in s["rows"]:
        assert len(row["values"]) == len(fm.EXCESS_ROE_STEPS)
    # A higher cost of equity is worth less; a higher ROE is worth more.
    mid = len(fm.EXCESS_KE_STEPS) // 2
    assert s["rows"][0]["values"][mid] > s["rows"][-1]["values"][mid]
    assert s["rows"][mid]["values"][0] < s["rows"][mid]["values"][-1]


def test_roe_sensitivity_is_monotonic(valued):
    values = valued["roe_sensitivity"]["values"]
    assert values == sorted(values)


# ── the defects adversarial review found on 2026-08-29 ───────────────

def test_a_loss_year_cannot_poison_the_payout_denominator(jpm):
    """The severest defect in the first draft, pinned so it cannot return.

    Dividends over a *negative* net income is a negative payout, so `1 - payout`
    exceeds one and book value compounds at a rate the company never earned. As
    the loss approached zero the fair value diverged: -1bn gave 23,718 per share
    and -0.001bn gave 1.19e28, with no refusal and no flag. The payout is now
    averaged across profitable periods only.
    """
    for loss in (-30e9, -5e9, -1e9, -1e6):
        f = copy.deepcopy(jpm)
        f["income_statement"]["2025-12-31"]["Net Income Common Stockholders"] = loss
        f["income_statement"]["2025-12-31"]["Net Income"] = loss

        out = fm.excess_returns_valuation(f)
        assert "error" not in out, out["error"]
        a = out["assumptions"]
        # The loss year is excluded from the payout, not divided by.
        assert a["payout_periods"] == 3
        assert 0 < a["payout_ratio"] < 1
        # And the answer stays in the range a share price lives in.
        assert 0 < out["fair_value_per_share"] < 1000


def test_no_profitable_period_is_refused(jpm):
    """Both refusals mention the retention ratio, so this asserts the clause
    only *this* one carries. The first version matched either message and would
    have passed against the wrong refusal — the second unfalsifiable assertion
    found in this file, and by the same review."""
    f = copy.deepcopy(jpm)
    for period in f["income_statement"]:
        f["income_statement"][period]["Net Income Common Stockholders"] = -1e9
        f["income_statement"][period]["Net Income"] = -1e9

    out = fm.excess_returns_valuation(f)
    assert out["error"].startswith("No period reports a dividend against positive")
    assert "cannot be measured" in out["error"]


def test_a_payout_that_is_not_describing_a_payout_is_refused():
    """The retention band, fired by a real fixture rather than a contrived one.

    Realty Income distributes 2.76x its net income, because a REIT pays out of
    cash flow while GAAP depreciation crushes reported earnings. Retention comes
    out at -161%, which is not a retention ratio, so the model declines rather
    than compounding book value at a rate derived from it.

    This is a second, independent line of defence: even if the routing added in
    the next phase pointed a REIT at this model, the model itself refuses.
    """
    out = fm.excess_returns_valuation(load_fundamentals("O"))
    assert out["error"].startswith("Retention ratio of -161.2% is outside")
    assert set(out) == {"error"}


def test_price_to_book_is_withheld_when_the_two_are_in_different_currencies(jpm,
                                                                           monkeypatch):
    """`upside_pct` was gated on the FX basis and `price_to_book` was not, so a
    traded HKD price sat over an unconverted USD book value and was reported as
    a ratio."""
    monkeypatch.setattr(fm, "fx_rate", lambda *a, **k: None)
    f = copy.deepcopy(jpm)
    f["info"]["currency"] = "HKD"
    f["info"]["financialCurrency"] = "USD"

    out = fm.excess_returns_valuation(f)
    assert out["assumptions"]["fx_basis"] == "rate_unavailable"
    assert out["upside_pct"] is None
    assert out["diagnostics"]["price_to_book"] is None


def test_every_currency_output_is_converted_and_no_ratio_is(jpm):
    """The output-boundary rule, which this model did not follow until P5a.

    `dcf_valuation`'s own comment states it: `conv` is applied to every
    currency-denominated output and to none of the unit-free ratios. The DCF
    converts `equity_value`; the dividend model converts both its present
    values; this one converted `fair_value_per_share` and nothing else.

    The gap was internal too. Before the fix, on this same relabelled fixture,
    `book_value_per_share` times the share count came to 376.64bn against a
    `book_value_of_equity` of 342.39bn — off by exactly the 1.10 rate, so the
    two figures on one payload could not both be right.

    Every fixture but the Hong Kong pair reports and trades in one currency, so
    `conv` is 1.0 throughout the suite and the defect was a no-op on all of it.
    That is why this test relabels rather than reaching for a fixture.
    """
    crossed = copy.deepcopy(jpm)
    crossed["info"]["financialCurrency"] = "CNY"
    crossed["info"]["currency"] = "HKD"

    # Cost of equity and terminal growth pinned across both runs: relabelling
    # the reporting currency also re-points the risk-free rate at ChinaBond, and
    # without holding those the conversion and the discount rate move together.
    kw = dict(cost_of_equity_override=0.10, terminal_growth=0.025)
    plain = fm.excess_returns_valuation(jpm, **kw)
    converted = fm.excess_returns_valuation(crossed, **kw)

    assert plain["assumptions"]["fx_basis"] == "single_currency"
    assert converted["assumptions"]["fx_basis"] == "converted"
    assert converted["assumptions"]["fx_rate_used"] == pytest.approx(1.10)

    # `rel=1e-4` rather than tighter: every one of these is rounded to two
    # decimals before it is returned, and scaling a 2dp figure by 1.10 lands a
    # rounding step away from the 2dp figure computed from the scaled input.
    for key in ("book_value_of_equity", "excess_return_pv", "terminal_value_pv",
                "equity_value", "fair_value_per_share"):
        assert converted[key] == pytest.approx(plain[key] * 1.10, rel=1e-4), key

    for key in ("book_value_per_share", "tangible_book_value"):
        assert converted["diagnostics"][key] == pytest.approx(
            plain["diagnostics"][key] * 1.10, rel=1e-4), key

    # And nothing unit-free moves: a ratio of two reporting-currency figures is
    # already dimensionless, so converting it would break what conversion fixes.
    for key in ("excess_spread", "implied_terminal_payout", "current_payout",
                "terminal_value_share", "tangible_share_of_book"):
        assert converted["diagnostics"][key] == pytest.approx(
            plain["diagnostics"][key], rel=1e-9), key

    # The identity that was false before: per-share times shares is the total.
    shares = jpm["info"]["sharesOutstanding"]
    assert converted["diagnostics"]["book_value_per_share"] * shares == pytest.approx(
        converted["book_value_of_equity"], rel=1e-4)


def test_tangible_book_comes_from_the_same_period_as_book(jpm):
    """`statements.latest` walks backward per row; `book` does not. Dropping the
    row from the newest period silently paired a 2024 tangible figure with 2025
    equity."""
    f = copy.deepcopy(jpm)
    del f["balance_sheet"]["2025-12-31"]["Tangible Book Value"]

    d = fm.excess_returns_valuation(f)["diagnostics"]
    assert d["tangible_book_value"] is None
    assert d["tangible_share_of_book"] is None


def test_price_falls_back_the_way_the_dcf_does(jpm):
    f = copy.deepcopy(jpm)
    f["info"]["regularMarketPrice"] = f["info"].pop("currentPrice")

    out = fm.excess_returns_valuation(f)
    assert out["current_price"] == f["info"]["regularMarketPrice"]
    assert out["upside_pct"] is not None
