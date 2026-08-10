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

import comps


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
        target(targetLowPrice=80.0, targetHighPrice=140.0, targetMeanPrice=110.0), {}, {})
    without = comps.football_field(target(targetLowPrice=80.0), {}, {})
    assert ("Analyst targets", 80.0, 140.0) == tuple(
        [with_targets[0]["method"], with_targets[0]["low"], with_targets[0]["high"]])
    assert not without


def test_peer_multiple_bar_spans_the_implied_values():
    comps_result = {"implied_values": {"a": 90.0, "b": 100.0, "c": 130.0}}
    bar = next(r for r in comps.football_field(target(), {}, comps_result)
               if r["method"].startswith("Peer"))
    assert (bar["low"], bar["mid"], bar["high"]) == (90.0, 100.0, 130.0)


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
