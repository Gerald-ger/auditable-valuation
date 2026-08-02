"""Market data adapter layer.

The rest of the app only talks to `provider`. To switch to OpenBB later,
implement OpenBBProvider with the same five methods — get_quote, get_history,
get_news, get_peer_snapshot, get_fundamentals — and swap the last line.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import yfinance as yf


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

    def get_peer_snapshot(self, ticker: str) -> dict:
        """Just the multiples/metrics needed for a comps table row."""
        info = yf.Ticker(ticker).info or {}
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "market_cap": _clean(info.get("marketCap")),
            "pe_trailing": _clean(info.get("trailingPE")),
            "pe_forward": _clean(info.get("forwardPE")),
            "price_to_book": _clean(info.get("priceToBook")),
            "ev_to_ebitda": _clean(info.get("enterpriseToEbitda")),
            "ev_to_revenue": _clean(info.get("enterpriseToRevenue")),
            "peg_ratio": _clean(info.get("pegRatio")),
            "operating_margin": _clean(info.get("operatingMargins")),
            "revenue_growth": _clean(info.get("revenueGrowth")),
        }

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
