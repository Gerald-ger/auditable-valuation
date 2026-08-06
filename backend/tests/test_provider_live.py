"""Live provider contract tests — deselected by default (`-m network`).

yfinance is an unofficial scraper with no API contract: it has already shipped
two different news payload shapes, and the whole site sits on a single provider.
These tests exist to tell you the shape changed *before* the UI does.

    backend\\.venv\\Scripts\\python.exe -m pytest -m network
"""
from __future__ import annotations

import pytest

import financial_models as fm
from data_provider import provider

pytestmark = pytest.mark.network

REQUIRED_INFO_FIELDS = [
    "marketCap", "currentPrice", "sharesOutstanding",
    # momentum pillar inputs — losing any of these drops the pillar below its
    # 40% availability threshold and silently changes every composite
    "twoHundredDayAverage", "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
    "52WeekChange", "SandP52WeekChange",
]


def test_quote_shape():
    q = provider.get_quote("AAPL")
    assert q["price"] is not None
    assert q["currency"] == "USD"


def test_fundamentals_still_carry_the_fields_scoring_depends_on():
    f = provider.get_fundamentals("AAPL")
    missing = [k for k in REQUIRED_INFO_FIELDS if f["info"].get(k) is None]
    assert not missing, f"yfinance stopped supplying: {missing}"


def test_cash_flow_statement_still_has_both_fcf_legs():
    """The DCF and both FCF scoring metrics depend on this path existing."""
    f = provider.get_fundamentals("AAPL")
    statement = fm._statement_fcf(f["cash_flow"])
    assert statement is not None
    period, fcf = statement
    assert fcf > 0
    # fcf_conversion is dropped unless net income exists for the SAME period
    assert fm._value_at(f["income_statement"], period,
                        "Net Income", "Net Income Common Stockholders") is not None


def test_peer_snapshot_carries_beta():
    """resolve_beta falls back to the peer median; without this field it can't."""
    snap = provider.get_peer_snapshot("MSFT")
    assert snap["beta"] is not None


def test_news_parses_into_the_expected_shape():
    items = provider.get_news("AAPL")
    assert items, "news feed returned nothing"
    assert {"title", "date", "url", "category"} <= set(items[0])
    assert {i["category"] for i in items} <= {"company", "macro"}


def test_filings_give_the_chart_something_to_mark():
    """The yfinance news feed carries ~3 distinct dates; the whole point of the
    SEC source is that a multi-year chart has more than two markers on it."""
    filings = provider.get_filings("AAPL")
    assert len(filings) > 50
    dates = {f["date"] for f in filings}
    assert len(dates) > 25, f"only {len(dates)} distinct dates"
    assert {"title", "date", "url", "category"} <= set(filings[0])
    assert {f["category"] for f in filings} <= {"earnings", "material", "insider"}
    assert all(f["url"] for f in filings), "a marker with no link is not clickable"


def test_filings_are_skipped_for_non_us_listings():
    """EDGAR has no CIK for HK tickers — this must cost nothing, not raise."""
    assert provider.get_filings("0700.HK") == []


def test_history_returns_ordered_bars():
    bars = provider.get_history("AAPL", "1mo", "1d")
    assert len(bars) > 5
    assert [b["time"] for b in bars] == sorted(b["time"] for b in bars)
