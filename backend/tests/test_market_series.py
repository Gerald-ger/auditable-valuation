"""Return-series maths, and the beta and relative strength built on it.

The platform used to read both of these off vendor scalars. `market_series` is
the machinery that replaced them, so these tests cover the arithmetic first and
the wiring second — a beta that regresses correctly but is fed misaligned weeks
is wrong in a way no valuation test would catch.
"""
from __future__ import annotations

import pytest

from conftest import load_bars, load_fundamentals, load_market_bars

from backend import financial_models as fm
from backend import market_series as ms
from backend import scoring


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


def test_a_motionless_stock_yields_no_beta():
    """The mirror of the motionless-index case, and it became load-bearing when
    `resolve_beta` started reading the confidence interval.

    A halted or delisted series forward-filled to one price has an exactly zero
    residual, so the standard error is zero, the interval collapses to a point,
    and the fit *rejects* the credibility floor more confidently than any real
    measurement can. Without this the beta would be 0.0 — used as measured,
    because the interval "excludes" 0.30 — which is the fabricated number
    `BETA_MIN` exists to refuse.
    """
    index_closes = [100.0]
    for r in [0.01, -0.02, 0.03] * 40:
        index_closes.append(index_closes[-1] * (1 + r))

    fit, n = ms.beta_fit(_bars([100.0] * len(index_closes)), _bars(index_closes))
    assert fit is None
    assert ms.beta(_bars([100.0] * len(index_closes)), _bars(index_closes))[0] is None

    # and end to end: the floor is not bypassed, because there is no regression
    used, source = fm.resolve_beta({"beta": 1.1}, None, 0.21,
                                   _bars([100.0] * len(index_closes)),
                                   _bars(index_closes))
    assert (used, source) == (1.1, "reported")


def test_change_over_needs_a_full_window():
    assert ms.change_over(_bars([100.0] * 52), periods=52) is None
    assert ms.change_over(_bars([100.0] * 52 + [110.0]), periods=52) == pytest.approx(0.10)


# ── how well the regression fits ─────────────────────────────────────

def test_the_fit_reports_its_own_precision():
    """A slope with no error term cannot say whether it measured anything. The
    standard error is the textbook OLS slope error; these figures were checked
    against numpy's polyfit covariance matrix and the algebraic form, agreeing
    to 1e-12, when this was written."""
    fit, n = ms.beta_fit(*load_market_bars("XOM"))
    assert n == 261
    assert fit["beta"] == pytest.approx(0.288806, abs=1e-5)
    assert fit["standard_error"] == pytest.approx(0.10512, abs=1e-4)
    assert fit["r_squared"] == pytest.approx(0.0283, abs=1e-3)

    lo, hi = fit["confidence_interval"]
    assert lo == pytest.approx(fit["beta"] - ms.BETA_CI_Z * fit["standard_error"])
    assert hi == pytest.approx(fit["beta"] + ms.BETA_CI_Z * fit["standard_error"])


def test_the_t_statistic_identity_holds():
    """t = beta/SE must satisfy t^2 = R^2/(1-R^2) * (n-2) for a simple
    regression. If it does not, the error and the fit were computed from
    different residuals — which is exactly the bug a hand-rolled OLS invites."""
    for stem in ("AAPL", "XOM", "0700_HK"):
        fit, n = ms.beta_fit(*load_market_bars(stem))
        t = fit["beta"] / fit["standard_error"]
        r2 = fit["r_squared"]
        assert t ** 2 == pytest.approx(r2 / (1 - r2) * (n - 2), rel=1e-9), stem


def test_the_fit_separates_a_measurement_from_a_non_measurement():
    """The whole point. Both of these are 5y weekly regressions over 260-odd
    observations and both used to reach the caller as a bare four-decimal
    number; one of them explains almost nothing."""
    tencent, _ = ms.beta_fit(*load_market_bars("0700_HK"))
    xom, _ = ms.beta_fit(*load_market_bars("XOM"))

    assert tencent["r_squared"] > 0.65 and xom["r_squared"] < 0.05
    tencent_width = tencent["confidence_interval"][1] - tencent["confidence_interval"][0]
    xom_width = xom["confidence_interval"][1] - xom["confidence_interval"][0]

    # XOM's slope is roughly a fifth of Tencent's and its interval is still
    # wider in absolute terms.
    assert xom_width > tencent_width

    # The sharpest way to put it: XOM's interval is wider than the estimate it
    # brackets, so the measurement does not even establish the beta's own order
    # of magnitude. Tencent's is a small fraction of its estimate.
    assert xom_width > xom["beta"]
    assert tencent_width < 0.2 * tencent["beta"]


def test_beta_is_a_reading_of_the_same_fit():
    """`beta` must not become a second implementation of the slope."""
    for stem in ("AAPL", "XOM", "O"):
        bars = load_market_bars(stem)
        assert ms.beta(*bars)[0] == ms.beta_fit(*bars)[0]["beta"]


def test_no_fit_where_there_is_no_beta():
    """Both guards agree: too short a series, and a motionless index."""
    assert ms.beta_fit(_bars([100.0] * 10), _bars([100.0] * 10))[0] is None
    flat = _bars([100.0] * 200)
    moving = _bars([100.0 * (1.001 ** i) for i in range(200)])
    assert ms.beta_fit(moving, flat)[0] is None


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
