"""Ticker search ranking/typo tolerance, and the period->interval contract.

Offline: the local index is stubbed and the remote tier is monkeypatched, so
these assert *our* ranking and fallback rules rather than Yahoo's uptime. The
live behaviour they encode was measured 2026-08-07 and is recorded in each test.
"""
from __future__ import annotations

import asyncio

import pytest

import data_provider
import main
import search


@pytest.fixture(autouse=True)
def clean_search_state(monkeypatch):
    """Every test gets its own index, buckets and remote cache."""
    monkeypatch.setattr(search, "_index", None)
    monkeypatch.setattr(search, "_buckets", {})
    monkeypatch.setattr(search, "_remote_cache", {})
    yield


def _stub_index(monkeypatch, rows):
    monkeypatch.setattr(search, "load_index", lambda force=False: rows)


def _stub_remote(monkeypatch, rows):
    monkeypatch.setattr(search, "_yahoo_matches",
                        lambda q, limit: [(search.SCORE_YAHOO_TOP - i * 10, r)
                                          for i, r in enumerate(rows[:limit])])


US = [
    {"symbol": "AAPL", "name": "Apple Inc."},
    {"symbol": "MSFT", "name": "MICROSOFT CORP"},
    {"symbol": "TSLA", "name": "Tesla, Inc."},
    {"symbol": "TME", "name": "Tencent Music Entertainment Group"},
    {"symbol": "APLE", "name": "Apple Hospitality REIT, Inc."},
]


# ── typo tolerance: the reason the local index exists ────────────────

@pytest.mark.parametrize("typo,expected", [
    ("microsft", "MSFT"),
    ("teslla", "TSLA"),
    ("appl", "AAPL"),
])
def test_typos_still_find_the_company(monkeypatch, typo, expected):
    """Yahoo returns nothing for these without its fuzzy flag (measured), so
    local fuzzy matching is what stops a slip showing an empty chart."""
    _stub_index(monkeypatch, US)
    _stub_remote(monkeypatch, [])
    assert search.search_tickers(typo, 5)[0]["symbol"] == expected


def test_unrelated_text_matches_nothing():
    """Fuzzy must not degrade into 'always return something'."""
    assert search.search_tickers("zzzzqqqq", 5) == []


# ── ranking ──────────────────────────────────────────────────────────

def test_exact_symbol_outranks_every_name_match(monkeypatch):
    """Typing a known symbol must never be reordered by a remote guess."""
    _stub_index(monkeypatch, US)
    _stub_remote(monkeypatch, [{"symbol": "AAPL34.SA", "name": "APPLE DRN",
                                "source": "yahoo"}])
    assert search.search_tickers("AAPL", 5)[0]["symbol"] == "AAPL"


def test_remote_hit_outranks_a_local_name_prefix(monkeypatch):
    """The measured failure this ordering fixes: the index is US-only, so
    "tencent" matched Tencent *Music* while the wanted 0700.HK sat below it."""
    _stub_index(monkeypatch, US)
    _stub_remote(monkeypatch, [{"symbol": "0700.HK", "name": "TENCENT",
                                "exchange": "Hong Kong", "source": "yahoo"}])
    results = search.search_tickers("tencent", 5)
    assert results[0]["symbol"] == "0700.HK"
    assert "TME" in [r["symbol"] for r in results], "the local match still appears"


def test_duplicate_symbols_are_collapsed(monkeypatch):
    _stub_index(monkeypatch, US)
    _stub_remote(monkeypatch, [{"symbol": "AAPL", "name": "Apple Inc.", "source": "yahoo"}])
    symbols = [r["symbol"] for r in search.search_tickers("AAPL", 8)]
    assert symbols.count("AAPL") == 1


def test_blank_query_returns_nothing():
    assert search.search_tickers("", 5) == []
    assert search.search_tickers("   ", 5) == []


# ── degradation ──────────────────────────────────────────────────────

def test_remote_failure_leaves_local_results_standing(monkeypatch):
    """Offline or rate-limited, the box must still resolve US symbols."""
    _stub_index(monkeypatch, US)

    def boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr("yfinance.Search", boom)
    assert search.search_tickers("AAPL", 5)[0]["symbol"] == "AAPL"


def test_missing_index_still_serves_remote_results(monkeypatch):
    """No SEC cache and no network for it: HK lookups must keep working."""
    _stub_index(monkeypatch, [])
    _stub_remote(monkeypatch, [{"symbol": "0700.HK", "name": "TENCENT", "source": "yahoo"}])
    assert search.search_tickers("tencent", 5)[0]["symbol"] == "0700.HK"


# ── period -> interval contract ──────────────────────────────────────

def test_every_offered_period_has_an_interval():
    """The UI's period buttons and the backend's interval map must not drift."""
    ui_periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
    for period in ui_periods:
        assert period in main.PERIOD_INTERVALS, f"{period} has no interval mapping"


@pytest.mark.parametrize("period,interval", [("1d", "1m"), ("5d", "5m")])
def test_requested_intraday_intervals(period, interval):
    assert main.PERIOD_INTERVALS[period] == interval


@pytest.mark.parametrize("period", ["5y", "max"])
def test_long_periods_stay_daily_or_coarser(period):
    """Yahoo serves hourly data for the last 730 days only — measured, 5y at
    1h returns ZERO bars. No UI choice can make these finer."""
    assert main.PERIOD_INTERVALS[period] in ("1d", "1wk")


def test_no_period_requests_sub_hourly_beyond_60_days():
    """Sub-hourly data is capped at 60 days; 3mo at 30m returned zero bars."""
    sub_hourly = {"1m", "2m", "5m", "15m", "30m", "90m"}
    for period in ("3mo", "6mo", "1y", "2y", "5y", "max"):
        assert main.PERIOD_INTERVALS[period] not in sub_hourly


# ── bars per day (drives indicator window scaling) ───────────────────

def test_bars_per_day_counts_a_full_session():
    """The chart scales MA/RSI/MACD windows with this, so an off-by-one here
    silently changes what every indicator measures."""
    bars = [{"time": f"2026-08-{day:02d}"} for day in range(3, 9) for _ in range(7)]
    assert main._bars_per_day(bars) == 7.0


def test_bars_per_day_ignores_partial_first_and_last_days():
    """Today's session is usually incomplete and would drag the median down."""
    bars = ([{"time": "2026-08-03"}] * 2 + [{"time": "2026-08-04"}] * 7
            + [{"time": "2026-08-05"}] * 7 + [{"time": "2026-08-06"}] * 7
            + [{"time": "2026-08-07"}] * 1)
    assert main._bars_per_day(bars) == 7.0


def test_bars_per_day_is_one_for_daily_bars():
    bars = [{"time": f"2026-08-{d:02d}"} for d in range(1, 12)]
    assert main._bars_per_day(bars) == 1.0


def test_bars_per_day_handles_epoch_intraday_times():
    """Intraday bars carry epoch ints, daily bars carry date strings."""
    day = 1_786_000_000
    bars = [{"time": day + hour * 3600} for hour in range(0, 20)]
    assert main._bars_per_day(bars) >= 1.0


def test_bars_per_day_never_returns_zero():
    """It is a divisor in the frontend; zero would produce Infinity windows."""
    assert main._bars_per_day([]) == 1.0
    assert main._bars_per_day([{"time": "2026-08-07"}]) >= 1.0


# ── news publish timestamps (chart marker placement) ─────────────────

def _epoch(content, item=None):
    return data_provider.YFinanceProvider._publish_epoch(content, item or {})


def test_iso_publish_time_becomes_an_epoch():
    assert _epoch({"pubDate": "2026-08-06T14:05:00Z"}) == 1786025100


def test_naive_iso_is_read_as_utc_not_server_local():
    """.timestamp() on a naive datetime uses the host's zone, which would shift
    every marker by the server's offset — 8 hours on the dev machine."""
    assert _epoch({"pubDate": "2026-08-06T14:05:00"}) == _epoch({"pubDate": "2026-08-06T14:05:00Z"})


def test_offset_iso_is_normalised_to_utc():
    assert _epoch({"pubDate": "2026-08-06T10:05:00-04:00"}) == _epoch({"pubDate": "2026-08-06T14:05:00Z"})


def test_legacy_epoch_shape_is_carried_through():
    assert _epoch({}, {"providerPublishTime": 1786025100}) == 1786025100


def test_missing_publish_time_is_none():
    assert _epoch({}, {}) is None


def test_unparseable_publish_time_is_none_rather_than_raising():
    """A feed change must degrade to date placement, not 500 the events call."""
    assert _epoch({"pubDate": "last Tuesday"}) is None


def test_parsed_news_items_carry_published_at():
    raw = [{"content": {"title": "T", "pubDate": "2026-08-06T14:05:00Z"}}]
    item = data_provider.YFinanceProvider._parse_news(raw, "company", 10)[0]
    assert item["published_at"] == 1786025100
    assert item["date"] == "2026-08-06"  # unchanged, still the fallback


# ── the stale-backend guard ──────────────────────────────────────────
#
# A backend running older code than the folder is this project's most repeated
# self-inflicted wound, and its symptom is silence: a field added after the
# server booted is simply absent, the panel reading it renders nothing, and that
# is indistinguishable from a feature never built. `/api/health` now reports it.

def test_the_source_fingerprint_ignores_line_endings(tmp_path, monkeypatch):
    """The subtle half. A byte hash looked right and was wrong on Windows:
    measured 2026-08-14, `git checkout` restored `sector_weights.py` with 252
    CRLF where the running process had loaded LF, so the guard reported a stale
    server for a file git itself called unmodified. A banner nobody can clear is
    a banner people learn to ignore, so the hash reads text, not bytes.
    """
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for d in (lf, crlf):
        d.mkdir()
    (lf / "a.py").write_bytes(b"x = 1\ny = 2\n")
    (crlf / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")

    def fingerprint_of(directory):
        monkeypatch.setattr(main, "__file__", str(directory / "main.py"))
        return main._source_fingerprint()

    assert fingerprint_of(lf) == fingerprint_of(crlf)


def test_the_source_fingerprint_changes_when_the_source_does(tmp_path, monkeypatch):
    """The other half: it must still catch a real edit, or it is decoration."""
    d = tmp_path / "src"
    d.mkdir()
    monkeypatch.setattr(main, "__file__", str(d / "main.py"))

    (d / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = main._source_fingerprint()
    (d / "a.py").write_text("x = 2\n", encoding="utf-8")

    assert main._source_fingerprint() != before


def test_health_reports_whether_the_source_moved():
    """Fresh by construction inside the suite — the fingerprint is captured at
    import, and the suite does not rewrite the backend while running."""
    body = asyncio.run(main.health())
    assert body["status"] == "ok"
    assert body["source_changed_since_start"] is False
