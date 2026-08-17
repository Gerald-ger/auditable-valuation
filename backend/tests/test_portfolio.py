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
