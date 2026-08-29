"""The dividend discount model, and the two things it refuses to do.

A REIT distributes by statute rather than by choice, so its dividend is the
cash flow rather than a residual left after one. That makes discounting it the
direct valuation — and makes two failure modes specific enough to be worth
their own file.

The first is arithmetic: REITs fund acquisitions by issuing equity, so the
aggregate dividend grows far faster than the dividend per share, and a model
that valued the aggregate would credit today's holder with dividends bought by
someone else's money. The second is the discount rate: this model applies the
cost of equity to every cash flow with no debt weighting to damp it, so an
error there is undamped in a way the DCF's is not.

Written against the O fixture throughout, because it is the only REIT in the
set and because both failure modes are live in it rather than hypothetical.
"""
from __future__ import annotations

import copy

import pytest

from conftest import load_fundamentals, load_market_bars

from backend import financial_models as fm
from backend import statements


@pytest.fixture
def reit():
    return load_fundamentals("O")


@pytest.fixture
def valued(reit):
    """The base case. No `market_bars`, which is not an omission — see
    `test_the_same_company_is_refused_once_its_beta_is_regressed`."""
    return fm.dividend_discount_valuation(reit)


# ── the arithmetic, against closed forms the source does not restate ──

def test_a_flat_dividend_discounts_to_the_zero_growth_perpetuity(reit):
    """`D / k`, exactly, to the cent.

    The identity is worth stating as a test rather than trusting, because it is
    the one claim the whole model rests on and nothing else here can check it:
    every other assertion in this file compares the model against itself. Hold
    both growth rates at zero and ten discounted years plus a discounted
    perpetuity must collapse to `D / k` — the ten explicit years contribute
    `D/k x (1 - (1+k)^-10)` and the terminal contributes exactly the remaining
    `D/k x (1+k)^-10`.

    Deliberately not `assert value == pv + terminal_pv`, which is what the first
    draft of the excess return model's identity test asserted and which is a
    restatement of a source line rather than a proof of anything. This number
    comes from the closed form, not from the implementation.
    """
    out = fm.dividend_discount_valuation(
        reit, growth_rate=0.0, terminal_growth=0.0, cost_of_equity_override=0.10)
    dps = out["assumptions"]["dividend_per_share"]

    assert out["fair_value_per_share"] == pytest.approx(dps / 0.10, abs=0.01)
    assert out["fair_value_per_share"] == pytest.approx(31.27, abs=0.01)


def test_a_constant_growth_dividend_discounts_to_gordon(reit):
    """`D0 (1 + g) / (k - g)`, the textbook form, when both stages grow alike.

    The two-stage fade is only visible when the stages differ; hold them equal
    and the fade has nothing to interpolate between, so the model has to
    reproduce the single-stage answer. That it does is what makes the fade a
    refinement of Gordon rather than a departure from it.
    """
    out = fm.dividend_discount_valuation(
        reit, growth_rate=0.03, terminal_growth=0.03, cost_of_equity_override=0.10)
    dps = out["assumptions"]["dividend_per_share"]

    assert out["fair_value_per_share"] == pytest.approx(
        dps * 1.03 / (0.10 - 0.03), abs=0.01)
    assert out["fair_value_per_share"] == pytest.approx(46.02, abs=0.01)


# ── per share, never in aggregate ─────────────────────────────────────

def test_the_growth_rate_is_per_share_and_the_difference_is_enormous(reit, valued):
    """O's share count ran 660.3m -> 934.0m, +41.4%, across the four reported
    years. Aggregate dividends paid therefore compound at 17.22% while the
    dividend *per share* compounds at 4.43% — and the 12.79-point gap is not
    growth, it is the new shareholders who brought the capital.

    Both rates are computed here from the fixture rather than quoted, so the
    test fails if either the data or the choice between them changes. At 17.22%
    against a cost of equity of 7.51% the Gordon terminal value would not merely
    be too big, it would be *negative*.
    """
    cash_flow = reit["cash_flow"]
    paid = [abs(statements.value_at(cash_flow, p, *fm.COMMON_DIVIDEND_ROWS))
            for p in sorted(cash_flow)
            if statements.value_at(cash_flow, p, *fm.COMMON_DIVIDEND_ROWS)]
    aggregate_cagr = (paid[-1] / paid[0]) ** (1 / (len(paid) - 1)) - 1

    per_share = valued["assumptions"]["growth_rate_explicit"]
    assert aggregate_cagr == pytest.approx(0.1722, abs=0.0001)
    assert per_share == pytest.approx(0.0443, abs=0.0001)
    assert aggregate_cagr - per_share > 0.12

    ke = valued["assumptions"]["cost_of_equity_used"]
    assert aggregate_cagr > ke, "otherwise this test proves nothing about why"


def test_the_grid_marks_every_rate_the_headline_would_refuse(reit):
    """One screen must not make two opposite claims about one number.

    The grid sweeps +/-1pp around a cost of equity that clears this company's
    pre-tax cost of debt by 21bp, so two of its five rows land under it. Until
    2026-08-29 those rows were drawn as valuations and unioned into the football
    field bar — while a reader typing the same 6.51% into the panel was refused,
    with a sentence about lenders ranking ahead of shareholders. Found in the
    overall verification of P1-P5.

    The mark is asserted against the headline's *actual* behaviour at each rate
    rather than against a recomputed comparison, so the two can never drift
    apart: if the refusal moves and the mark does not, this fails.
    """
    out = fm.dividend_discount_valuation(reit)
    rows = out["sensitivity"]["rows"]

    assert any(row["below_cost_of_debt"] for row in rows), \
        "the sweep has to cross the inversion on O or this test proves nothing"
    assert any(not row["below_cost_of_debt"] for row in rows)

    for row in rows:
        typed = fm.dividend_discount_valuation(
            reit, cost_of_equity_override=row["cost_of_equity"])
        refused_when_typed = "pre-tax cost of debt" in typed.get("error", "")
        assert row["below_cost_of_debt"] == refused_when_typed, (
            f"the grid and the headline disagree at "
            f"{row['cost_of_equity']:.2%}")
        # Marked, not deleted: the row still says which way the answer moves.
        assert all(v is not None for v in row["values"])


def test_the_refused_rows_are_reachable_on_the_path_a_reit_reader_takes(reit):
    """Where the grid contradiction was actually live.

    The test above measures without market bars, and production never does that:
    with them O's beta regresses to 0.4263 and the model refuses outright — no
    grid, no band, nothing to mark. Presenting the band movement as a published
    bar that moved was wrong about the only REIT fixture in the set, corrected in
    the changelog 2026-08-30.

    The reachable case is the one P5b built for exactly this company. A reader
    who supplies a cost of equity gets a valuation, and the grid still sweeps
    +/-1pp around *their* rate — so it can still cross the floor underneath them.
    That is the screen the refusal banner sends them to, which makes it the one
    place the mark has to work.
    """
    bars = load_market_bars("O")
    assert "pre-tax cost of debt" in fm.dividend_discount_valuation(
        reit, market_bars=bars)["error"], "production refuses, or this proves nothing"

    for supplied, fair_value, refused_rows in ((0.075, 69.65, 2), (0.08, 63.26, 1)):
        out = fm.dividend_discount_valuation(
            reit, cost_of_equity_override=supplied, market_bars=bars)
        assert out["fair_value_per_share"] == pytest.approx(fair_value)
        rows = out["sensitivity"]["rows"]
        assert sum(r["below_cost_of_debt"] for r in rows) == refused_rows
        assert len(rows) == 5


def test_a_period_whose_dividend_is_not_an_outflow_is_dropped(reit):
    """The filter that makes the `dps <= 0` guard below it dead.

    `dividend_per_share_history` admits a period only when the dividend is
    strictly negative — a cash outflow — and the share count strictly positive.
    The comment above that guard argues from exactly this, and until now the
    argument had no test under it: deleting `shares <= 0 or dividends >= 0` left
    all 776 green, because no committed fixture has a period that trips either
    half. Found by mutation in the overall verification 2026-08-29.

    A positive figure on the dividend row is a *received* dividend, and `abs()`
    two lines down would silently record it as one paid.
    """
    period = sorted(reit["cash_flow"])[-1]
    baseline = len(fm.dividend_per_share_history(reit))

    flipped = copy.deepcopy(reit)
    for row in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
        if row in flipped["cash_flow"][period]:
            flipped["cash_flow"][period][row] = abs(
                flipped["cash_flow"][period][row])
    assert len(fm.dividend_per_share_history(flipped)) == baseline - 1

    negative_shares = copy.deepcopy(reit)
    negative_shares["balance_sheet"][period]["Ordinary Shares Number"] *= -1
    assert len(fm.dividend_per_share_history(negative_shares)) == baseline - 1


def test_the_dividend_row_is_the_common_one_not_the_total(reit, valued):
    """`Cash Dividends Paid` includes preferred distributions; this model
    divides by the *common* share count, so the preferred dividend is a claim
    ranking ahead of the shares being valued.

    O's two rows agree in three of four years and differ in FY2024 by exactly
    `Preferred Stock Dividend Paid`. That single year is the whole test: the
    first draft reused `DIVIDEND_PAID_ROWS`, whose order is total-first because
    the excess return model wants the total, and inherited a 0.29% overstatement
    in that year's dividend per share.
    """
    period = "2024-12-31"
    # Named literally, never through `fm.COMMON_DIVIDEND_ROWS`. The first draft
    # of this test read the expected value out of the very tuple it was
    # checking, so reversing that tuple changed the model and the expectation
    # together and the test went on passing — which is exactly what happened
    # when a mutation run left the constant reversed on 2026-08-29 and 731 tests
    # stayed green. Found by the mutation battery's applied-assertion, not by
    # the suite.
    def row(name):
        return abs(statements.value_at(reit["cash_flow"], period, name))

    total, common, preferred = (row("Cash Dividends Paid"),
                                row("Common Stock Dividend Paid"),
                                row("Preferred Stock Dividend Paid"))
    assert total - common == pytest.approx(preferred, abs=1.0)
    assert preferred > 0, "no preferred dividend in this year means no test"

    shares = statements.value_at(reit["balance_sheet"], period, "Ordinary Shares Number")
    measured = next(h for h in valued["diagnostics"]["dividend_per_share_history"]
                    if h["period"] == period)["dividend_per_share"]
    assert measured == pytest.approx(common / shares, abs=1e-6)
    assert measured != pytest.approx(total / shares, abs=1e-6)
    # 3.019277 against 3.028005 — the two have to be far enough apart that the
    # inequality above is a real discrimination and not a rounding artefact.
    assert abs(common / shares - total / shares) > 0.008


def test_the_share_count_is_the_period_s_own_not_todays(reit, valued):
    """`info["sharesOutstanding"]` is one point-in-time figure — 932,492,530
    against the FY2025 statement's 933,975,000 — and dividing four years of
    dividends by one year's count would report dividend growth that is mostly
    the change in the denominator."""
    history = valued["diagnostics"]["dividend_per_share_history"]
    counts = [h["shares"] for h in history]

    assert len(set(counts)) == len(counts), "a constant count means one was reused"
    assert counts != [reit["info"]["sharesOutstanding"]] * len(counts)
    for h in history:
        assert h["shares"] == statements.value_at(
            reit["balance_sheet"], h["period"], *fm.SHARES_OUTSTANDING_ROWS)


# ── the refusals ──────────────────────────────────────────────────────

def test_the_same_company_is_refused_once_its_beta_is_regressed(reit):
    """The decision this model exists to make, on the one fixture that forces it.

    With `market_bars` supplied — which is what the comps endpoint does — O's
    beta is regressed to 0.4263 (R^2 0.148) and the cost of equity lands at
    6.20% against a 7.30% pre-tax cost of debt. A lender ranks ahead of a
    shareholder, so that is not a rate this company could raise equity at, and
    the fair value built on it is 94.35 against a price of 62.70.

    `dcf_valuation` reports the same inequality as `cost_of_equity_below_debt`
    and deliberately never corrects it, because a WACC blends the inverted cost
    of equity with the debt cost that overtook it and damps the error. This
    model discounts everything at the cost of equity alone, so it refuses.
    """
    refused = fm.dividend_discount_valuation(reit, market_bars=load_market_bars("O"))
    assert "below this company's pre-tax cost of debt" in refused["error"]
    assert "fair_value_per_share" not in refused

    # The control. Without bars the reported beta of 0.72 is used, the cost of
    # equity clears the inversion, and the same company is valued — so the
    # refusal above is about the rate and not about the company.
    priced = fm.dividend_discount_valuation(reit)
    assert priced["diagnostics"]["cost_of_equity_below_debt"] is False
    assert priced["fair_value_per_share"] > 0


def test_the_headroom_that_clears_the_inversion_is_thin_and_reported(valued):
    """21 basis points. The base case is not comfortably clear of the refusal
    above, it is barely clear of it, and a reader who cannot see that would
    read this valuation as sturdier than it is.

    Pinned rather than merely asserted positive, so that any future change to
    beta, the credit spread or the risk-free rate that quietly consumes the
    margin fails here instead of silently flipping the model to a refusal.
    """
    d = valued["diagnostics"]
    assert d["cost_of_equity_headroom"] == pytest.approx(0.0021, abs=0.0001)
    assert d["cost_of_debt_pre_tax"] == pytest.approx(0.0730, abs=0.0001)
    assert 0 < d["cost_of_equity_headroom"] < 0.005


def test_a_company_that_pays_no_dividend_is_refused():
    """Not a defect and not a gap: a model that discounts dividends has nothing
    to discount. RIVN reports no dividend row in any period."""
    out = fm.dividend_discount_valuation(load_fundamentals("RIVN"))
    assert "Fewer than two periods report a dividend" in out["error"]
    assert len(out) == 1


def test_a_cost_of_equity_under_terminal_growth_is_refused(reit):
    out = fm.dividend_discount_valuation(
        reit, terminal_growth=0.09, cost_of_equity_override=0.08)
    assert "must exceed terminal growth" in out["error"]


def test_a_growth_rate_outside_the_validity_band_is_refused(reit):
    """Rejected, never truncated — the rule `GROWTH_VALIDITY_RANGE` exists to
    state. A dividend series compounding at 250% is a corrupt series, and
    clamping it to the ceiling would substitute a number no statement reported
    and no reader could trace.

    Driven through the fixture rather than the override, because the override is
    the caller's own figure and is deliberately trusted; the band guards what the
    model *measures*. Doubling the newest dividend three times over is the
    shape a mis-scaled vendor row would take.
    """
    corrupt = load_fundamentals("O")
    period = sorted(corrupt["cash_flow"])[-1]
    for row in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
        corrupt["cash_flow"][period][row] *= 60

    out = fm.dividend_discount_valuation(corrupt)
    assert "outside -50% to 200%" in out["error"]
    assert "not describing a growth rate" in out["error"]

    # The control: at 20x the same row stays inside the band and is valued, so
    # the guard is a band and not a blanket refusal on any edited fixture.
    milder = load_fundamentals("O")
    for row in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
        milder["cash_flow"][period][row] *= 3
    assert fm.dividend_discount_valuation(milder)["fair_value_per_share"] > 0


# ── the diagnostics that make the answer arguable ─────────────────────

def test_the_implied_cost_of_equity_reproduces_the_price(reit, valued):
    """The one number that turns "+10.9% upside" into a claim a reader can
    disagree with: at 8.05% the model returns the market price exactly. So the
    valuation is not really a statement about O, it is a statement that the
    market's discount rate is 54 basis points above this platform's CAPM one.

    Verified by feeding it back in rather than by trusting the bisection — the
    round trip is the proof.
    """
    implied = valued["diagnostics"]["implied_cost_of_equity"]
    assert implied == pytest.approx(0.0805, abs=0.0005)

    round_trip = fm.dividend_discount_valuation(reit, cost_of_equity_override=implied)
    assert round_trip["fair_value_per_share"] == pytest.approx(
        valued["current_price"], abs=0.01)
    assert implied > valued["assumptions"]["cost_of_equity_used"]


def test_an_unreachable_implied_rate_is_reported_as_none_not_as_the_bracket_edge(reit):
    """The bisection brackets both ends or it does not bracket at all.

    Fair value falls in the cost of equity, so a root exists only where the
    cheap end overshoots the price and the dear end undershoots it. Checking
    only the near end returned `hi` itself whenever no rate could reach the
    price — found 2026-08-29 by forcing the price to 1.00, under which even a
    100% cost of equity values O at 3.40 and the bisection confidently reported
    an implied cost of equity of exactly 1.0000.

    A number at the edge of a search band is the search failing, not answering.
    """
    unreachable = load_fundamentals("O")
    unreachable["info"]["currentPrice"] = 1.00
    unreachable["info"]["regularMarketPrice"] = 1.00
    out = fm.dividend_discount_valuation(unreachable)

    assert out["diagnostics"]["implied_cost_of_equity"] is None
    # The rest of the valuation is unharmed — only the diagnostic withdraws.
    assert out["fair_value_per_share"] == pytest.approx(69.51, abs=0.01)


def test_a_year_that_pays_nothing_shortens_the_history_rather_than_zeroing_it(reit):
    """Why there is no `dps <= 0` guard in the model: there cannot be one to
    fire. `dividend_per_share_history` admits a period only on a strictly
    negative dividend and a strictly positive share count, so a year that pays
    nothing drops out and the series gets shorter — which is what the
    two-period refusal measures.

    Asserted rather than assumed, because a guard that cannot fire reads exactly
    like a guard that works.
    """
    assert all(h["dividend_per_share"] > 0
               for h in fm.dividend_per_share_history(reit))

    silent = load_fundamentals("O")
    period = sorted(silent["cash_flow"])[-1]
    for row in ("Common Stock Dividend Paid", "Cash Dividends Paid"):
        silent["cash_flow"][period][row] = 0.0

    shortened = fm.dividend_per_share_history(silent)
    assert len(shortened) == len(fm.dividend_per_share_history(reit)) - 1
    assert period not in [h["period"] for h in shortened]
    assert all(h["dividend_per_share"] > 0 for h in shortened)


def test_the_dividend_is_measured_against_a_proxy_that_says_it_is_a_proxy(valued):
    """A dividend discount model takes the dividend as given and compounds it,
    so whether the dividend is *covered* cannot come from inside the model.

    Net income plus total D&A, which is what `scoring.py` already uses and what
    its comment already disclaims at length: it is not NAREIT FFO, because
    yfinance exposes no gain-on-sale-of-real-estate row to subtract. Reported
    as a proxy and named one — 81.5% in the newest year, rising from 71.4%,
    which is the reading a REIT investor actually wants and is nowhere near the
    261.2% a net-income payout ratio reports for the same company.
    """
    coverage = valued["diagnostics"]["payout_of_ffo_proxy"]
    assert [c["period"] for c in coverage] == [
        "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
    assert coverage[-1]["payout_of_ffo_proxy"] == pytest.approx(0.8153, abs=0.0001)
    assert all(0.5 < c["payout_of_ffo_proxy"] < 1.0 for c in coverage)
    assert "not_nareit_ffo" in valued["diagnostics"]["ffo_basis"]


def test_both_readings_of_the_growth_series_are_published(valued):
    """Compound and mean year-on-year, 2 basis points apart on O. Published
    beside each other and never averaged: they agree because a declared dividend
    is a smoothed series, and a gap between them is the signal that it is not."""
    d = valued["diagnostics"]
    assert d["growth_compound"] == pytest.approx(0.044256, abs=1e-6)
    assert d["growth_mean_yoy"] == pytest.approx(0.044504, abs=1e-6)
    # The assumption carries the unrounded rate and the diagnostic the reported
    # one, so this is approx by construction rather than by tolerance-fudging.
    assert valued["assumptions"]["growth_rate_explicit"] == pytest.approx(
        d["growth_compound"], abs=1e-6)
    assert d["share_count_growth"] == pytest.approx(0.4145, abs=0.0001)


def test_the_terminal_growth_cap_is_reached_rather_than_merely_stated(monkeypatch, reit):
    """The cap only binds below a 2.5% risk-free rate, so nothing in this
    fixture set reaches it — the pinned rate is 4.30% and `min` picks the
    platform anchor every time.

    That makes it exactly the kind of line that ships untested: removing the
    `min` entirely leaves all 736 tests passing, which the mutation battery
    found on 2026-08-29. So the rate is driven under the anchor here to force
    the other branch, rather than asserting `terminal_growth == min(...)`,
    which restates the source line and passes whichever branch ran.

    The cost of equity is pinned by override throughout, because it moves with
    the risk-free rate too — and by more. Left free, cutting the rate to 0.8%
    raises the fair value from 69.51 to 115.74 despite the smaller perpetuity,
    and a test asserting the value fell would have failed for the right reason
    while proving nothing about the cap.
    """
    from backend import data_provider

    base = fm.dividend_discount_valuation(reit, cost_of_equity_override=0.10)
    assert base["assumptions"]["terminal_growth_source"] == "platform_default"
    assert base["assumptions"]["terminal_growth"] == fm.TERMINAL_GROWTH

    monkeypatch.setattr(data_provider, "_us_treasury_10y", lambda: 0.008)
    capped = fm.dividend_discount_valuation(reit, cost_of_equity_override=0.10)
    a = capped["assumptions"]

    assert a["risk_free_rate"] == pytest.approx(0.008, abs=1e-9)
    assert a["terminal_growth"] == pytest.approx(0.008, abs=1e-9)
    assert a["terminal_growth_source"] == "capped_at_risk_free_rate"
    assert a["terminal_growth"] < a["terminal_growth_anchor"]
    # With the discount rate held, a lower terminal growth is a smaller
    # perpetuity — so the cap has to cost value rather than merely relabel it.
    assert capped["fair_value_per_share"] < base["fair_value_per_share"]


def test_the_terminal_carries_most_of_the_answer_and_says_so(valued):
    d = valued["diagnostics"]
    assert d["terminal_value_share"] == pytest.approx(0.6271, abs=0.0001)
    assert d["terminal_value_high"] is False   # the flag fires above 0.75
    assert d["terminal_spread"] == pytest.approx(0.0501, abs=0.0001)
    assert valued["dividend_pv"] + valued["terminal_value_pv"] == pytest.approx(
        valued["fair_value_per_share"], abs=0.01)


# ── currency, which the only REIT fixture cannot exercise ─────────────

def test_a_statement_currency_that_differs_from_the_traded_one_is_converted():
    """Dividends per share are a reporting-currency figure and the price is a
    traded one. O reports and trades in USD, so `conv` is 1.0 on the only REIT
    in the fixture set and **deleting the conversion entirely leaves the whole
    suite green** — found by mutation 2026-08-29. For reference, the DCF's tests
    pin the FX basis in eight places and the excess return model's in one; this
    model's in none.

    Driven here as CNY reporting against an HKD listing, the pair `conftest`
    already pins at 1.10, so the multiplier is checked against a rate no part of
    this test computed. Cost of equity and terminal growth are both overridden
    so that the currency change moves exactly one thing: without that, switching
    the reporting currency also re-points the risk-free rate at ChinaBond and
    the two effects arrive together.
    """
    plain = fm.dividend_discount_valuation(
        load_fundamentals("O"), cost_of_equity_override=0.10, terminal_growth=0.025)

    crossed = load_fundamentals("O")
    crossed["info"]["financialCurrency"] = "CNY"
    crossed["info"]["currency"] = "HKD"
    converted = fm.dividend_discount_valuation(
        crossed, cost_of_equity_override=0.10, terminal_growth=0.025)

    assert plain["assumptions"]["fx_basis"] == "single_currency"
    assert plain["assumptions"]["fx_rate_used"] is None
    assert converted["assumptions"]["fx_basis"] == "converted"
    assert converted["assumptions"]["fx_rate_used"] == pytest.approx(1.10)

    # Both legs scale by the rate exactly, so the conversion is applied once to
    # the whole valuation rather than to whichever line someone remembered.
    assert converted["dividend_pv"] / plain["dividend_pv"] == pytest.approx(1.10, abs=1e-6)
    assert converted["terminal_value_pv"] / plain["terminal_value_pv"] == pytest.approx(1.10, abs=1e-6)
    assert converted["fair_value_per_share"] == pytest.approx(
        plain["fair_value_per_share"] * 1.10, abs=0.01)

    # The dividend itself stays in reporting units — it is an input, not an
    # answer, and converting it twice is the other way to get this wrong.
    assert converted["assumptions"]["dividend_per_share"] == pytest.approx(
        plain["assumptions"]["dividend_per_share"], abs=1e-9)


def test_without_a_rate_every_cross_currency_comparison_is_withheld():
    """Not converted at a guessed rate and not compared across two units. The
    per-share figure is still reported, because it is a valid answer in the
    reporting currency; everything that puts it beside the traded price is not.
    """
    stranded = load_fundamentals("O")
    stranded["info"]["financialCurrency"] = "USD"
    stranded["info"]["currency"] = "HKD"   # no USD->HKD rate is pinned
    out = fm.dividend_discount_valuation(stranded)

    assert out["assumptions"]["fx_basis"] == "rate_unavailable"
    assert out["fair_value_per_share"] == pytest.approx(69.51, abs=0.01)
    assert out["upside_pct"] is None
    assert out["diagnostics"]["implied_cost_of_equity"] is None
    assert out["diagnostics"]["trailing_dividend_yield"] is None


def test_the_terminal_growth_cap_binds_for_a_reporter_in_a_low_rate_currency():
    """The cap reached without monkeypatching anything, which is the better
    witness: a CNY reporter discounts at ChinaBond's rate, and `conftest` pins
    that low enough that `min(TERMINAL_GROWTH, rf)` picks the rate rather than
    the platform anchor."""
    crossed = load_fundamentals("O")
    crossed["info"]["financialCurrency"] = "CNY"
    crossed["info"]["currency"] = "HKD"
    a = fm.dividend_discount_valuation(crossed)["assumptions"]

    assert a["risk_free_rate"] == pytest.approx(0.011, abs=1e-6)
    assert a["terminal_growth"] == pytest.approx(0.011, abs=1e-6)
    assert a["terminal_growth_source"] == "capped_at_risk_free_rate"
    assert a["terminal_growth"] < a["terminal_growth_anchor"]


def test_the_yield_names_which_dividend_it_divides_by(valued):
    """Three different numbers have a claim to the name "dividend yield" on this
    company: the trailing 4.99%, the forward 5.21%, and yfinance's own 5.17%.
    The field was called `dividend_yield_on_price` and was pinned by nothing —
    swapping it to the forward figure left the suite green.
    """
    a = valued["assumptions"]
    trailing = a["dividend_per_share"] / valued["current_price"]
    forward = a["dividend_per_share"] * (1 + a["growth_rate_explicit"]) / valued["current_price"]

    assert valued["diagnostics"]["trailing_dividend_yield"] == pytest.approx(
        trailing, abs=1e-6)
    assert valued["diagnostics"]["trailing_dividend_yield"] != pytest.approx(
        forward, abs=1e-4)
    assert trailing == pytest.approx(0.0499, abs=0.0001)
    assert forward == pytest.approx(0.0521, abs=0.0001)


def test_the_terminal_weight_flag_has_a_threshold_that_something_crosses(reit, valued):
    """62.7% on the base case, so the flag is False — and it is False whether
    the line reads 0.75 or 0.95, which is how the threshold shipped pinned by
    nothing. Pushed over it here by raising terminal growth alone.

    Lowering the cost of equity would have been the obvious lever and cannot be
    used: below 7.30% the inversion refusal fires first, so on this company
    there is no cost of equity that produces a terminal-heavy valuation at all.
    """
    assert valued["diagnostics"]["terminal_value_share"] == pytest.approx(0.6271, abs=1e-4)
    assert valued["diagnostics"]["terminal_value_high"] is False

    heavy = fm.dividend_discount_valuation(reit, terminal_growth=0.05)
    assert heavy["diagnostics"]["terminal_value_share"] == pytest.approx(0.7883, abs=1e-4)
    assert heavy["diagnostics"]["terminal_value_high"] is True
    assert heavy["fair_value_per_share"] == pytest.approx(127.50, abs=0.01)


# ── the envelope ──────────────────────────────────────────────────────

def test_it_returns_no_aggregate_it_never_computed(reit, valued):
    """Per-share from the first line to the last. Multiplying back by a share
    count to publish an `equity_value` would invent a figure the model never
    formed — the same refusal the excess return model makes about enterprise
    value, for the same reason.

    Diffed against a live `dcf_valuation` rather than against a hardcoded key
    list, so a key added to the shared envelope later cannot drift these two
    apart while this test goes on passing.
    """
    dcf = fm.dcf_valuation(load_fundamentals("AAPL"))
    shared = {"assumptions", "fair_value_per_share", "current_price",
              "upside_pct", "diagnostics", "sensitivity", "growth_sensitivity"}
    assert shared <= set(dcf) and shared <= set(valued)

    for absent in ("enterprise_value", "net_debt", "equity_value",
                   "book_value_of_equity", "roe_sensitivity"):
        assert absent not in valued

    banked = fm.excess_returns_valuation(load_fundamentals("JPM"))
    assert "equity_value" in banked, "the contrast is the point of the loop above"


def test_the_grid_sweeps_the_assumption_rather_than_the_measurement(valued):
    """Terminal growth against cost of equity, matching the DCF's grid step for
    step rather than the excess return model's.

    There the two first-order inputs are ROE and the cost of equity and the
    growth rate is a function of ROE, so the grid sweeps both. Here the explicit
    rate is measured from four years of the company's own declared dividends —
    a fact — while terminal growth is a pure assumption carrying 62.7% of the
    answer. The assumption gets the axis; the measurement gets its own sweep.
    """
    assert valued["sensitivity"]["terminal_growth_cols"] == [
        0.02, 0.0225, 0.025, 0.0275, 0.03]
    rows = valued["sensitivity"]["rows"]
    assert [r["cost_of_equity"] for r in rows] == [
        pytest.approx(0.0751 + d, abs=1e-6) for d in fm.DDM_KE_STEPS]

    # Falling down the rows, rising across them — a grid that did neither would
    # be a grid of the same number five times.
    assert all(r["values"] == sorted(r["values"]) for r in rows)
    assert [r["values"][2] for r in rows] == sorted(
        [r["values"][2] for r in rows], reverse=True)

    # And the one-dimensional sweep is *not* a row of the grid, which is exactly
    # the difference from the excess return model's and the reason its band
    # unions this in rather than declining to.
    assert valued["growth_sensitivity"]["values"] != rows[2]["values"]
