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

_cache: dict[tuple[str, str], tuple[float, object]] = {}
_cache_lock = Lock()


def _ttl_cached(fn):
    """Cache a provider method keyed on its ticker argument.

    Callers must treat the returned structure as read-only — it is shared
    between requests for the TTL window. Nothing in the app mutates provider
    output today; keep it that way rather than paying for a deep copy per hit.
    """
    @wraps(fn)
    def wrapper(self, ticker: str, *args, **kwargs):
        key = (fn.__name__, ticker.upper())
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

    def get_history(self, ticker: str, period: str = "1y", interval: str = "1d") -> list[dict]:
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
        macro_symbol = "^HSI" if ticker.upper().endswith(".HK") else "^GSPC"
        try:
            seen = {n["title"] for n in items}
            items += [n for n in self._parse_news(yf.Ticker(macro_symbol).news or [], "macro", limit)
                      if n["title"] not in seen]
        except Exception:
            pass  # macro feed is best-effort enrichment
        items.sort(key=lambda n: n["date"] or "", reverse=True)
        return items[:limit]

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
                "longName", "sector", "industry", "currency", "marketCap",
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
