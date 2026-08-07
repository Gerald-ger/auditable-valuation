"""Geometry of user-drawn chart lines.

The contract under test is that the *engine* computes every number the AI will
see about a drawing, and that the drawing stays labelled as the user's assertion
rather than a model output.
"""
from __future__ import annotations

import pytest

import drawings

DAY = 86400
T0 = 1_786_000_000


def _hline(price=100.0, **kw):
    return {"id": 1, "kind": "hline", "p1": price, "t1": None, "t2": None,
            "p2": None, "label": None, **kw}


def _trend(p1=100.0, p2=110.0, t1=T0, t2=T0 + 10 * DAY, **kw):
    return {"id": 2, "kind": "trendline", "p1": p1, "p2": p2, "t1": t1, "t2": t2,
            "label": None, **kw}


def _bar(t, low, high, close=None):
    return {"time": t, "low": low, "high": high, "close": close if close is not None else high}


# ── price along the line ─────────────────────────────────────────────

def test_horizontal_line_is_flat_everywhere():
    h = _hline(210.0)
    assert drawings.price_at(h, T0) == 210.0
    assert drawings.price_at(h, T0 + 900 * DAY) == 210.0
    assert drawings.slope_per_day(h) == 0.0


def test_trendline_interpolates_between_its_endpoints():
    t = _trend(100.0, 110.0, T0, T0 + 10 * DAY)
    assert drawings.price_at(t, T0) == pytest.approx(100.0)
    assert drawings.price_at(t, T0 + 5 * DAY) == pytest.approx(105.0)
    assert drawings.price_at(t, T0 + 10 * DAY) == pytest.approx(110.0)
    assert drawings.slope_per_day(t) == pytest.approx(1.0)


def test_trendline_extends_beyond_the_drawn_segment():
    """The point of drawing one is to ask where it will be, so it must extend."""
    t = _trend(100.0, 110.0, T0, T0 + 10 * DAY)
    assert drawings.price_at(t, T0 + 20 * DAY) == pytest.approx(120.0)
    assert drawings.price_at(t, T0 - 10 * DAY) == pytest.approx(90.0)


def test_degenerate_trendline_returns_no_price():
    """Both endpoints on the same timestamp is a vertical line, not a trend."""
    assert drawings.price_at(_trend(t1=T0, t2=T0), T0) is None
    assert drawings.slope_per_day(_trend(t1=T0, t2=T0)) is None


# ── touches: the only evidence a drawn level meant anything ──────────

def test_touches_count_bars_that_reached_the_line():
    h = _hline(100.0)
    bars = [
        _bar(T0, 99.8, 100.1),          # touch
        _bar(T0 + DAY, 90.0, 92.0),     # nowhere near
        _bar(T0 + 2 * DAY, 100.3, 105.0),  # low within 0.5%
    ]
    assert drawings.describe(h, bars, 100.0)["bars_touching"] == 2


def test_a_line_through_empty_space_reports_zero_touches():
    """Reported as zero, not omitted — 'price never respected this' is the
    single most useful thing to say about such a line."""
    out = drawings.describe(_hline(500.0),
                            [_bar(T0 + i * DAY, 99, 101) for i in range(10)], 100.0)
    assert out["bars_touching"] == 0
    assert out["bars_closing_below"] == 10


def test_closes_are_split_above_and_below_the_line():
    h = _hline(100.0)
    bars = [_bar(T0, 104, 106, close=105), _bar(T0 + DAY, 94, 96, close=95)]
    out = drawings.describe(h, bars, 105.0)
    assert out["bars_closing_above"] == 1
    assert out["bars_closing_below"] == 1


# ── the summary handed to the model ──────────────────────────────────

def test_distance_from_current_price_and_its_direction():
    out = drawings.describe(_hline(100.0), [_bar(T0, 99, 101)], 110.0)
    assert out["price_vs_line_pct"] == pytest.approx(10.0)
    assert out["price_is"] == "above"

    below = drawings.describe(_hline(100.0), [_bar(T0, 99, 101)], 90.0)
    assert below["price_vs_line_pct"] == pytest.approx(-10.0)
    assert below["price_is"] == "below"


def test_every_drawing_is_marked_as_the_users_own():
    """If this is lost, the model will discuss a drawn level as if the engine
    derived it — the one thing the AI in this app must never do."""
    out = drawings.describe(_hline(), [_bar(T0, 99, 101)], 100.0)
    assert out["drawn_by"] == "user"


def test_the_context_block_says_so_too():
    block = drawings.describe_all([_hline(), _trend()],
                                  [_bar(T0, 99, 101)], 100.0)
    assert block["count"] == 2
    assert "drawn by the user" in block["note"]
    assert "not" in block["note"] and "engine" in block["note"]


def test_no_drawings_is_stated_rather_than_omitted():
    block = drawings.describe_all([], [], 100.0)
    assert block["count"] == 0
    assert block["drawings"] == []


def test_daily_date_string_bars_are_understood():
    """Daily bars carry a date string, intraday bars an epoch — both must work."""
    # within the 0.5% touch tolerance of a 100.0 line
    bars = [{"time": "2026-08-06", "low": 99.7, "high": 100.2, "close": 100.0}]
    out = drawings.describe(_hline(100.0), bars, 100.0)
    assert out["bars_touching"] == 1


def test_missing_current_price_does_not_invent_a_distance():
    out = drawings.describe(_hline(100.0), [_bar(T0, 99, 101)], None)
    assert out["price_vs_line_pct"] is None
    assert out["price_is"] is None
