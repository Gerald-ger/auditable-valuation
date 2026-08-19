"""Market data adapter layer.

The rest of the app only talks to `provider`. To switch to OpenBB later,
implement OpenBBProvider with the same six methods — get_quote, get_history,
get_news, get_peer_snapshot, get_fundamentals, get_filings — and swap the last
line.
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import Lock
from urllib.request import urlopen

import yfinance as yf

# Statement-backed data changes quarterly, so a short TTL costs nothing in
# freshness and removes the repeat fetches: one scorecard page load used to call
# get_fundamentals twice for the same ticker (/api/score + /api/stock/../comps)
# plus one get_peer_snapshot per peer. Batch screening multiplies that by N.
# get_quote is deliberately NOT cached — a live tracker must stay live.
CACHE_TTL_S = 900  # 15 minutes

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = Lock()


def _ttl_cached(fn):
    """Cache a provider method keyed on its ticker *and its other arguments*.

    Callers must treat the returned structure as read-only — it is shared
    between requests for the TTL window. Nothing in the app mutates provider
    output today; keep it that way rather than paying for a deep copy per hit.

    The key used to be the ticker alone, which was fine while every cached
    method took nothing else. `get_history` takes `period` and `interval`, so on
    the old key a 5y weekly series and the chart's 1y hourly one would collide
    and whichever landed first would be served to both.
    """
    @wraps(fn)
    def wrapper(self, ticker: str, *args, **kwargs):
        key = (fn.__name__, ticker.upper(), args, tuple(sorted(kwargs.items())))
        now = time.monotonic()
        with _cache_lock:
            hit = _cache.get(key)
            if hit is not None and now - hit[0] < CACHE_TTL_S:
                return hit[1]
        value = fn(self, ticker, *args, **kwargs)
        with _cache_lock:
            _cache[key] = (now, value)
        return value

    return wrapper


def home_index(ticker: str) -> str:
    """The index a ticker's relative performance should be read against.

    One definition, three consumers: the macro news feed, the beta regression
    and the momentum pillar's relative strength. It was inlined in `get_news`
    while it had a single caller; a second copy would be the kind of drift that
    lets news say Hang Seng while scoring says S&P 500 for the same company.

    Suffix-based, like the EDGAR skip below, and it inherits the same limit —
    a US-listed ADR of a Chinese company still reads as `^GSPC`.
    """
    return "^HSI" if ticker.upper().endswith(".HK") else "^GSPC"


def cache_stats() -> dict:
    with _cache_lock:
        return {"entries": len(_cache), "ttl_seconds": CACHE_TTL_S}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# SEC filing types worth marking on a price chart, mapped to the category the
# UI filters on. Anything not listed (144, SC 13G/A, PX14A6G, ...) is dropped —
# it would bury the chart in dots that say nothing about the price.
FILING_CATEGORIES = {
    "10-K": "earnings", "10-Q": "earnings", "20-F": "earnings", "40-F": "earnings",
    "8-K": "material",
    "3": "insider", "4": "insider", "5": "insider",
}
FILINGS_LIMIT = 400  # ~5 years for a large-cap once the noise types are dropped


def _filing_title(report_type: str, row) -> str:
    if report_type in ("10-K", "20-F", "40-F"):
        return "10-K annual report"
    if report_type == "10-Q":
        period = str(getattr(row, "report_date", "") or "")[:10]
        return f"10-Q quarterly report{f' (period {period})' if period else ''}"
    if report_type == "8-K":
        items = (getattr(row, "items", "") or "").strip()
        return f"8-K material event{f' (items {items})' if items else ''}"
    return f"Form {report_type} insider transaction"


def _clean(value):
    """Replace NaN/inf with None so JSON serialization never breaks."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


_RF_CACHE: tuple[str, float] | None = None  # (date, rate) — treasury rates move once a day
_CGB_CACHE: tuple[str, float] | None = None  # (date, rate) — same, for the CGB curve

# ChinaBond (CCDC) publishes the official China Government Bond curve; the PBOC
# points at it rather than republishing. `gjqx=10` selects the 10-year tenor and
# `qxId=ycqx` the government curve, but the response still carries the
# commercial-bank and CP&Note curves beside it, so the row has to be matched by
# name and not by position.
CGB_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
CGB_CURVE = "ChinaBond Government Bond Yield Curve"
# Wide enough to clear a Chinese New Year or Golden Week closure — those run to
# nine consecutive days, and a window that lands entirely inside one returns an
# empty table indistinguishable from an outage. Measured 2026-08-19: 20 calendar
# days is 15 trading rows, 19.8 KB, 3.2 s.
CGB_WINDOW_DAYS = 20
# How old the newest published row may be before the feed counts as frozen
# rather than merely quiet. Comfortably past a nine-day holiday closure plus a
# weekend, and far short of the request window above — so a table that stops
# updating is caught rather than served as if it were today's.
CGB_MAX_STALE_DAYS = 14
# Measured 1.3-3.8 s across ~20 calls on 2026-08-19, with one outright miss in
# that run. A hard ceiling because the HKMA endpoint hung for 25 s on two
# separate attempts — a slow day has to degrade the number, never the request.
#
# 10 s is ~2.6x the worst observation rather than a generous margin, and that is
# affordable only because a failure is **not cached**: a miss degrades one
# request to the USD proxy and the next request retries. Were failures sticky
# this would need to be far longer, since the gap between the two rates is worth
# 30% of Tencent's fair value.
CGB_TIMEOUT_S = 10


def _cgb_10y() -> float | None:
    """The live China 10-year government yield, or **None**. Percent, not a ratio.

    Same contract as `_us_treasury_10y`: at most one fetch per calendar day, and
    a failure is never cached, so an outage degrades one day's number instead of
    pinning a stale one for the life of the process.

    **A range wider than a year returns HTTP 200 with an empty table** rather
    than an error, and so does a window containing no trading days. Both parse
    to `None` here, which is the same outcome as an outage and the reason the
    parse is checked rather than the status code.
    """
    global _CGB_CACHE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _CGB_CACHE and _CGB_CACHE[0] == today:
        return _CGB_CACHE[1]
    try:
        start = (datetime.now(timezone.utc)
                 - timedelta(days=CGB_WINDOW_DAYS)).strftime("%Y-%m-%d")
        url = (f"{CGB_URL}?gjqx=10&qxId=ycqx&locale=en_US"
               f"&startDate={start}&endDate={today}")
        with urlopen(url, timeout=CGB_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        rows = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [c for c in (re.sub(r"<[^>]+>", "", x).strip()
                                 for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S))
                     if c]
            if len(cells) == 3 and cells[0] == CGB_CURVE:
                rows.append((cells[1], float(cells[2])))
        # By date rather than by position: the table happens to arrive
        # newest-first, and nothing documents that it always will. Keyed on the
        # date *alone* — a bare `max(rows)` falls through to comparing yields
        # when two rows share a date, which would quietly serve the higher one,
        # and a spurious 9.99% clears the sanity band below. ISO dates make
        # lexicographic order chronological, so no parsing is needed.
        newest, rate = (max(rows, key=lambda r: r[0]) if rows else (None, None))
        # A frozen upstream table is the one failure this parse cannot see: the
        # rows are well-formed and the yield is plausible, it is simply years
        # old. Nothing else bounds it — the request window happens to be 20 days,
        # which is an accident of `CGB_WINDOW_DAYS` rather than a check.
        if newest is not None and newest < (
                datetime.now(timezone.utc) - timedelta(days=CGB_MAX_STALE_DAYS)
        ).strftime("%Y-%m-%d"):
            return None
        rate = rate / 100 if rate is not None else None
        # Same sanity band as the treasury feed, for the same reason — the page
        # quotes percent, so a switch to ratios would silently divide by 100.
        if rate is not None and 0 < rate < 0.25:
            _CGB_CACHE = (today, rate)
            return rate
    except Exception:
        pass
    return None


def _us_treasury_10y() -> float | None:
    """The live US 10-year yield, or **None** when it cannot be fetched.

    Split out of `risk_free_rate` below so that the currency branch runs for
    real under test. The offline suite pins *this* function rather than the one
    above it, which is the difference between a fixture that keeps the suite
    offline and a fixture that stubs out the very logic under test.

    Fetched at most once per calendar day. A failure is **not** cached, so a
    transient outage does not pin the fallback for the rest of the process.
    """
    global _RF_CACHE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _RF_CACHE and _RF_CACHE[0] == today:
        return _RF_CACHE[1]
    try:
        # deferred: importing openbb costs ~4s, so only a request that actually
        # runs a DCF pays it, and only once per process
        from openbb import obb
        rows = obb.fixedincome.government.treasury_rates(provider="federal_reserve").results
        rate = next(r.year_10 for r in reversed(rows) if r.year_10 is not None)
        # sanity band: a provider switching to percent units would wreck every WACC
        if 0 < rate < 0.25:
            _RF_CACHE = (today, rate)
            return rate
    except Exception:
        pass
    return None


def risk_free_rate(fallback: float,
                   currency: str | None = None,
                   sovereign_spread: float = 0.0) -> tuple[float, str]:
    """(rate, source) for the currency the discounted cash flows are in.

    Reads `financialCurrency`, the same *field* and for the same reason as
    `financial_models.equity_risk_premium_for`: a discount rate has to match the
    currency of the cash flows it discounts. Until now only the *premium* half
    of CAPM obeyed that — 0002.HK was priced off Hong Kong's 5.01% equity risk
    premium and a **United States** risk-free rate, which is not a rate in any
    market.

    All three consumers of the currency code — this, `equity_risk_premium_for`
    and `sovereign_default_spread` — match **exactly**, so an unrecognised
    spelling degrades the same way in all three rather than half-resolving in
    one. `None` means the caller did not say; it is treated as USD, which is
    what this function did before the parameter existed.

    Four sources, mirroring `equity_risk_premium_for`:
      us_treasury_10y       USD cash flows, and the Fed feed answered
      platform_default      USD cash flows, no feed — `fallback` stands in
      cgb_10y_less_spread   CNY cash flows, priced off China's own curve
      usd_proxy             a non-USD currency with no curve of its own; a US
                            rate is standing in

    `sovereign_spread` is subtracted from a **local sovereign yield only**, and
    is the caller's to supply because it comes from the same vendored table the
    caller reads the equity premium from. A government bond yield is not
    risk-free: China's 10-year contains China's own default risk, and the
    country-inclusive ERP paired with it contains that spread again. Subtracting
    once removes the double count. It is deliberately *not* applied to the US
    10-year, which is the mature-market base the whole table is built on —
    netting it there would move every USD valuation for no corresponding gain.

    A non-USD currency reports `usd_proxy` whether the US number came from the
    feed or from `fallback`. The distinction the reader needs is that no rate
    for *this* currency was used, and that is identical in both cases. **CNY
    degrades to exactly that** when ChinaBond cannot be reached, so a bad day
    returns the platform to its pre-2026-08-19 behaviour rather than to an error.
    """
    # `str(...)` because this reads straight off a vendor payload: a non-string
    # here used to be harmless and would now raise inside `_wacc`, which is a
    # fragility this change would have introduced rather than found.
    #
    # Exact match, no case folding, because the other two consumers of this same
    # currency code — `equity_risk_premium_for` and `sovereign_default_spread` —
    # are exact-match dict lookups. Folding here alone was worse than not folding
    # at all: `"cny"` took the CGB branch while the spread lookup missed and
    # returned 0.0 and the premium fell to the mature market, so the rate came
    # back as China's *raw* yield paired with a no-country premium, still
    # labelled `cgb_10y_less_spread`. An unrecognised spelling now degrades to
    # the proxy, which is what it did before the CNY branch existed.
    ccy = str(currency or "USD")
    if ccy == "CNY":
        cgb = _cgb_10y()
        # Re-checked *after* the subtraction. `_cgb_10y`'s band guards the
        # published yield; netting the sovereign spread happens out here, and a
        # low enough print nets to zero or below — 0.60% is the spread, so any
        # CGB under that does it. A negative risk-free rate then caps terminal
        # growth negative through `min(TERMINAL_GROWTH, rf)`, and the model
        # would assert perpetual *shrinkage* for a going concern with no error
        # and no flag. Out of band degrades to the proxy like any other miss.
        if cgb is not None and 0 < cgb - sovereign_spread < 0.25:
            return cgb - sovereign_spread, "cgb_10y_less_spread"
    rate = _us_treasury_10y()
    if ccy != "USD":
        return (fallback if rate is None else rate), "usd_proxy"
    if rate is None:
        return fallback, "platform_default"
    return rate, "us_treasury_10y"


_FX_CACHE: dict[tuple[str, str], tuple[str, float]] = {}  # (pair) -> (date, rate)


def fx_rate(from_ccy: str | None, to_ccy: str | None) -> float | None:
    """Units of `to_ccy` per 1 `from_ccy`, or **None** when it cannot be fetched.

    Needed because a company's statements and its shares can be denominated
    differently: measured live 2026-08-10, 0700.HK, 9988.HK and 1810.HK all
    trade in HKD and report in CNY. The cash flows a DCF discounts come from the
    statements and the price it compares them against comes from the market, so
    without this the two sides of the comparison are different units.

    Returning None rather than a constant is deliberate, and the opposite of
    `risk_free_rate` above. A stale risk-free rate moves a valuation a little; a
    wrong FX rate rescales all of it, and there is no defensible constant for a
    currency pair. Callers suppress the comparison instead of printing a number
    built on a guess.

    yfinance rather than `obb.currency`: it is already this app's data source,
    the `CNYHKD=X` pair is served on the same client we already construct, and it
    costs no second provider on the valuation path. Cached per calendar day, and
    failures are not cached, so an outage does not pin a ticker for the session.
    """
    if not from_ccy or not to_ccy:
        return None
    if from_ccy == to_ccy:
        return 1.0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (from_ccy, to_ccy)
    hit = _FX_CACHE.get(key)
    if hit and hit[0] == today:
        return hit[1]
    try:
        close = yf.Ticker(f"{from_ccy}{to_ccy}=X").history(period="5d")["Close"]
        rate = float(close.iloc[-1])
    except Exception:
        return None
    if not (math.isfinite(rate) and rate > 0):
        return None
    _FX_CACHE[key] = (today, rate)
    return rate


# ticker -> (monotonic fetch time, price, as_of epoch seconds)
_PRICE_CACHE: dict[str, tuple[float, float, float | None]] = {}
PRICE_TTL_S = 60

# What the vendor states about its own latency, forwarded rather than assumed.
# Measured on 0700.HK 2026-08-14: exchangeDataDelayedBy 15, quoteSourceName
# "Delayed Quote", and regularMarketTime exactly 15.0 minutes behind the clock.
DEFAULT_QUOTE_DELAY_MIN = 15


def live_price(ticker: str) -> tuple[float, float | None] | None:
    """(price, as_of epoch) fresher than the fundamentals cache, or None.

    `get_fundamentals` is cached for 15 minutes because statements do not change
    within a quarter, and the price rides along in the same payload. Stacked on
    the vendor's own 15-minute delay that put the valuation screen up to **30
    minutes** behind the market, while the Tracker — which calls the uncached
    `get_quote` — was half that. Only the second 15 is ours to remove.

    Cached for 60 seconds rather than not at all, which is the whole reason this
    is separate from `get_quote`: a single page view fires several endpoints at
    once (a Scorecard load hits `/score`, `/peers` and `/comps`), so an uncached
    fetch would cost three or four quote calls to answer one question. 60s is far
    inside the vendor's delay, so it costs no freshness that exists to be had.

    `get_quote` stays uncached regardless — a live tracker must stay live.

    Returns None on any failure, and the failure is deliberately not cached (same
    rule as `risk_free_rate` and `fx_rate` above). Callers keep the snapshot
    price: a quote outage should cost freshness, never the valuation.
    """
    now = time.monotonic()
    hit = _PRICE_CACHE.get(ticker.upper())
    if hit and now - hit[0] < PRICE_TTL_S:
        return hit[1], hit[2]
    try:
        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        price = float(price)
    except Exception:
        return None
    if not (math.isfinite(price) and price > 0):
        return None
    as_of = info.get("regularMarketTime")
    _PRICE_CACHE[ticker.upper()] = (now, price, as_of)
    return price, as_of


def with_fresh_price(f: dict) -> dict:
    """`f` with its price refreshed, as a copy.

    Copied rather than mutated because `get_fundamentals` output is TTL-cached
    and shared between requests — its decorator's docstring requires callers to
    treat it as read-only, and writing a price into the shared object would hand
    a later request a payload whose price and statements came from different
    fetches without anything saying so.

    **Only the price moves. `marketCap` deliberately does not.** Market cap feeds
    the WACC weights, so refreshing it would make fair value drift intraday with
    no filing having changed — a valuation that will not reproduce minute to
    minute. Leaving it also keeps every market-cap-derived multiple (P/E, P/B,
    EV/EBITDA, `fcf_yield`) mutually consistent as of one snapshot rather than
    half-refreshed. The cost is that recomputing P/E from the displayed price
    gives a marginally different answer, which is why the age is labelled.
    """
    fresh = live_price(f["ticker"])
    if fresh is None:
        return f
    price, as_of = fresh
    info = {**f["info"], "currentPrice": price, "regularMarketPrice": price}
    if as_of is not None:
        info["regularMarketTime"] = as_of
    return {**f, "info": info}


# The `info` fields `get_fundamentals` forwards to the model layer, and with that
# the contract every committed fixture has to satisfy. At module level rather
# than inline in the method so `tests/test_fixtures.py` can import it and assert
# the two agree: while this list lived inside the function body, two keys were
# added on 2026-08-14 and the fixtures captured on 2026-08-10 went on being a
# 49-key subset of a 51-key contract, with nothing able to notice.
#
# Adding a key here means recapturing the fixtures, or adding it to them as null.
# A fixture missing a field the provider forwards silently reads as "the vendor
# did not report it", which is a different test from the one you think you wrote.
INFO_KEYS = (
    # `currency` is what the shares trade in; `financialCurrency` is
    # what the statements are reported in, and for a China-domiciled
    # HK listing they differ — 0700.HK trades in HKD and reports in
    # CNY (verified live 2026-08-10, same for 9988.HK). Without this
    # field the app cannot tell that the cash flows it discounts and
    # the price it compares them against are different units.
    "longName", "sector", "industry", "currency", "financialCurrency",
    "marketCap",
    "currentPrice", "regularMarketPrice", "sharesOutstanding", "beta",
    # What the vendor says about its own latency. Forwarded so the
    # price can carry its age like every other model input carries
    # its provenance — it is the denominator of the headline upside
    # and was the only input on screen with no label at all.
    "regularMarketTime", "exchangeDataDelayedBy",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseValue",
    "enterpriseToEbitda", "enterpriseToRevenue", "pegRatio",
    "dividendYield", "payoutRatio", "returnOnEquity", "returnOnAssets",
    "profitMargins", "operatingMargins", "grossMargins", "ebitdaMargins",
    "revenueGrowth", "earningsGrowth", "totalDebt", "totalCash",
    "debtToEquity", "currentRatio", "quickRatio", "freeCashflow",
    "operatingCashflow", "totalRevenue", "ebitda", "trailingEps",
    "forwardEps", "bookValue", "targetMeanPrice", "recommendationKey",
    "numberOfAnalystOpinions", "targetLowPrice", "targetHighPrice",
    # momentum pillar inputs (scoring.py pillar M) — omitting any of
    # these drops the pillar below its 40% availability threshold
    "twoHundredDayAverage", "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
    "52WeekChange", "SandP52WeekChange",
)


class YFinanceProvider:
    def get_quote(self, ticker: str) -> dict:
        info = yf.Ticker(ticker).info or {}
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "currency": info.get("currency"),
            "exchange": info.get("fullExchangeName") or info.get("exchange"),
            "price": _clean(info.get("currentPrice") or info.get("regularMarketPrice")),
            "previous_close": _clean(info.get("previousClose")),
            "day_high": _clean(info.get("dayHigh")),
            "day_low": _clean(info.get("dayLow")),
            "market_cap": _clean(info.get("marketCap")),
            "pe_trailing": _clean(info.get("trailingPE")),
            "pe_forward": _clean(info.get("forwardPE")),
            "fifty_two_week_high": _clean(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _clean(info.get("fiftyTwoWeekLow")),
        }

    @_ttl_cached
    def get_history(self, ticker: str, period: str = "1y", interval: str = "1d") -> list[dict]:
        # Cached because the valuation path now asks for a long weekly series
        # per ticker *and* per home index, and a screening run would otherwise
        # refetch the same index bars once per name. Keyed on period and
        # interval as well, so this does not collide with the chart's requests.
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
        # intraday bars need epoch timestamps; daily+ bars use date strings
        intraday = interval.endswith(("m", "h"))
        out = []
        for ts, row in df.iterrows():
            bar = {
                "time": int(ts.timestamp()) if intraday else ts.strftime("%Y-%m-%d"),
                "open": _clean(round(float(row["Open"]), 4)),
                "high": _clean(round(float(row["High"]), 4)),
                "low": _clean(round(float(row["Low"]), 4)),
                "close": _clean(round(float(row["Close"]), 4)),
                "volume": _clean(float(row["Volume"])),
            }
            if bar["close"] is not None:
                out.append(bar)
        return out

    def get_news(self, ticker: str, limit: int = 50) -> list[dict]:
        """Company news blended with macro/policy headlines from the ticker's
        home-market index (full world-news feeds arrive with OpenBB)."""
        items = self._parse_news(yf.Ticker(ticker).news or [], "company", limit)
        macro_symbol = home_index(ticker)
        try:
            seen = {n["title"] for n in items}
            items += [n for n in self._parse_news(yf.Ticker(macro_symbol).news or [], "macro", limit)
                      if n["title"] not in seen]
        except Exception:
            pass  # macro feed is best-effort enrichment
        items.sort(key=lambda n: n["date"] or "", reverse=True)
        return items[:limit]

    @staticmethod
    def _publish_epoch(content: dict, item: dict) -> int | None:
        """Publish time as a UTC epoch, or None when the feed omits it.

        Both yfinance shapes carry a real timestamp — an ISO string or a unix
        epoch — which `date` below throws away by truncating to ten characters.
        The chart uses this to place an intraday marker on the bar the story
        actually landed in rather than on the session open.

        A naive ISO string is read as UTC: `.timestamp()` would otherwise
        interpret it in the server's local zone, which silently shifts every
        marker by the host's offset.
        """
        pub = content.get("pubDate") or content.get("displayTime")
        if pub:
            try:
                parsed = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        stamp = item.get("providerPublishTime")
        return int(stamp) if isinstance(stamp, (int, float)) else None

    @staticmethod
    def _parse_news(raw: list, category: str, limit: int) -> list[dict]:
        items = []
        for item in raw[:limit]:
            # yfinance has shipped two shapes: flat dicts and nested {'content': {...}}
            content = item.get("content", item)
            title = content.get("title")
            if not title:
                continue
            date = None
            pub = content.get("pubDate") or content.get("displayTime")
            if pub:  # ISO string
                date = str(pub)[:10]
            elif item.get("providerPublishTime"):  # unix epoch
                date = datetime.fromtimestamp(
                    item["providerPublishTime"], tz=timezone.utc
                ).strftime("%Y-%m-%d")
            url = content.get("canonicalUrl")
            if isinstance(url, dict):
                url = url.get("url")
            url = url or item.get("link")
            publisher = content.get("provider", item.get("publisher"))
            if isinstance(publisher, dict):
                publisher = publisher.get("displayName")
            items.append({
                "title": title,
                "summary": content.get("summary") or "",
                "date": date,
                # None for feeds that omit it, and absent from SEC filings
                # entirely — the chart falls back to date placement for both.
                "published_at": YFinanceProvider._publish_epoch(content, item),
                "url": url,
                "publisher": publisher,
                "category": category,
            })
        return items

    @_ttl_cached
    def get_peer_snapshot(self, ticker: str) -> dict:
        """Just the multiples/metrics needed for a comps table row."""
        info = yf.Ticker(ticker).info or {}
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "market_cap": _clean(info.get("marketCap")),
            # market_cap is in the trading currency and total_debt in the
            # reporting one, so resolve_beta needs both labels to put a peer's
            # D/E on one basis. Free — same info call.
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency"),
            # Yahoo's own classification, carried so peer *discovery* can filter
            # on the same labels the target is classified by. Free — same info
            # call, no extra request, exactly like the two fields above.
            #
            # `industry` here is Yahoo's display string ("REIT - Retail",
            # hyphen-spaced) and is NOT interchangeable with the spelling
            # yfinance's screener accepts ("REIT—Retail", em-dash):
            # EquityQuery('eq', ['industry', 'REIT - Retail']) raises ValueError
            # with the network unplugged, because the accepted spellings are a
            # literal dict in the pinned yfinance — EQUITY_SCREENER_EQ_MAP
            # ['industry'] in yfinance/const.py.
            #
            # `comps._SCREENER_INDUSTRY` translates between them, derived from
            # that dict. This note used to say the translation "needs a mapping,
            # not a character replace", which overstated the evidence: measured
            # 2026-08-19, a plain replace round-trips all 145 industries. The
            # derived lookup is used for a different reason — an industry the
            # pinned build does not know misses it and yields no peers, where a
            # replace would emit a spelling the screener rejects and look
            # identical to an empty screen.
            #
            # `sector` needs no such treatment: its 11 values are the same
            # display strings on both sides.
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            # beta rides along free on the same info call; financial_models uses
            # the peer median when a company's own reported beta is not credible
            "beta": _clean(info.get("beta")),
            # with market cap, this gives each peer's D/E, which is what lets
            # financial_models.resolve_beta unlever a peer beta before taking the
            # median and re-lever it to the target's own capital structure
            # (reference doc §1.1.2). Free — same info call, no extra request.
            "total_debt": _clean(info.get("totalDebt")),
            "pe_trailing": _clean(info.get("trailingPE")),
            "pe_forward": _clean(info.get("forwardPE")),
            "price_to_book": _clean(info.get("priceToBook")),
            "ev_to_ebitda": _clean(info.get("enterpriseToEbitda")),
            "ev_to_revenue": _clean(info.get("enterpriseToRevenue")),
            "peg_ratio": _clean(info.get("pegRatio")),
            "operating_margin": _clean(info.get("operatingMargins")),
            "revenue_growth": _clean(info.get("revenueGrowth")),
        }

    @_ttl_cached
    def get_filings(self, ticker: str) -> list[dict]:
        """Dated regulatory events from SEC EDGAR, shaped like news items.

        Why this exists: the yfinance news feed carries only ~10 recent stories
        per feed, so a 5-year chart had 2 event markers on it. SEC filings are
        free, need no key, and go back ~5 years — AAPL returns 209 distinct
        dates. They are *events*, not headlines, so they carry their own
        categories and the UI tags them separately.

        US-only: EDGAR has no CIK for HK listings, so those return [] rather
        than paying a guaranteed round-trip to fail.
        """
        if "." in ticker:  # 0700.HK and friends are not in EDGAR
            return []
        try:
            # deferred: importing openbb costs ~5 s, so only a request that
            # actually wants filings pays it, and only once per process
            from openbb import obb
            rows = obb.equity.fundamental.filings(
                symbol=ticker.upper(), provider="sec", limit=FILINGS_LIMIT).results
        except Exception:
            return []  # unknown symbol, network failure, or EDGAR rate limit

        items = []
        for r in rows:
            report_type = (getattr(r, "report_type", "") or "").upper()
            category = FILING_CATEGORIES.get(report_type)
            if category is None:
                continue  # 144, SC 13G/A, PX14A6G ... noise for a price chart
            date = str(getattr(r, "filing_date", "") or "")[:10]
            if not date:
                continue
            items.append({
                "title": _filing_title(report_type, r),
                "summary": "",
                "date": date,
                "url": getattr(r, "filing_detail_url", None)
                       or getattr(r, "report_url", None),
                "publisher": "SEC EDGAR",
                "category": category,
            })
        return items

    @_ttl_cached
    def get_fundamentals(self, ticker: str) -> dict:
        """Raw statement data + key info fields the model layer needs."""
        t = yf.Ticker(ticker)
        info = t.info or {}

        estimates = {"revenue_growth_fwd": None, "earnings_growth_fwd": None}
        try:
            rev_est = t.revenue_estimate
            if rev_est is not None and "+1y" in rev_est.index:
                estimates["revenue_growth_fwd"] = _clean(float(rev_est.loc["+1y", "growth"]))
            gr = t.growth_estimates
            if gr is not None and "+1y" in gr.index:
                estimates["earnings_growth_fwd"] = _clean(float(gr.loc["+1y", "stockTrend"]))
        except Exception:
            pass  # estimates are optional enrichment

        def frame_to_dict(df):
            if df is None or df.empty:
                return {}
            out = {}
            for col in df.columns:  # columns are period-end timestamps
                key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                out[key] = {
                    str(idx): _clean(float(v)) if isinstance(v, (int, float)) else None
                    for idx, v in df[col].items()
                }
            return out

        return {
            "ticker": ticker.upper(),
            "info": {k: _clean(info.get(k)) for k in INFO_KEYS},
            "estimates": estimates,
            "income_statement": frame_to_dict(t.income_stmt),
            "balance_sheet": frame_to_dict(t.balance_sheet),
            "cash_flow": frame_to_dict(t.cash_flow),
        }


provider = YFinanceProvider()
