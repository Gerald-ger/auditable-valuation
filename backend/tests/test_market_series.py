"""Return-series maths, and the beta and relative strength built on it.

The platform used to read both of these off vendor scalars. `market_series` is
the machinery that replaced them, so these tests cover the arithmetic first and
the wiring second — a beta that regresses correctly but is fed misaligned weeks
is wrong in a way no valuation test would catch.
"""
from __future__ import annotations

import pytest

from conftest import load_bars, load_fundamentals, load_market_bars

import financial_models as fm
import market_series as ms
import scoring


def _bars(closes, start=0):
    """Weekly bars with sequential dates; only `time` and `close` are read."""
    return [{"time": f"2020-01-{i + start + 1:02d}", "close": c}
            for i, c in enumerate(closes)]


# ── the arithmetic ───────────────────────────────────────────────────

def test_beta_recovers_a_known_slope():
    """Construct a stock whose returns are exactly 1.5x the index's, and the
    regression must return 1.5. Without this, every other beta assertion is
    just comparing one implementation against itself."""
    index_closes = [100.0]
    for r in [0.01, -0.02, 0.03, -0.01, 0.02] * 30:
        index_closes.append(index_closes[-1] * (1 + r))
    stock_closes = [100.0]
    for i in range(1, len(index_closes)):
        r = index_closes[i] / index_closes[i - 1] - 1
        stock_closes.append(stock_closes[-1] * (1 + 1.5 * r))

    beta, n = ms.beta(_bars(stock_closes), _bars(index_closes))
    assert n == len(index_closes) - 1
    assert beta == pytest.approx(1.5, rel=1e-6)


def test_beta_matches_a_least_squares_slope_on_real_series():
    """Cross-checked against numpy's cov/var and against a polyfit slope when
    this was written — agreement to 1e-9 on all five DCF-eligible fixtures.
    Pinned here without numpy so the suite keeps only the dependencies it has.
    """
    stock, index = load_market_bars("XOM")
    beta, n = ms.beta(stock, index)
    assert n == 261                      # 262 weekly closes -> 261 returns
    assert beta == pytest.approx(0.288806, abs=1e-5)


def test_align_drops_dates_only_one_series_has():
    """The failure this prevents is silent: two lists of nearly equal length
    zipped together pair week 40 of one against week 41 of the other from the
    first mismatch onward, producing a plausible-looking wrong beta. HK and US
    market calendars genuinely differ — on the committed fixtures AAPL and ^HSI
    share 261 of 262 dates."""
    stock = _bars([10.0, 11.0, 12.0, 13.0])
    index = [b for b in _bars([100.0, 101.0, 102.0, 103.0]) if b["time"] != "2020-01-03"]

    closes_s, closes_i = ms.align(stock, index)
    assert len(closes_s) == len(closes_i) == 3
    assert 12.0 not in closes_s          # the unmatched date is gone, not shifted


def test_align_output_lengths_always_match():
    """A non-positive close must drop the *pair*, not shorten one side."""
    stock = _bars([10.0, 0.0, 12.0, 13.0])
    closes_s, closes_i = ms.align(stock, _bars([100.0, 101.0, 102.0, 103.0]))
    assert len(closes_s) == len(closes_i) == 3


def test_too_short_a_series_yields_no_beta():
    """A regression over a handful of weeks fits noise. Returning None sends the
    caller down its existing ladder instead of inventing confidence."""
    beta, n = ms.beta(_bars([100.0] * 10), _bars([100.0] * 10))
    assert beta is None and n < ms.MIN_BETA_OBSERVATIONS


def test_a_motionless_index_yields_no_beta():
    """Zero variance in the denominator. A halted or placeholder series looks
    exactly like this."""
    flat = _bars([100.0] * 200)
    moving = _bars([100.0 * (1.001 ** i) for i in range(200)])
    assert ms.beta(moving, flat)[0] is None


def test_change_over_needs_a_full_window():
    assert ms.change_over(_bars([100.0] * 52), periods=52) is None
    assert ms.change_over(_bars([100.0] * 52 + [110.0]), periods=52) == pytest.approx(0.10)


# ── beta resolution ──────────────────────────────────────────────────

def test_xom_gets_a_measured_beta_instead_of_the_neutral_default():
    """The defect this work exists for. XOM's reported 0.173 fails the band and
    only one of its four peers survives it, so `resolve_beta` fell through to a
    flat 1.0 — the least informative answer available, applied to the company
    with the most distinctive risk profile in the fixture set."""
    f = load_fundamentals("XOM")
    assert fm.resolve_beta(f["info"], None) == (fm.BETA_FALLBACK, "default")

    beta, source = fm.resolve_beta(f["info"], None, bars=load_bars("XOM"),
                                   index_bars=load_bars("_GSPC"))
    assert source == "computed"
    assert beta < 0.5          # measured 0.2888, clamped up to the 0.3 floor


def test_a_measured_beta_outranks_a_credible_reported_one():
    """AAPL's 1.086 would pass the band. The regression still wins: the vendor's
    method is undisclosed, and its errors are correlated across a sector rather
    than random, which is what a band cannot catch."""
    f = load_fundamentals("AAPL")
    assert fm.resolve_beta(f["info"], None)[1] == "reported"
    assert fm.resolve_beta(f["info"], None, bars=load_bars("AAPL"),
                           index_bars=load_bars("_GSPC"))[1] == "computed"


def test_without_bars_the_existing_ladder_is_untouched():
    """Everything below the computed tier keeps its old order, so a history
    outage restores exactly the previous behaviour rather than a third one."""
    for stem, expected in (("AAPL", "reported"), ("XOM", "default")):
        assert fm.resolve_beta(load_fundamentals(stem)["info"], None)[1] == expected


def test_a_computed_beta_is_held_inside_the_credibility_band():
    """A thin or violently levered series can still regress past anything
    plausible, so the clamp applies to a measured value too. The index needs
    genuinely varying returns here — a smooth exponential has zero return
    variance and no slope is defined against it at all."""
    index_closes, wild_closes = [100.0], [100.0]
    for r in [0.01, -0.02, 0.03, -0.01, 0.02] * 40:
        index_closes.append(index_closes[-1] * (1 + r))
        wild_closes.append(wild_closes[-1] * (1 + 4.0 * r))

    beta, source = fm.resolve_beta({"beta": None}, None, bars=_bars(wild_closes),
                                   index_bars=_bars(index_closes))
    assert source == "computed"
    assert beta == fm.BETA_MAX           # measured ~4.0, held at the ceiling


def test_the_valuation_reports_whether_the_vendor_beta_was_credible():
    """`beta_source != "reported"` used to mean "the vendor's number failed the
    band". With a measured beta on top it usually means "we had something
    better", and the UI must not accuse credible data of being untrustworthy."""
    a = fm.dcf_valuation(load_fundamentals("AAPL"),
                         market_bars=load_market_bars("AAPL"))["assumptions"]
    assert a["beta_source"] == "computed"
    assert a["beta_reported_credible"] is True

    x = fm.dcf_valuation(load_fundamentals("XOM"),
                         market_bars=load_market_bars("XOM"))["assumptions"]
    assert x["beta_reported_credible"] is False


# ── relative strength ────────────────────────────────────────────────

def test_hk_relative_strength_uses_the_hang_seng():
    """0700.HK was scored against the S&P 500, an index it does not trade on.
    Measured on the committed bars: -24.23% against the Hang Seng's -0.43% is
    -23.79%, where the S&P's +20.92% would make it -45.15%."""
    raw, _ = scoring.extract_metrics(load_fundamentals("0700_HK"),
                                     load_market_bars("0700_HK"))
    assert raw["rel_52w_change"] == pytest.approx(-0.2379, abs=1e-3)


def test_us_relative_strength_uses_the_sp500():
    raw, _ = scoring.extract_metrics(load_fundamentals("AAPL"),
                                     load_market_bars("AAPL"))
    assert raw["rel_52w_change"] == pytest.approx(0.1138, abs=1e-3)


def test_the_vendor_index_scalar_is_not_used():
    """Measured live 2026-08-14: the S&P reports `52WeekChange` in percent
    (20.918) and the Hang Seng in decimal (0.500), and the Hang Seng figure
    matches neither its own price history (-1.41%) nor any unit reading of it.
    Reading it would have scored Tencent at roughly -63.7% relative, i.e. worse
    than the defect being fixed. The answer must sit nowhere near either the
    old scalar pair or that value."""
    f = load_fundamentals("0700_HK")
    raw, _ = scoring.extract_metrics(f, load_market_bars("0700_HK"))
    vendor_pair = f["info"]["52WeekChange"] - f["info"]["SandP52WeekChange"]

    assert raw["rel_52w_change"] != pytest.approx(vendor_pair, abs=1e-3)
    assert raw["rel_52w_change"] != pytest.approx(-0.637, abs=1e-2)


def test_without_bars_it_falls_back_to_the_scalars_and_says_so():
    """A history outage must degrade this metric, not drop the momentum pillar
    below its availability threshold — but the fallback has to be visible."""
    raw, flags = scoring.extract_metrics(load_fundamentals("AAPL"))
    assert raw["rel_52w_change"] is not None
    assert "rel_52w_change_from_vendor_scalars" in flags
