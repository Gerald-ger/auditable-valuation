"""Peer comparison (trading comps) and valuation-range (football field) assembly.

Peer suggestions are curated-first: FMP peer discovery is measurably worse than
the hand-curated list where one exists (UPS -> HWM, GD, MMM, WM — generic
industrials rather than freight), but it covers HK and turns "no peers at all"
into "usually usable" for the ~everything else. Users can always edit the peer
list in the UI, so a bad suggestion is visible and correctable.
"""
from __future__ import annotations

from statistics import median, quantiles

from data_provider import provider

PEER_SUGGESTIONS = {
    # US mega-cap tech
    "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "GOOGL": ["META", "MSFT", "AMZN", "AAPL"],
    "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
    "AMZN": ["MSFT", "GOOGL", "WMT", "BABA"],
    "NVDA": ["AMD", "AVGO", "INTC", "QCOM"],
    "AMD": ["NVDA", "INTC", "QCOM", "AVGO"],
    "TSLA": ["BYDDY", "GM", "F", "RIVN"],
    "NFLX": ["DIS", "WBD", "PARA", "ROKU"],
    # US financials / consumer / health / energy
    "JPM": ["BAC", "WFC", "C", "GS"],
    "V": ["MA", "AXP", "PYPL", "FI"],
    "JNJ": ["PFE", "MRK", "ABBV", "LLY"],
    "WMT": ["TGT", "COST", "KR", "AMZN"],
    "KO": ["PEP", "KDP", "MNST", "CELH"],
    "XOM": ["CVX", "COP", "SHEL", "BP"],
    "UPS": ["FDX", "GXO", "CHRW", "EXPD"],
    "FDX": ["UPS", "GXO", "CHRW", "EXPD"],
    # HK
    "0700.HK": ["9988.HK", "3690.HK", "9999.HK", "1024.HK"],
    "9988.HK": ["0700.HK", "3690.HK", "9618.HK", "PDD"],
    "3690.HK": ["9988.HK", "0700.HK", "9618.HK", "1024.HK"],
    "0005.HK": ["2388.HK", "0011.HK", "1398.HK", "3988.HK"],
    "1299.HK": ["2318.HK", "2628.HK", "0966.HK", "PRU"],
    "0941.HK": ["0728.HK", "0762.HK", "T", "VZ"],
}

MULTIPLE_KEYS = ["pe_trailing", "pe_forward", "price_to_book",
                 "ev_to_ebitda", "ev_to_revenue", "peg_ratio"]


MAX_AUTO_PEERS = 4

_FMP_PEER_CACHE: dict[str, list[str]] = {}


def _fmp_peers(ticker: str) -> list[str]:
    """FMP peer discovery — free tier, no extra key beyond the configured one.

    Successes are cached for the process lifetime; failures are **not**, so a
    transient outage does not permanently blank a ticker's peers (same rule as
    data_provider.risk_free_rate).
    """
    if ticker in _FMP_PEER_CACHE:
        return _FMP_PEER_CACHE[ticker]
    try:
        # deferred: importing openbb costs ~5 s, so only a request that actually
        # needs discovery pays it, and only once per process
        from openbb import obb
        rows = obb.equity.compare.peers(symbol=ticker, provider="fmp").results
        peers = [r.symbol for r in rows if getattr(r, "symbol", None)][:MAX_AUTO_PEERS]
    except Exception:
        return []  # EmptyDataError for unknown tickers, plus network/quota failures
    if peers:
        _FMP_PEER_CACHE[ticker] = peers
    return peers


def suggest_peers(ticker: str) -> list[str]:
    """Curated list when we have one, FMP discovery otherwise."""
    t = ticker.upper()
    return PEER_SUGGESTIONS.get(t) or _fmp_peers(t)


def peer_beta_inputs(ticker: str) -> list[dict]:
    """Suggested peers' snapshots, for financial_models.resolve_beta.

    Returns whole snapshots rather than bare betas because resolve_beta unlevers
    each peer beta before taking the median, which needs that peer's own
    `total_debt` and `market_cap` — both already on the snapshot.

    Reads through the TTL-cached peer snapshot, so on a warm cache this costs
    nothing. Callers should only reach for this when the company's own reported
    beta is not credible — see main.py.
    """
    out = []
    for p in suggest_peers(ticker):
        try:
            snap = provider.get_peer_snapshot(p)
        except Exception:
            continue
        if snap.get("beta") is not None:
            out.append(snap)
    return out


def comps_analysis(target_fund: dict, peer_tickers: list[str]) -> dict:
    """Comps table + peer-median-implied share values for the target."""
    info = target_fund["info"]
    target_row = {
        "ticker": target_fund["ticker"],
        "name": info.get("longName"),
        "market_cap": info.get("marketCap"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "ev_to_revenue": info.get("enterpriseToRevenue"),
        "peg_ratio": info.get("pegRatio"),
        "operating_margin": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
    }

    peers, failed = [], []
    for p in peer_tickers[:8]:
        try:
            snap = provider.get_peer_snapshot(p)
            if snap["market_cap"] is None:
                failed.append(p)
            else:
                peers.append(snap)
        except Exception:
            failed.append(p)

    medians = {}
    for key in MULTIPLE_KEYS:
        vals = [p[key] for p in peers if p[key] is not None and p[key] > 0]
        medians[key] = round(median(vals), 2) if vals else None

    # apply peer-median multiples to the target's own metrics
    shares = info.get("sharesOutstanding")
    net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    implied = {}

    def ev_implied(mult, metric):
        if mult and metric and shares:
            return round((mult * metric - net_debt) / shares, 2)
        return None

    if medians.get("pe_forward") and info.get("forwardEps"):
        implied["peer_forward_pe"] = round(medians["pe_forward"] * info["forwardEps"], 2)
    if medians.get("pe_trailing") and info.get("trailingEps"):
        implied["peer_trailing_pe"] = round(medians["pe_trailing"] * info["trailingEps"], 2)
    implied["peer_ev_ebitda"] = ev_implied(medians.get("ev_to_ebitda"), info.get("ebitda"))
    implied["peer_ev_revenue"] = ev_implied(medians.get("ev_to_revenue"), info.get("totalRevenue"))
    # P/B-implied value is only meaningful for balance-sheet-driven sectors
    if info.get("sector") in ("Financial Services", "Real Estate") \
            and medians.get("price_to_book") and info.get("bookValue"):
        implied["peer_price_to_book"] = round(medians["price_to_book"] * info["bookValue"], 2)
    implied = {k: v for k, v in implied.items() if v is not None and v > 0}

    return {
        "target": target_row,
        "peers": peers,
        "failed_tickers": failed,
        "peer_medians": medians,
        "implied_values": implied,
        "implied_range": {
            "low": min(implied.values()) if implied else None,
            "high": max(implied.values()) if implied else None,
        },
    }


def football_field(target_fund: dict, dcf: dict, comps: dict) -> list[dict]:
    """Valuation ranges from each method, for the range chart."""
    info = target_fund["info"]
    ranges = []

    if dcf and not dcf.get("error"):
        # 25th-75th percentile of the sensitivity grid, per the reference doc's
        # football-field spec (§5.2), not the grid's min/max. The grid's corners
        # are the compounded worst and best case of two assumptions moved
        # together, so min/max produced a bar roughly twice as wide as the band
        # the method actually supports: measured 2026-08-07, AAPL 55.27 -> 26.73,
        # MSFT 132.95 -> 64.00, 0700.HK 330.00 -> 149.08. The width mattered —
        # 0700.HK's verdict was "in range" only because of the corners, and reads
        # "price below" against the interquartile band.
        vals = sorted(v for row in dcf["sensitivity"]["rows"]
                      for v in row["values"] if v is not None)
        if len(vals) >= 4:
            q1, q3 = quantiles(vals, n=4)[0], quantiles(vals, n=4)[2]
            ranges.append({"method": "DCF (sensitivity 25th–75th)",
                           "low": round(q1, 2), "high": round(q3, 2),
                           "mid": dcf.get("fair_value_per_share")})
        elif vals:
            ranges.append({"method": "DCF (sensitivity range)",
                           "low": min(vals), "high": max(vals),
                           "mid": dcf.get("fair_value_per_share")})

    imp = comps.get("implied_values", {})
    if imp:
        ranges.append({"method": "Peer multiples (implied)",
                       "low": min(imp.values()), "high": max(imp.values()),
                       "mid": round(median(imp.values()), 2)})

    if info.get("targetLowPrice") and info.get("targetHighPrice"):
        ranges.append({"method": "Analyst targets",
                       "low": info["targetLowPrice"], "high": info["targetHighPrice"],
                       "mid": info.get("targetMeanPrice")})

    return ranges
