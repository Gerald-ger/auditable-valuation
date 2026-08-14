"""Market data adapter layer.

The rest of the app only talks to `provider`. To switch to OpenBB later,
implement OpenBBProvider with the same six methods — get_quote, get_history,
get_news, get_peer_snapshot, get_fundamentals, get_filings — and swap the last
line.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from functools import wraps
from threading import Lock

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


def risk_free_rate(fallback: float) -> float:
    """US 10-year treasury yield for CAPM (reference doc 1.1.2), via OpenBB.

    Fetched at most once per calendar day. Returns `fallback` — without caching
    it — whenever OpenBB is missing or the Fed feed fails, so the DCF keeps
    working offline and starts using live rates again as soon as it can.
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
    return fallback


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
            "info": {k: _clean(info.get(k)) for k in [
                # `currency` is what the shares trade in; `financialCurrency` is
                # what the statements are reported in, and for a China-domiciled
                # HK listing they differ — 0700.HK trades in HKD and reports in
                # CNY (verified live 2026-08-10, same for 9988.HK). Without this
                # field the app cannot tell that the cash flows it discounts and
                # the price it compares them against are different units.
                "longName", "sector", "industry", "currency", "financialCurrency",
                "marketCap",
                "currentPrice", "regularMarketPrice", "sharesOutstanding", "beta",
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
            ]},
            "estimates": estimates,
            "income_statement": frame_to_dict(t.income_stmt),
            "balance_sheet": frame_to_dict(t.balance_sheet),
            "cash_flow": frame_to_dict(t.cash_flow),
        }


provider = YFinanceProvider()
