"""Portfolio row arithmetic.

Written for one defect: a cost basis of exactly zero produced a real
`unrealized_pnl` alongside a null `unrealized_pnl_pct`, and PortfolioTab read
the percentage off the absolute figure's guard. The `TypeError` landed inside
the component's own render, so the ErrorBoundary unmounted the whole tab —
including the form needed to correct the position — leaving no route back from
the UI.

The arithmetic was inline in the `/api/portfolio` handler and therefore
untestable, which is the reason the shipped shape was never checked. It now
lives in `main.position_values`, and what these tests pin is the *contract the
frontend depends on*: which fields can be null, and when.
"""
from __future__ import annotations

import pytest

from backend import main


def test_a_zero_cost_basis_has_a_gain_but_no_percentage_return():
    """The crash case. Zero cost is a real position (a gift, a vest, a typo),
    the absolute gain is well defined, and the percentage return is not —
    the denominator is zero."""
    v = main.position_values(price=250.0, shares=10.0, cost=0.0)
    assert v["unrealized_pnl"] == pytest.approx(2500.0)
    assert v["unrealized_pnl_pct"] is None


def test_both_pnl_forms_are_present_for_an_ordinary_position():
    v = main.position_values(price=250.0, shares=10.0, cost=200.0)
    assert v["unrealized_pnl"] == pytest.approx(500.0)
    assert v["unrealized_pnl_pct"] == pytest.approx(25.0)


def test_a_watchlist_row_has_no_money_figures_but_still_prices():
    """Shares = 0 is watch-only; value and cost are zero, not null, and the
    percentage return still reads off price vs cost."""
    v = main.position_values(price=250.0, shares=0.0, cost=200.0)
    assert v["market_value"] == 0.0
    assert v["unrealized_pnl"] == 0.0
    assert v["unrealized_pnl_pct"] == pytest.approx(25.0)


def test_no_cost_basis_means_no_pnl_at_all():
    v = main.position_values(price=250.0, shares=10.0, cost=None)
    assert v["cost_value"] is None
    assert v["unrealized_pnl"] is None
    assert v["unrealized_pnl_pct"] is None


def test_an_unpriceable_ticker_nulls_every_money_figure():
    """_safe_quote returns {'error': ...} with no price when yfinance fails."""
    v = main.position_values(price=None, shares=10.0, cost=200.0)
    assert v["market_value"] is None
    assert v["unrealized_pnl"] is None
    assert v["unrealized_pnl_pct"] is None


def test_a_loss_is_signed_on_both_forms():
    v = main.position_values(price=150.0, shares=10.0, cost=200.0)
    assert v["unrealized_pnl"] == pytest.approx(-500.0)
    assert v["unrealized_pnl_pct"] == pytest.approx(-25.0)


@pytest.mark.parametrize("price,shares,cost", [
    (250.0, 10.0, 0.0),      # the crash case
    (250.0, 10.0, None),
    (None, 10.0, 200.0),
    (None, 0.0, None),
    (0.0, 10.0, 200.0),      # a delisted name quoted at zero
])
def test_the_percentage_is_never_present_without_the_absolute(price, shares, cost):
    """The one-way implication PortfolioTab may rely on. The converse does not
    hold — that asymmetry is the bug — so it must not be assumed anywhere."""
    v = main.position_values(price, shares, cost)
    if v["unrealized_pnl_pct"] is not None:
        assert v["unrealized_pnl"] is not None


# ── the aggregation, which had no test at all ────────────────────────
#
# Everything above tests `position_values`, a pure function over one row. The
# endpoint's own arithmetic — the totals, the weights and the concentration —
# had never been reached by anything, which is how it summed US dollars and
# Hong Kong dollars at face value for as long as it has existed.


@pytest.fixture
def priced_portfolio(monkeypatch, temp_db):
    """`main.portfolio()` with the store, the quote feed and the FX feed stubbed.

    `holdings` maps ticker -> (price, currency, shares, cost_basis); `rates`
    maps (from, to) -> rate. The stub mirrors `fx_rate`'s real contract on the
    two points that matter here: same currency is 1.0 without a lookup, and an
    unavailable pair is None rather than an exception.
    """
    def install(holdings, rates=None):
        rates = rates or {}
        quotes = {}
        for ticker, (price, currency, shares, cost) in holdings.items():
            temp_db.upsert_position(ticker, shares=shares, cost_basis=cost)
            quotes[ticker] = {"price": price, "currency": currency, "name": ticker}
        monkeypatch.setattr(main.provider, "get_quote", lambda t: quotes[t])
        monkeypatch.setattr(main, "fx_rate",
                            lambda a, b: 1.0 if a and a == b else rates.get((a, b)))
        return main.portfolio()
    return install


MIXED = {"AAPL": (311.0, "USD", 10, None), "0700.HK": (481.4, "HKD", 1000, None)}
PEG = {("USD", "HKD"): 7.80}


def test_a_mixed_total_is_converted_rather_than_added_at_face_value(priced_portfolio):
    """The two committed fixture prices, held together.

    Face value adds 3,110 US dollars to 481,400 Hong Kong dollars as though they
    were the same unit and reports 484,510 of nothing. At the peg the AAPL leg is
    24,258 HKD, so the portfolio is worth 505,658.

    The size of this error is not fixed — it scales with how much of the
    portfolio sits away from the base currency. Here it is 4.2%, because 99% of
    the value is already HKD. An all-USD portfolio under an HKD base is out by
    the whole peg, 7.8x, and that is measured below.
    """
    result = priced_portfolio(MIXED, PEG)
    assert result["totals"]["market_value"] == pytest.approx(505_658.0)
    assert result["totals"]["currency"] == "HKD"


def test_an_all_usd_portfolio_is_out_by_the_whole_rate(priced_portfolio):
    """The worst case, and the one a Hong Kong holder of US stocks actually has."""
    result = priced_portfolio({"AAPL": (311.0, "USD", 10, None)}, PEG)
    assert result["totals"]["market_value"] == pytest.approx(24_258.0)


def test_weights_are_shares_of_the_converted_total(priced_portfolio):
    """A ratio of two figures in different units is not a weight.

    AAPL is 4.80% of this portfolio and read as 0.64% — understated by a factor
    of 7.5, which is the exchange rate. Unlike the total, this error does not
    depend on the base currency: it is the same ratio whichever side you convert.
    """
    rows = {r["ticker"]: r for r in priced_portfolio(MIXED, PEG)["rows"]}
    assert rows["AAPL"]["weight_pct"] == pytest.approx(4.797, abs=0.01)
    assert rows["0700.HK"]["weight_pct"] == pytest.approx(95.203, abs=0.01)


def test_concentration_follows_the_converted_weights(priced_portfolio):
    """Face value made this a 99.4% single-name portfolio. It is 95.2%."""
    conc = priced_portfolio(MIXED, PEG)["concentration"]
    assert conc["top_weight_pct"] == pytest.approx(95.2, abs=0.05)


def test_cost_and_pnl_convert_with_the_value_but_the_percentage_does_not(priced_portfolio):
    """Converting the value and not the cost would report a profit made entirely
    of exchange rate. The percentage is a same-row ratio, so the rate cancels
    and it must not move — converting it would be a category error."""
    row = priced_portfolio({"AAPL": (311.0, "USD", 10, 200.0)}, PEG)["rows"][0]
    assert row["market_value"] == pytest.approx(311.0 * 10 * 7.80)
    assert row["cost_value"] == pytest.approx(200.0 * 10 * 7.80)
    assert row["unrealized_pnl"] == pytest.approx((311.0 - 200.0) * 10 * 7.80)
    assert row["unrealized_pnl_pct"] == pytest.approx((311.0 / 200.0 - 1) * 100)


def test_an_unavailable_rate_refuses_the_total_rather_than_guessing(priced_portfolio):
    """`fx_rate`'s own docstring: callers suppress the comparison instead of
    printing a number built on a guess. Falling back to a face-value sum is a
    guess — it is exactly today's wrong number with a warning beside it.

    All or nothing, deliberately: converting the rows that can be converted and
    leaving the rest native would make one column two units, which is the defect
    rather than a partial fix.
    """
    result = priced_portfolio(MIXED, {})
    assert result["totals"]["market_value"] is None
    assert result["totals"]["currency"] is None
    assert result["totals"]["unconverted_currencies"] == ["USD"]
    assert all(r["weight_pct"] is None for r in result["rows"])
    assert result["concentration"]["top_weight_pct"] is None

    rows = {r["ticker"]: r for r in result["rows"]}
    assert rows["AAPL"]["market_value"] == pytest.approx(3110.0)


def test_a_portfolio_already_in_the_base_currency_needs_no_rate(priced_portfolio):
    """The regression pin. Same currency resolves to 1.0 without a lookup, so
    the common case must be untouched and must not depend on a feed being up."""
    result = priced_portfolio({"0700.HK": (481.4, "HKD", 1000, 400.0)})
    assert result["totals"]["market_value"] == pytest.approx(481_400.0)
    assert result["totals"]["cost_value"] == pytest.approx(400_000.0)
    assert result["totals"]["unconverted_currencies"] == []
    assert result["rows"][0]["weight_pct"] == pytest.approx(100.0)
