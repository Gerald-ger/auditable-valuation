"""Ticker search ranking/typo tolerance, and the period->interval contract.

Offline: the local index is stubbed and the remote tier is monkeypatched, so
these assert *our* ranking and fallback rules rather than Yahoo's uptime. The
live behaviour they encode was measured 2026-08-07 and is recorded in each test.
"""
from __future__ import annotations

import asyncio
import unittest.mock as mock

import pytest

from conftest import load_fundamentals

from backend import data_provider
from backend import financial_models as fm
from backend import main
from backend import search


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


# Yahoo's own list, read off the error it returns for a tenor it does not serve:
# "Invalid input - interval=3h is not supported. Valid intervals: [...]"
# (measured 2026-08-19). Kept as a set rather than probed live because the whole
# point is that it runs offline, next to the table it guards.
YAHOO_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "4h",
                   "1d", "5d", "1wk", "1mo", "3mo"}


def test_every_interval_is_one_yahoo_actually_serves():
    """An interval Yahoo does not publish is invisible, not loud.

    It returns HTTP 200 with zero bars, `history` below falls back to daily, and
    the chart renders perfectly — at a bar size nobody chose. `3h` and `3d` both
    look like reasonable steps in this table and neither exists; they were asked
    for on 2026-08-19 and only the live probe said so.
    """
    unserved = {p: i for p, i in main.PERIOD_INTERVALS.items()
                if i not in YAHOO_INTERVALS}
    assert not unserved, f"Yahoo does not serve: {unserved}"


@pytest.mark.parametrize("period", ["6mo", "1y", "2y"])
def test_the_mid_ranges_are_daily_so_the_indicators_mean_days(period):
    """MA20/MA50, RSI(14) and MACD(12,26,9) are daily-line conventions, and the
    chart counts bars rather than time. These three ranges were hourly until
    2026-08-19, which made RSI(14) a fourteen-*hour* RSI wearing a daily name.

    Pinned as an equality on all three together: the value is that they agree,
    so a reader comparing MA50 across 6mo, 1y and 2y is comparing one indicator.
    """
    assert main.PERIOD_INTERVALS[period] == "1d"


@pytest.mark.parametrize("period", ["5y", "max"])
def test_long_periods_stay_daily_or_coarser(period):
    """Yahoo serves hourly data for the last 730 days only — measured, 5y at
    1h returns ZERO bars. No UI choice can make these finer.

    The upper bound matters too, and it is why `max` is not monthly: Yahoo caps
    a monthly response at **500 bars**, measured 2026-08-19, which starts XOM in
    1985 rather than 1962 and RIVN with 58 bars in total. Excluding `1mo` here
    is therefore load-bearing rather than incidental — a `max` button that shows
    23 fewer years than the weekly one contradicts its own label, and it does it
    silently, since 500 bars is a successful response.
    """
    assert main.PERIOD_INTERVALS[period] in ("1d", "1wk")


def test_no_period_requests_sub_hourly_beyond_60_days():
    """Sub-hourly data is capped at 60 days; 3mo at 30m returned zero bars."""
    sub_hourly = {"1m", "2m", "5m", "15m", "30m", "90m"}
    for period in ("3mo", "6mo", "1y", "2y", "5y", "max"):
        assert main.PERIOD_INTERVALS[period] not in sub_hourly


# ── lead-in bars ─────────────────────────────────────────────────────
#
# Every test here stubs `provider.get_history`, so what is asserted is the
# trimming and the failure policy rather than Yahoo's uptime.


def _stub_history(monkeypatch, series: dict[str, list]):
    """`provider.get_history` answering from a {period: bars} table."""
    def fake(ticker, period="1y", interval="1d"):
        return series[period]
    monkeypatch.setattr(main.provider, "get_history", fake)


def _daily(start: int, count: int) -> list[dict]:
    """`count` bars whose times sort in the order they were generated."""
    return [{"time": f"{2000 + (start + i) // 12:04d}-{(start + i) % 12 + 1:02d}-01",
             "close": 1.0} for i in range(count)]


def test_the_lead_in_is_the_bars_immediately_before_the_window(monkeypatch):
    """Contiguous and non-overlapping: the last N of the source that predate the
    window, not the first N of the source and not any bar the window repeats."""
    window = _daily(200, 30)
    _stub_history(monkeypatch, {"6mo": window, "1y": _daily(0, 230)})

    out = main.history("X", period="6mo", interval="1d")

    assert out["warmup_bars"] == main.WARMUP_BARS
    lead, shown = out["bars"][:main.WARMUP_BARS], out["bars"][main.WARMUP_BARS:]
    assert shown == window, "the requested window must survive intact"
    assert lead == _daily(150, 50), "must be the 50 bars ending where the window starts"
    assert [b["time"] for b in out["bars"]] == sorted(b["time"] for b in out["bars"])


def test_a_lead_in_failure_costs_the_left_edge_and_not_the_chart(monkeypatch):
    """The reason `_lead_in` does not use `_guard`.

    `_guard` turns any provider exception into a 502, which is right for the
    bars a chart cannot be drawn without and wrong for these. A lead-in outage
    must return the chart the app had before this feature existed.
    """
    window = _daily(200, 30)

    def fake(ticker, period="1y", interval="1d"):
        if period == "1y":
            raise RuntimeError("Yahoo said no")
        return window

    monkeypatch.setattr(main.provider, "get_history", fake)

    out = main.history("X", period="6mo", interval="1d")
    assert out["warmup_bars"] == 0
    assert out["bars"] == window


def test_a_company_younger_than_the_window_gets_what_lead_in_exists(monkeypatch):
    """Partial rather than none, and none rather than an error.

    RIVN's 5y and its max are the same 250 weekly bars, so it has no run-up at
    all; a name with three bars of it should still get the three.
    """
    window = _daily(200, 30)
    _stub_history(monkeypatch, {"6mo": window, "1y": _daily(197, 33)})

    out = main.history("X", period="6mo", interval="1d")
    assert out["warmup_bars"] == 3
    assert out["bars"] == _daily(197, 3) + window


@pytest.mark.parametrize("period", ["1d", "5d", "max"])
def test_the_ranges_that_deliberately_get_no_lead_in(period):
    """Absence here is a decision, not a gap — see the comment on WARMUP_SOURCE.

    `1d` and `5d` would need a 4-5x fetch against Yahoo's most rate-limited
    endpoints to buy the last 13% of a chart that already carries MA50 across
    87% of itself. `max` has no bar before its first one.
    """
    assert period not in main.WARMUP_SOURCE


def test_every_lead_in_source_is_a_longer_period():
    """A source no longer than what it feeds supplies no earlier bar at all, so
    the lead-in would be silently empty and MA50 would go back to starting a
    third of the way in — with nothing failing."""
    order = list(main.PERIOD_INTERVALS)
    for period, source in main.WARMUP_SOURCE.items():
        assert order.index(source) > order.index(period), f"{source} !> {period}"


# Roughly how far back each period reaches, for the limit check below only.
PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
               "1y": 365, "2y": 730, "5y": 1825, "max": 10**6}


def test_no_lead_in_asks_yahoo_for_a_span_it_will_not_serve():
    """The lead-in is fetched at the **display** interval, not at the source
    period's own one — `1mo` is served at 1h and its lead-in is `3mo` at 1h,
    where `PERIOD_INTERVALS["3mo"]` is 4h and irrelevant. (An earlier draft of
    this test asserted the two intervals matched. They do not need to, the code
    never claimed they did, and the assertion failed on the first run.)

    What does bind is Yahoo's own window per bar size, which the source period
    can walk past even when the display period does not: `2y` at 1h would be
    legal to display and its `5y` lead-in would return **zero** bars, giving a
    silently empty run-up rather than an error.
    """
    for period, source in main.WARMUP_SOURCE.items():
        interval, days = main.PERIOD_INTERVALS[period], PERIOD_DAYS[source]
        if interval in {"1m", "2m", "5m", "15m", "30m", "90m"}:
            assert days <= 60, f"{period}: {source} at {interval} exceeds 60 days"
        elif interval in {"1h", "60m", "4h"}:
            assert days <= 730, f"{period}: {source} at {interval} exceeds 730 days"


def test_the_lead_in_covers_every_window_the_chart_draws():
    """50 is MA50 and `smaSeries` emits from index `period - 1`, so exactly 50
    leading bars put the longest line on the first displayed bar. The other
    three ride along: SD band 20, RSI(14) 15, MACD signal 34 (26 - 1, then 9)."""
    assert main.WARMUP_BARS >= 50


# ── bars per day (drives indicator window scaling) ───────────────────

def test_bars_per_day_counts_a_full_session():
    """Median bars per trading day, ignoring partial sessions at either end.

    This docstring said until 2026-08-19 that *"the chart scales MA/RSI/MACD
    windows with this, so an off-by-one here silently changes what every
    indicator measures"*. It does not — nothing consumes `bars_per_day`; see the
    corrected note on `main._bars_per_day`. The figure is still served and still
    worth pinning, but an off-by-one changes a payload field, not a chart.
    """
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


# ── price freshness ──────────────────────────────────────────────────
#
# The statements are cached for fifteen minutes because they change quarterly;
# the price rode along in the same payload and does not have that luxury. Stacked
# on the vendor's own fifteen-minute delay, the valuation screen ran up to half an
# hour behind the market. Only our half is removable, and these pin how.

def test_refreshing_the_price_does_not_touch_the_cached_payload():
    """The one change here that could corrupt shared state. `get_fundamentals`
    output is TTL-cached and handed to every request in the window, so writing a
    price into it would give a later caller statements and a price from different
    fetches with nothing saying so."""
    original = load_fundamentals("AAPL")
    snapshot = original["info"]["currentPrice"]

    with mock.patch.object(data_provider, "live_price", lambda t: (snapshot * 2, 1234)):
        out = data_provider.with_fresh_price(original)

    assert out["info"]["currentPrice"] == snapshot * 2      # the copy moved
    assert original["info"]["currentPrice"] == snapshot     # the original did not
    assert out["info"] is not original["info"]              # and it is a real copy


def test_a_quote_outage_keeps_the_snapshot_price():
    """Freshness is worth a network call; a valuation is not worth losing to one.
    Same rule as `risk_free_rate` and `fx_rate` — degrade the number, never the
    endpoint."""
    f = load_fundamentals("AAPL")
    with mock.patch.object(data_provider, "live_price", lambda t: None):
        out = data_provider.with_fresh_price(f)
    assert out is f


def test_a_fresher_price_moves_the_upside_but_never_the_fair_value():
    """Pins the market-cap decision. Only the price is refreshed, deliberately:
    market cap feeds the WACC weights, so refreshing it too would make fair value
    drift intraday with no filing having changed — a valuation that will not
    reproduce minute to minute."""
    low, high = load_fundamentals("AAPL"), load_fundamentals("AAPL")
    low["info"]["currentPrice"] = 100.0
    high["info"]["currentPrice"] = 200.0

    a, b = fm.dcf_valuation(low), fm.dcf_valuation(high)
    assert a["fair_value_per_share"] == b["fair_value_per_share"]
    assert a["upside_pct"] != b["upside_pct"]
    assert a["assumptions"]["wacc"] == b["assumptions"]["wacc"]


def test_the_price_carries_its_own_provenance():
    """It is the denominator of the headline upside and was the only input on the
    screen with no label. Both figures are the vendor's, not estimates."""
    f = load_fundamentals("AAPL")
    f["info"]["regularMarketTime"] = 1_755_000_000
    f["info"]["exchangeDataDelayedBy"] = 15

    a = fm.dcf_valuation(f)["assumptions"]
    assert a["price_as_of"] == 1_755_000_000
    assert a["price_delayed_by_minutes"] == 15


def test_the_price_cache_holds_for_its_window_and_does_not_cache_failures():
    """60 seconds, not uncached: one page view fires several endpoints at once, so
    an uncached fetch would cost three or four quote calls to answer one question.
    A failure must not pin the ticker for that window."""
    data_provider._PRICE_CACHE.clear()
    calls = []

    class Stub:
        def __init__(self, ticker):
            calls.append(ticker)

        @property
        def info(self):
            return {"currentPrice": 123.0, "regularMarketTime": 99}

    with mock.patch.object(data_provider.yf, "Ticker", Stub):
        assert data_provider.live_price("AAPL") == (123.0, 99)
        assert data_provider.live_price("AAPL") == (123.0, 99)
    assert len(calls) == 1, "second call inside the window must be served from cache"

    data_provider._PRICE_CACHE.clear()
    failures = []

    class Boom:
        def __init__(self, ticker):
            failures.append(ticker)

        @property
        def info(self):
            raise RuntimeError("quote feed down")

    with mock.patch.object(data_provider.yf, "Ticker", Boom):
        assert data_provider.live_price("AAPL") is None
        assert data_provider.live_price("AAPL") is None
    assert len(failures) == 2, "a failure must not be cached"


def test_the_batch_screener_keeps_the_snapshot_price():
    """A fifteen-minute-old quote cannot reorder a ranking, and a fetch per ticker
    would roughly double the network work of a fifty-name run."""
    with mock.patch.object(main.provider, "get_fundamentals",
                           lambda t: load_fundamentals("AAPL")) as _, \
         mock.patch.object(main, "with_fresh_price") as refresh:
        main._fundamentals("AAPL", fresh_price=False)
        refresh.assert_not_called()
        main._fundamentals("AAPL")
        refresh.assert_called_once()
