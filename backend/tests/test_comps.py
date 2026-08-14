"""Peer comps and the football field.

`comps.py` had no tests at all, which made it the largest piece of unaudited
financial arithmetic in the backend: it owns every peer-median-implied share
value and the width of every bar on the valuation-range chart. The two decisions
worth pinning are both recorded as measurements in its docstrings — the
interquartile band (§5.2 of the reference doc, not the grid's corners) and the
positive-only median — so this file turns those measurements into assertions.

Peers are fetched through `comps.provider`, so every test here swaps in a stub;
nothing touches the network.
"""
from __future__ import annotations

from statistics import quantiles

import pytest

from conftest import load_fundamentals

import comps
import financial_models as fm


class StubProvider:
    """Returns canned snapshots; raises for tickers it does not know."""

    def __init__(self, snapshots: dict):
        self.snapshots = snapshots
        self.calls = []

    def get_peer_snapshot(self, ticker: str) -> dict:
        self.calls.append(ticker)
        if ticker not in self.snapshots:
            raise ValueError(f"no data for {ticker}")
        return self.snapshots[ticker]


def snapshot(ticker, **overrides) -> dict:
    base = {
        "ticker": ticker, "name": ticker, "market_cap": 1e12, "beta": 1.0,
        "total_debt": 1e10, "pe_trailing": 20.0, "pe_forward": 18.0,
        "price_to_book": 3.0, "ev_to_ebitda": 12.0, "ev_to_revenue": 4.0,
        "peg_ratio": 1.5, "operating_margin": 0.25, "revenue_growth": 0.10,
    }
    return {**base, **overrides}


def target(**info_overrides) -> dict:
    info = {
        "longName": "Target Co", "marketCap": 1e12, "sharesOutstanding": 1e9,
        "totalDebt": 5e10, "totalCash": 2e10, "ebitda": 1e11, "totalRevenue": 4e11,
        "trailingEps": 5.0, "forwardEps": 6.0, "bookValue": 20.0,
        "trailingPE": 25.0, "forwardPE": 22.0, "priceToBook": 5.0,
        "enterpriseToEbitda": 14.0, "enterpriseToRevenue": 5.0, "pegRatio": 2.0,
        "operatingMargins": 0.30, "revenueGrowth": 0.12, "sector": "Technology",
    }
    return {"ticker": "TGT", "info": {**info, **info_overrides}}


@pytest.fixture
def stub(monkeypatch):
    def install(snapshots):
        p = StubProvider(snapshots)
        monkeypatch.setattr(comps, "provider", p)
        return p
    return install


# ── peer medians ─────────────────────────────────────────────────────

def test_peer_medians_are_the_median_of_the_reported_multiples(stub):
    stub({t: snapshot(t, pe_forward=v)
          for t, v in [("A", 10.0), ("B", 20.0), ("C", 30.0)]})
    result = comps.comps_analysis(target(), ["A", "B", "C"])
    assert result["peer_medians"]["pe_forward"] == 20.0


def test_a_non_positive_multiple_is_excluded_from_the_median(stub):
    """A negative P/E is not a cheap one — it is a loss-making company, and
    including it would drag the peer median toward a number no peer trades at."""
    stub({t: snapshot(t, pe_forward=v)
          for t, v in [("A", 20.0), ("B", 30.0), ("C", -50.0)]})
    result = comps.comps_analysis(target(), ["A", "B", "C"])
    assert result["peer_medians"]["pe_forward"] == 25.0  # median(20, 30), not median(-50, 20, 30)


def test_a_peer_that_fails_to_resolve_is_reported_not_swallowed(stub):
    stub({"A": snapshot("A")})
    result = comps.comps_analysis(target(), ["A", "MISSING"])
    assert [p["ticker"] for p in result["peers"]] == ["A"]
    assert result["failed_tickers"] == ["MISSING"]


def test_a_peer_with_no_market_cap_counts_as_failed(stub):
    """An empty yfinance payload returns a shaped dict full of Nones rather than
    raising, so 'resolved' has to mean 'has a market cap'."""
    stub({"A": snapshot("A"), "B": snapshot("B", market_cap=None)})
    result = comps.comps_analysis(target(), ["A", "B"])
    assert result["failed_tickers"] == ["B"]


def test_peer_list_is_capped_at_eight(stub):
    tickers = [f"P{i}" for i in range(12)]
    p = stub({t: snapshot(t) for t in tickers})
    comps.comps_analysis(target(), tickers)
    assert len(p.calls) == 8


# ── implied values ───────────────────────────────────────────────────

def test_ev_implied_bridges_to_equity_before_dividing_by_shares(stub):
    """An EV multiple values the *enterprise*; net debt has to come off before
    the result is a per-share equity figure."""
    stub({t: snapshot(t, ev_to_ebitda=10.0) for t in ("A", "B", "C")})
    f = target()
    result = comps.comps_analysis(f, ["A", "B", "C"])

    ebitda = f["info"]["ebitda"]
    net_debt = f["info"]["totalDebt"] - f["info"]["totalCash"]
    expected = (10.0 * ebitda - net_debt) / f["info"]["sharesOutstanding"]
    assert result["implied_values"]["peer_ev_ebitda"] == pytest.approx(expected, rel=1e-9)


def test_earnings_multiples_apply_directly_to_eps(stub):
    """A P/E is already an equity multiple — no bridge, no share count."""
    stub({t: snapshot(t, pe_forward=15.0, pe_trailing=18.0) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(), ["A", "B", "C"])
    assert result["implied_values"]["peer_forward_pe"] == pytest.approx(15.0 * 6.0)
    assert result["implied_values"]["peer_trailing_pe"] == pytest.approx(18.0 * 5.0)


def test_a_negative_implied_value_is_dropped(stub):
    """Net debt larger than the multiple-implied enterprise value means the
    method says the equity is worthless, which is not a valuation to plot."""
    stub({t: snapshot(t, ev_to_ebitda=0.1) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(totalDebt=9e11, totalCash=0), ["A", "B", "C"])
    assert "peer_ev_ebitda" not in result["implied_values"]


def test_price_to_book_is_implied_only_for_balance_sheet_sectors(stub):
    """P/B-implied value assumes book value means something. For a software
    company it does not."""
    stub({t: snapshot(t) for t in ("A", "B", "C")})
    tech = comps.comps_analysis(target(sector="Technology"), ["A", "B", "C"])
    bank = comps.comps_analysis(target(sector="Financial Services"), ["A", "B", "C"])
    assert "peer_price_to_book" not in tech["implied_values"]
    assert bank["implied_values"]["peer_price_to_book"] == pytest.approx(3.0 * 20.0)


# ── football field ───────────────────────────────────────────────────

def _dcf_with_grid(values: list[float], fair_value: float = 100.0) -> dict:
    """A DCF shaped like dcf_valuation's output, carrying `values` in the grid."""
    rows = [{"wacc": 0.08, "values": values[i:i + 5]} for i in range(0, len(values), 5)]
    return {"fair_value_per_share": fair_value,
            "sensitivity": {"terminal_growth_cols": [], "rows": rows}}


def test_dcf_bar_is_the_interquartile_band_not_the_grid_corners():
    """Reference doc §5.2. The grid's corners compound two assumptions moved
    together, so min/max produced a bar roughly twice the width the method
    supports — measured 2026-08-07: AAPL 55.27 -> 26.73, 0700.HK 330.00 ->
    149.08, and 0700.HK's verdict flipped from 'in range' to 'price below'.
    """
    values = [float(v) for v in range(50, 75)]  # 25 values, 50..74
    ranges = comps.football_field(target(), _dcf_with_grid(values), {})
    bar = next(r for r in ranges if r["method"].startswith("DCF"))

    q1, q3 = quantiles(values, n=4)[0], quantiles(values, n=4)[2]
    assert (bar["low"], bar["high"]) == (round(q1, 2), round(q3, 2))
    assert bar["high"] - bar["low"] < (max(values) - min(values)) * 0.6


def test_dcf_bar_midpoint_is_the_model_answer_not_the_grid_centre():
    """The bar shows the range; the tick shows what the model actually returned
    at its own assumptions."""
    ranges = comps.football_field(
        target(), _dcf_with_grid([float(v) for v in range(50, 75)], fair_value=61.5), {})
    assert next(r for r in ranges if r["method"].startswith("DCF"))["mid"] == 61.5


def test_a_thin_grid_falls_back_to_its_full_range():
    """Fewer than four surviving cells cannot support a quartile, so the honest
    answer is the range itself — labelled differently so the reader can tell."""
    dcf = _dcf_with_grid([90.0, 100.0, 110.0])
    bar = next(r for r in comps.football_field(target(), dcf, {})
               if r["method"].startswith("DCF"))
    assert (bar["low"], bar["high"]) == (90.0, 110.0)
    assert "25th" not in bar["method"]


def test_grid_cells_that_could_not_be_computed_are_skipped():
    """WACC <= terminal growth yields None cells; they must not become zeros."""
    values = [None, None] + [float(v) for v in range(50, 73)]
    bar = next(r for r in comps.football_field(target(), _dcf_with_grid(values), {})
               if r["method"].startswith("DCF"))
    assert bar["low"] > 50


def test_a_failed_dcf_contributes_no_bar():
    ranges = comps.football_field(target(), {"error": "no positive FCF"}, {})
    assert not any(r["method"].startswith("DCF") for r in ranges)


def test_analyst_targets_appear_only_when_both_bounds_exist():
    with_targets = comps.football_field(
        target(targetLowPrice=80.0, targetHighPrice=140.0, targetMeanPrice=110.0,
               numberOfAnalystOpinions=12), {}, {})
    without = comps.football_field(
        target(targetLowPrice=80.0, numberOfAnalystOpinions=12), {}, {})
    assert ("Analyst targets", 80.0, 140.0) == tuple(
        [with_targets[0]["method"], with_targets[0]["low"], with_targets[0]["high"]])
    assert not without


def test_peer_multiple_bar_spans_the_implied_values():
    comps_result = {"implied_values": {"a": 90.0, "b": 100.0, "c": 130.0}}
    bar = next(r for r in comps.football_field(target(), {}, comps_result)
               if r["method"].startswith("Peer"))
    assert (bar["low"], bar["mid"], bar["high"]) == (90.0, 100.0, 130.0)


# ── applicability, comparability and sample size ─────────────────────

@pytest.mark.parametrize("classification", ["real_estate_reit", "financials_bank",
                                            "financials_insurance"])
def test_no_dcf_bar_for_a_type_the_model_does_not_fit(classification):
    """The DCF error flag is the wrong gate and `scoring.py` says so: a REIT's
    `CFO - CapEx` is positive, so the model returns a confident number for a
    company whose capex *is* its acquisitions. The bar has to be refused on the
    classification, the way the Financial Models tab already refuses it."""
    healthy = _dcf_with_grid([float(v) for v in range(50, 75)])
    ranges = comps.football_field(target(), healthy, {}, classification)
    dcf_rows = [r for r in ranges if r["method"].startswith("DCF")]

    assert len(dcf_rows) == 1
    assert dcf_rows[0]["not_applicable"] is True
    assert "low" not in dcf_rows[0]
    assert classification.replace("_", " ") in dcf_rows[0]["reason"]


def test_a_type_the_model_does_fit_still_gets_its_bar():
    """The guard above must not fire on everything — a regression here would
    silently delete the DCF row for every company."""
    healthy = _dcf_with_grid([float(v) for v in range(50, 75)])
    bar = next(r for r in comps.football_field(target(), healthy, {}, "technology")
               if r["method"].startswith("DCF"))
    assert bar.get("not_applicable") is None and bar["low"] > 0


def test_ev_revenue_is_dropped_when_the_margins_do_not_compare(stub):
    """Measured live 2026-08-12: 0700.HK's peer set had a median operating
    margin of 5.7% against Tencent's 34.3%, and the 1.84x peer revenue multiple
    implied 189.61 against a 439-471 cluster from every other multiple — one
    number setting a 2.48x-wide bar, and with it the verdict."""
    stub({t: snapshot(t, operating_margin=0.05) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(operatingMargins=0.34), ["A", "B", "C"])

    assert "peer_ev_revenue" not in result["implied_values"]
    assert "peer_ev_revenue" in result["suppressed_multiples"]
    assert "34.0%" in result["suppressed_multiples"]["peer_ev_revenue"]


def test_ev_revenue_is_kept_when_the_margins_do_compare(stub):
    stub({t: snapshot(t, operating_margin=0.25) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(operatingMargins=0.30), ["A", "B", "C"])

    assert "peer_ev_revenue" in result["implied_values"]
    assert not result["suppressed_multiples"]


def test_ev_revenue_survives_when_target_and_peers_are_both_loss_making(stub):
    """EV/Sales is the conventional multiple precisely where earnings are not
    available yet — `sector_weights.pre_profit_growth` scores it for the same
    reason. The gate must not delete it there."""
    stub({t: snapshot(t, operating_margin=-0.20) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(operatingMargins=-0.15), ["A", "B", "C"])
    assert "peer_ev_revenue" in result["implied_values"]


def test_an_unknown_margin_suppresses_rather_than_assumes(stub):
    """Comparability is verified, not assumed — the same shape as the P/B
    sector gate, which includes rather than excludes."""
    stub({t: snapshot(t, operating_margin=None) for t in ("A", "B", "C")})
    result = comps.comps_analysis(target(), ["A", "B", "C"])
    assert "peer_ev_revenue" not in result["implied_values"]


def test_the_comps_bar_verdict_comes_from_the_core_not_the_envelope():
    """One outlying multiple used to set the whole width. The core carries the
    verdict; the envelope is kept beside it so the spread stays visible."""
    comps_result = {"implied_values": {"outlier": 190.0, "a": 440.0,
                                       "b": 455.0, "c": 470.0}}
    bar = next(r for r in comps.football_field(target(), {}, comps_result)
               if r["method"].startswith("Peer"))

    assert (bar["envelope_low"], bar["envelope_high"]) == (190.0, 470.0)
    assert bar["low"] > 190.0 and bar["high"] <= 470.0
    assert bar["high"] - bar["low"] < (470.0 - 190.0) * 0.8


def test_analyst_targets_need_enough_analysts_to_be_a_range():
    """Two opinions wearing the costume of a range. Same threshold the analyst
    scoring signal already uses."""
    thin = comps.football_field(
        target(targetLowPrice=80.0, targetHighPrice=140.0,
               numberOfAnalystOpinions=2), {}, {})
    assert not any(r["method"] == "Analyst targets" for r in thin)


def test_analyst_targets_are_marked_context_only():
    """Reference doc §5.2 gives them 0% weight — display, do not average."""
    row = comps.football_field(
        target(targetLowPrice=80.0, targetHighPrice=140.0,
               numberOfAnalystOpinions=20), {}, {})[0]
    assert row["context_only"] is True


def test_the_peer_count_behind_the_medians_is_reported(stub):
    """A median of one is not a median, and nothing on the chart said how many
    peers survived."""
    stub({"A": snapshot("A"), "B": snapshot("B")})
    result = comps.comps_analysis(target(), ["A", "B", "MISSING"])
    assert result["peers_used"] == 2
    assert result["failed_tickers"] == ["MISSING"]


# ── the tick cannot leave its own bar ────────────────────────────────

def test_the_midpoint_tick_stays_inside_the_bar():
    """`mid` is the model's own answer, not the band's centre, and nothing
    guaranteed it landed inside a band built from quantiles over a grid with
    dropped cells — while the chart positions the tick with no bounds check."""
    values = [None] * 12 + [float(v) for v in range(50, 63)]
    bar = next(r for r in comps.football_field(
        target(), _dcf_with_grid(values, fair_value=9_999.0), {})
        if r["method"].startswith("DCF"))
    assert bar["low"] <= bar["mid"] <= bar["high"]


def test_every_drawn_row_keeps_its_midpoint_inside_its_range():
    comps_result = {"implied_values": {"a": 90.0, "b": 100.0, "c": 130.0}}
    ranges = comps.football_field(
        target(targetLowPrice=80.0, targetHighPrice=140.0, targetMeanPrice=110.0,
               numberOfAnalystOpinions=20),
        _dcf_with_grid([float(v) for v in range(50, 75)], fair_value=61.5),
        comps_result)
    for r in ranges:
        if r.get("not_applicable"):
            continue
        assert r["low"] <= r["mid"] <= r["high"], r["method"]


# ── growth is the assumption the grid never stressed ─────────────────

def test_the_dcf_bar_widens_to_cover_the_growth_sweep():
    """The grid moves WACC and terminal growth — the second-order assumptions —
    and holds the first-order one fixed, so the band was narrow for the wrong
    reason. Measured live 2026-08-12 on 0700.HK: grid alone 606.74-778.12 and a
    confident 'price below', while growth alone reaches 502.96."""
    dcf = _dcf_with_grid([float(v) for v in range(50, 75)])
    without = next(r for r in comps.football_field(target(), dcf, {})
                   if r["method"].startswith("DCF"))

    dcf["growth_sensitivity"] = {"growth_rates": [0.0, 0.05, 0.1],
                                 "values": [20.0, 62.0, 140.0]}
    with_growth = next(r for r in comps.football_field(target(), dcf, {})
                       if r["method"].startswith("DCF"))

    assert (with_growth["low"], with_growth["high"]) == (20.0, 140.0)
    assert with_growth["high"] - with_growth["low"] > without["high"] - without["low"]
    assert "growth" in with_growth["method"]


def test_growth_sensitivity_is_absent_without_harm():
    """Callers that predate the sweep must keep the old band exactly."""
    values = [float(v) for v in range(50, 75)]
    bar = next(r for r in comps.football_field(target(), _dcf_with_grid(values), {})
               if r["method"].startswith("DCF"))
    q1, q3 = quantiles(values, n=4)[0], quantiles(values, n=4)[2]
    assert (bar["low"], bar["high"]) == (round(q1, 2), round(q3, 2))


# ── the base year is the third assumption in the bar ─────────────────
#
# Both sweeps above move a *rate*. Neither can say what the starting year being
# unrepresentative would do, and that error is undamped: fair value is
# homogeneous of degree one in base FCF, so a 30% level error is a permanent
# 30%. These pin the union — and, in the two directions below, pin that it is a
# band rather than a thumb on the scale.

def _bar(dcf):
    return next(r for r in comps.football_field(target(), dcf, {})
                if r["method"].startswith("DCF"))


def _with_normalised(dcf: dict, value) -> dict:
    dcf["diagnostics"] = {"base_year": {"fair_value_normalised": value}}
    return dcf


def test_the_dcf_bar_widens_up_to_a_normalised_base_year():
    """XOM's newest year ran at 0.711x its own four-year average FCF margin, so
    normalising raises the value: 71.75 -> 102.17 on the fixture."""
    values = [float(v) for v in range(50, 75)]
    without = _bar(_dcf_with_grid(values))
    with_base = _bar(_with_normalised(_dcf_with_grid(values), 140.0))

    assert with_base["high"] == 140.0
    assert with_base["low"] == without["low"]      # only the reached side moves
    assert "base year" in with_base["method"]


def test_the_dcf_bar_widens_down_when_the_base_year_ran_hot():
    """The direction is the argument. 0700.HK's newest year ran *above* its own
    average (1.057x), so the same rule lowers its value, 663.32 -> 628.00. A
    step that only ever raised the number would be price tuning in a band's
    clothes, and this is what stops that being true.

    Stubbed rather than taken from 0700.HK, because on that fixture 628.00 lands
    *inside* the grid band and widens nothing — the downward path is real but
    unexercised by the seven fixtures, which is exactly why it needs a test.
    """
    values = [float(v) for v in range(50, 75)]
    without = _bar(_dcf_with_grid(values))
    with_base = _bar(_with_normalised(_dcf_with_grid(values), 20.0))

    assert with_base["low"] == 20.0
    assert with_base["high"] == without["high"]
    assert "base year" in with_base["method"]


def test_a_normalised_base_inside_the_band_is_not_named():
    """The basis lists what moved the edges. A normalised figure the band
    already covers moved nothing, and naming it would imply a stress the bar
    does not carry — the same rule the growth sweep's one-sided wording follows.
    """
    values = [float(v) for v in range(50, 75)]
    without = _bar(_dcf_with_grid(values))
    inside = (without["low"] + without["high"]) / 2
    with_base = _bar(_with_normalised(_dcf_with_grid(values), inside))

    assert (with_base["low"], with_base["high"]) == (without["low"], without["high"])
    assert "base year" not in with_base["method"]


@pytest.mark.parametrize("bad", [None, 0, -12.4])
def test_a_non_positive_normalised_base_is_ignored(bad):
    """A normalised enterprise value below net debt gives a negative per-share
    figure. `price_gap_bridge` drops its step for the same reason: a bar
    stretched to -12.4 is unreadable rather than merely wide."""
    values = [float(v) for v in range(50, 75)]
    without = _bar(_dcf_with_grid(values))
    with_bad = _bar(_with_normalised(_dcf_with_grid(values), bad))

    assert (with_bad["low"], with_bad["high"]) == (without["low"], without["high"])
    assert "base year" not in with_bad["method"]


def test_the_tick_stays_on_the_reported_year_answer():
    """Union, not substitution. The band gains the normalised end; the headline
    the tick marks is still the reported-year fair value, which is the contract
    `financial_models` states where it builds the block."""
    bar = _bar(_with_normalised(
        _dcf_with_grid([float(v) for v in range(50, 75)], fair_value=61.5), 140.0))
    assert bar["mid"] == 61.5


def test_the_xom_bar_spans_both_bases_end_to_end():
    """Through the real model rather than a stub: the bar a reader sees must
    contain both the number the platform leads with and the one it shows
    beside it, or the chart and the Models tab disagree on screen."""
    dcf = fm.dcf_valuation(load_fundamentals("XOM"))
    normalised = dcf["diagnostics"]["base_year"]["fair_value_normalised"]
    bar = _bar(dcf)

    assert bar["low"] <= dcf["fair_value_per_share"] <= bar["high"]
    assert bar["low"] <= normalised <= bar["high"]


def test_widening_the_bar_does_not_move_conviction():
    """Conviction compares midpoints, and the DCF's midpoint is the model's own
    answer rather than the band's centre — so a wider bar must change the
    overlap zone and nothing else. Pinned because reading the centre instead
    would silently make every conviction grade a function of bar width."""
    values = [float(v) for v in range(50, 75)]
    peers = {"implied_values": {"peer_pe": 80.0, "peer_ev_ebitda": 90.0}}

    narrow = comps.triangulate(comps.football_field(
        target(), _dcf_with_grid(values, fair_value=61.5), peers))
    wide = comps.triangulate(comps.football_field(
        target(), _with_normalised(
            _dcf_with_grid(values, fair_value=61.5), 140.0), peers))

    assert wide["conviction"] == narrow["conviction"]
    assert wide["midpoint_spread"] == narrow["midpoint_spread"]


# ── triangulation: where the methods agree, and what to do when they don't ──

def _row(method, low, high, mid=None, **extra):
    return {"method": method, "low": low, "high": high,
            "mid": mid if mid is not None else (low + high) / 2, **extra}


def test_disjoint_methods_report_no_overlap_and_low_conviction():
    """The state the chart could not previously express. 0700.HK live
    2026-08-12: DCF 606.74-778.12 against peers 189.61-471.35, a 29% gap, shown
    as 'PRICE BELOW' beside 'IN RANGE' as though mildly different opinions."""
    t = comps.triangulate([_row("DCF", 606.74, 778.12), _row("Peer", 189.61, 471.35)])

    assert t["overlap"] is None
    assert t["conviction"] == "LOW"
    assert t["diverged"] is True
    assert t["anchors"]["low_method"] == "Peer"


def test_close_methods_report_their_overlap_and_high_conviction():
    t = comps.triangulate([_row("DCF", 90.0, 120.0), _row("Peer", 100.0, 130.0)])
    assert t["overlap"] == {"low": 100.0, "high": 120.0}
    assert t["conviction"] == "HIGH"
    assert t["diverged"] is False


def test_conviction_bands_follow_the_reference_table():
    within_30 = comps.triangulate([_row("A", 90.0, 110.0, mid=100.0),
                                   _row("B", 110.0, 140.0, mid=125.0)])
    assert within_30["conviction"] == "MEDIUM"


def test_analyst_targets_do_not_vote():
    """A target range is a forecast of the price, not a valuation of the
    business — letting it into the overlap lets the thing being tested vote on
    its own test."""
    rows = [_row("DCF", 600.0, 780.0), _row("Peer", 190.0, 470.0),
            _row("Analyst targets", 400.0, 900.0, context_only=True)]
    t = comps.triangulate(rows)
    assert "Analyst targets" not in t["methods_scored"]
    assert t["overlap"] is None  # analysts would otherwise bridge the gap


@pytest.mark.parametrize("low,high,mean,band", [
    (90.0, 110.0, 100.0, "tight"),      # 20% spread
    (80.0, 120.0, 100.0, "moderate"),   # 40%
    (50.0, 150.0, 100.0, "wide"),       # 100%
])
def test_analyst_dispersion_is_measured_not_discarded(low, high, mean, band):
    """The target range does not vote, but its width says how much informed
    forecasters disagree — an uncertainty signal the platform previously threw
    away. Measured across 20 large caps 2026-08-13 it runs 15.4% (O) to 105.7%
    (NVDA), so the bands discriminate rather than collapsing onto one value the
    way the conviction grade did."""
    row = comps.football_field(
        target(targetLowPrice=low, targetHighPrice=high, targetMeanPrice=mean,
               numberOfAnalystOpinions=30), {}, {})[0]

    assert row["dispersion"] == pytest.approx((high - low) / mean)
    assert row["dispersion_band"] == band


def test_dispersion_rides_alongside_conviction_not_inside_it():
    """Conviction measures whether the *methods* agree; dispersion whether the
    *forecasters* do. Wide dispersion with tight method agreement is a real and
    different state, and one number cannot carry both."""
    rows = comps.football_field(
        target(targetLowPrice=50.0, targetHighPrice=150.0, targetMeanPrice=100.0,
               numberOfAnalystOpinions=30),
        {}, {"implied_values": {"a": 90.0, "b": 100.0, "c": 110.0}})
    t = comps.triangulate(rows)

    assert t["analyst_dispersion_band"] == "wide"
    assert t["analysts"] == 30
    # ...and the analyst row still does not vote
    assert "Analyst targets" not in t["methods_scored"]


def test_a_single_method_is_not_a_triangulation():
    """A REIT reaches here by design: its DCF row is not applicable, leaving
    peer multiples alone. The intersection of one range is that range, which
    would render as an agreement zone nothing agreed on."""
    t = comps.triangulate([_row("Peer", 37.31, 90.25),
                           {"method": "DCF", "not_applicable": True}])
    assert t["overlap"] is None
    assert t["conviction"] is None


def test_reconciling_growth_reproduces_the_target_value(fundamentals):
    """The back-solve is the answer to 'the methods disagree, now what'. It has
    to actually invert the model, not approximate it."""
    f = fundamentals("0700_HK")
    base = fm.dcf_valuation(f)
    wanted = round(base["fair_value_per_share"] * 0.75, 2)

    g = comps.reconciling_growth(f, wanted)
    assert g is not None
    assert fm.dcf_valuation(f, growth_rate=g)["fair_value_per_share"] == \
        pytest.approx(wanted, rel=0.01)


def test_a_single_implied_value_is_flagged_not_drawn_as_a_range():
    """One multiple is an estimate, not a range. The chart has to hold the bar
    open at a minimum width to render it at all, which makes it wider than its
    own data — so the backend flags it and the bar is outlined rather than
    passing for a narrow-but-real band."""
    bar = next(r for r in comps.football_field(
        target(), {}, {"implied_values": {"only": 100.0}})
        if r["method"].startswith("Peer"))

    assert (bar["low"], bar["high"], bar["mid"]) == (100.0, 100.0, 100.0)
    assert bar["degenerate"] is True


def test_a_real_range_is_not_flagged_degenerate():
    bar = next(r for r in comps.football_field(
        target(), {}, {"implied_values": {"a": 90.0, "b": 130.0}})
        if r["method"].startswith("Peer"))
    assert "degenerate" not in bar


def test_the_thinnest_median_behind_a_plotted_multiple_is_reported(stub):
    """`peers_used` overstates support: a peer whose multiple is negative is
    dropped by the positive-only rule but still counts as resolved. Measured
    2026-08-12, 0700.HK's EV/EBITDA median rested on three of its four peers
    because 3690.HK reported -12.505."""
    stub({"A": snapshot("A"), "B": snapshot("B"),
          "C": snapshot("C", ev_to_ebitda=-12.5)})
    result = comps.comps_analysis(target(), ["A", "B", "C"])

    assert result["peers_used"] == 3
    assert result["peer_medians_n"]["ev_to_ebitda"] == 2
    assert result["peer_medians_n"]["pe_forward"] == 3

    bar = next(r for r in comps.football_field(target(), {}, result)
               if r["method"].startswith("Peer"))
    assert bar["peers_min"] == 2 and bar["peers_used"] == 3


def test_reconciling_growth_declines_when_no_rate_reaches_the_target(fundamentals):
    """Saying 'no growth rate in the model's own guardrail gets you there' is
    itself the finding; guessing one would not be."""
    f = fundamentals("0700_HK")
    assert comps.reconciling_growth(f, 1.0) is None


# ── peer suggestions ─────────────────────────────────────────────────

def test_a_curated_list_wins_over_discovery(monkeypatch):
    """FMP peers are measurably worse where a curated list exists (UPS -> HWM,
    GD, MMM, WM: generic industrials rather than freight)."""
    monkeypatch.setattr(comps, "_fmp_peers", lambda t: ["WRONG"])
    assert comps.suggest_peers("UPS") == ["FDX", "GXO", "CHRW", "EXPD"]


def test_discovery_covers_tickers_the_curated_map_does_not(monkeypatch):
    monkeypatch.setattr(comps, "_fmp_peers", lambda t: ["X", "Y"])
    assert comps.suggest_peers("NOTCURATED") == ["X", "Y"]


def test_peer_beta_inputs_skips_peers_with_no_beta(stub):
    """resolve_beta needs a beta to unlever; a snapshot without one is noise.

    MSFT's curated peers are AAPL, GOOGL, AMZN, ORCL — the target itself is never
    in its own peer set, which is why the stub below does not carry it.
    """
    stub({"AAPL": snapshot("AAPL", beta=1.1), "GOOGL": snapshot("GOOGL", beta=None),
          "AMZN": snapshot("AMZN", beta=1.3), "ORCL": snapshot("ORCL", beta=1.2)})
    out = comps.peer_beta_inputs("MSFT")
    assert [p["ticker"] for p in out] == ["AAPL", "AMZN", "ORCL"]


def test_peer_beta_inputs_survives_a_peer_that_cannot_be_fetched(stub):
    """One unreachable peer must not blank the substitution — resolve_beta still
    needs two survivors to take a median."""
    stub({"AAPL": snapshot("AAPL", beta=1.1), "AMZN": snapshot("AMZN", beta=1.3)})
    assert len(comps.peer_beta_inputs("MSFT")) == 2


# ── the price-gap bridge ─────────────────────────────────────────────
#
# Replaces a conviction grade that read LOW on every name tested. A signal that
# never varies is not a signal; these pin that the bridge does vary, and that
# its arithmetic closes.

def _bridge(stem):
    f = load_fundamentals(stem)
    dcf = fm.dcf_valuation(f)
    price = f["info"].get("currentPrice") or f["info"].get("regularMarketPrice")
    return comps.price_gap_bridge(dcf, price)


@pytest.mark.parametrize("stem", ["AAPL", "MSFT", "XOM", "0700_HK"])
def test_the_bridge_arithmetic_closes(stem):
    """Start plus every adjustment equals the adjusted value, and the residual
    is the whole of what is left. A bridge that does not add up is a fudge."""
    b = _bridge(stem)
    start = b["steps"][0]["value"]
    adjustments = sum(s["value"] for s in b["steps"] if s["kind"] == "adjustment")
    assert start + adjustments == pytest.approx(b["adjusted"], abs=0.01)
    assert b["adjusted"] + b["residual"] == pytest.approx(b["price"], abs=0.01)


def test_the_residual_is_not_always_the_same_sign():
    """The reason this replaced the conviction grade.

    0700.HK trades *below* our adjusted value while AAPL, MSFT and XOM trade
    above it. A panel that always said the same thing would be decoration.
    """
    assert _bridge("0700_HK")["residual_direction"] == "market_below"
    for stem in ("AAPL", "MSFT", "XOM"):
        assert _bridge(stem)["residual_direction"] == "market_above"


def test_no_adjustment_row_is_stubbed_at_zero():
    """An empty line implies a check was run. Rows for non-operating assets and
    for the interest-income double-count are absent because neither is computed
    yet — they must not appear as zeroes."""
    for stem in ("AAPL", "MSFT", "XOM", "0700_HK"):
        b = _bridge(stem)
        assert all(s["value"] != 0 for s in b["steps"] if s["kind"] == "adjustment")
        assert len(b["steps"]) == 2, "only the base-year step exists today"


def test_a_company_with_no_dcf_gets_no_bridge():
    """There is no gap to explain where there is no model."""
    f = load_fundamentals("JPM")
    dcf = fm.dcf_valuation(f)
    assert dcf.get("error")
    assert comps.price_gap_bridge(dcf, 100.0) is None


def test_a_missing_price_yields_no_bridge():
    assert comps.price_gap_bridge(fm.dcf_valuation(load_fundamentals("AAPL")), None) is None


# ── the comps endpoint, wired ────────────────────────────────────────
#
# comps.py is well covered and main.py's assembly of it was not, which is where
# an ordering mistake hides: the bridge measures against `current_price`, and
# that key used to be set on the last line of the endpoint, after every consumer
# of it had already run.

@pytest.fixture
def wired_endpoint(monkeypatch):
    """The comps endpoint with both providers stubbed. No network."""
    import main

    def fundamentals(ticker):
        return load_fundamentals(ticker.replace(".", "_"))

    monkeypatch.setattr(main.provider, "get_fundamentals", fundamentals)
    monkeypatch.setattr(main, "_peer_beta_inputs", lambda f: None)
    monkeypatch.setattr(comps.provider, "get_peer_snapshot",
                        lambda t: (_ for _ in ()).throw(ValueError("no peer")))
    monkeypatch.setattr(fm, "risk_free_rate", lambda fb: fm.RISK_FREE_RATE)
    return main.comps_endpoint


def test_the_endpoint_prices_the_bridge_before_returning(wired_endpoint):
    """`current_price` must exist by the time the bridge is built, not after."""
    result = wired_endpoint("AAPL", peer_list="MSFT")
    assert result["current_price"] is not None
    bridge = result["triangulation"].get("price_gap_bridge")
    assert bridge is not None, "the bridge went missing from the payload"
    assert bridge["price"] == result["current_price"], (
        "the bridge priced against something other than the payload's price")


def test_a_bank_gets_no_bridge_from_the_endpoint(wired_endpoint):
    """No DCF applies, so there is no gap to decompose — and no empty panel."""
    result = wired_endpoint("JPM", peer_list="AAPL")
    assert result["dcf_applicable"] is False
    assert "price_gap_bridge" not in result["triangulation"]
