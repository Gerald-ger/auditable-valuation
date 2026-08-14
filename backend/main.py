"""FastAPI backend for the stock analysis platform.

Run:  backend\\.venv\\Scripts\\python.exe -m uvicorn main:app --app-dir backend --port 8000
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from statistics import median
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ai_client
import comps
import drawings as drawings_model
import financial_models
import forensics
import scoring
import search
import sector_weights
import store
from data_provider import home_index, provider

# yfinance is IO-bound but throttles bursts, so batch work fans out narrowly
# rather than one thread per ticker.
BATCH_WORKERS = 4
MAX_BATCH_TICKERS = 50

# The window behind the computed beta and relative strength. Weekly rather than
# daily is the conventional beta sampling, and five years is the upper end of
# the conventional two-to-five — long enough that one unusual quarter cannot set
# the slope, short enough that the company is still recognisably itself.
BETA_PERIOD, BETA_INTERVAL = "5y", "1wk"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    yield


app = FastAPI(title="Stock Analysis Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # yfinance raises assorted exceptions for bad tickers
        raise HTTPException(status_code=502, detail=f"Data provider error: {e}")


async def _aguard(fn, *args, **kwargs):
    """_guard for async endpoints: the blocking call must leave the event loop."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data provider error: {e}")


def _peer_beta_inputs(f: dict) -> list[dict] | None:
    """Peer snapshots, but only when the company's own reported beta is not credible.

    resolve_beta prefers a plausible reported beta, so fetching peers otherwise
    would be pure waste — and this is the only network call the valuation path
    makes beyond the fundamentals themselves. yfinance returned 0.173 for XOM,
    which alone moved its DCF upside by ~79 points, so the rare fetch is worth it.
    """
    beta = f["info"].get("beta")
    if beta is not None and financial_models.BETA_MIN <= beta <= financial_models.BETA_MAX:
        return None
    return comps.peer_beta_inputs(f["ticker"])


def _market_bars(ticker: str) -> tuple[list[dict], list[dict]] | None:
    """(company weekly closes, home-index weekly closes) for the beta regression
    and the relative-strength metric, or None if either leg is unavailable.

    Best-effort by design. These feed a beta that has three fallbacks below it
    and a momentum metric that falls back to the vendor scalars, so a history
    outage should degrade both rather than 502 a whole scorecard — the same rule
    the peer fetch above already follows.

    Both legs are TTL-cached in the provider, so a screening run pays for each
    index once rather than once per company.
    """
    try:
        bars = provider.get_history(ticker, BETA_PERIOD, BETA_INTERVAL)
        index_bars = provider.get_history(home_index(ticker),
                                          BETA_PERIOD, BETA_INTERVAL)
    except Exception:
        return None
    return (bars, index_bars) if bars and index_bars else None


def _ndjson(events: AsyncIterator[dict]) -> StreamingResponse:
    """Serialize an async event stream as newline-delimited JSON.

    Errors become a final event instead of an HTTP status, because by the time
    the model fails the response headers are long gone.
    """
    async def body():
        try:
            async for event in events:
                yield (json.dumps(event) + "\n").encode()
        except ai_client.AIUnavailable as e:
            yield (json.dumps({"error": "ai_unavailable", "message": str(e)}) + "\n").encode()
        except Exception as e:  # never leave the client hanging on a half stream
            yield (json.dumps({"error": "stream_failed", "message": str(e)}) + "\n").encode()

    return StreamingResponse(body(), media_type="application/x-ndjson")


async def _analysis_with_beta(f: dict) -> dict:
    """full_analysis off the event loop — _peer_beta_inputs can hit the network."""
    return await asyncio.to_thread(
        lambda: financial_models.full_analysis(
            f, peers=_peer_beta_inputs(f), market_bars=_market_bars(f["ticker"])))


async def _text_stream(messages: list[dict], context: str) -> AsyncIterator[dict]:
    async for delta in ai_client.stream_chat(messages, context=context):
        yield {"delta": delta}


@app.get("/api/health")
async def health():
    return {"status": "ok", "ai": await ai_client.status()}


@app.get("/api/search")
async def search_endpoint(q: str = "", limit: int = 8):
    """Typo-tolerant symbol/name lookup for the header search box.

    Async + to_thread because the remote tier is a blocking HTTP call and this
    endpoint fires on every keystroke — blocking a worker per character would
    starve the pool that serves the rest of the page.
    """
    if not q.strip():
        return {"results": []}
    results = await asyncio.to_thread(search.search_tickers, q, min(limit, 20))
    return {"results": results}


@app.get("/api/stock/{ticker}/quote")
def quote(ticker: str):
    q = _guard(provider.get_quote, ticker)
    if q["price"] is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'")
    return q


# Finest interval Yahoo actually serves for each period. Measured against live
# responses 2026-08-07 — these are hard API limits, not preferences:
#   sub-hourly data  -> last 60 days only  (3mo at 30m returns ZERO bars)
#   hourly data      -> last 730 days only (5y at 1h returns ZERO bars)
# so 5y and max cannot go below daily however the UI asks.
PERIOD_INTERVALS = {
    "1d": "1m",     # 390 bars — the finest Yahoo serves, and its most rate-limited
    "5d": "5m",     # 390
    "1mo": "30m",   # 299
    "3mo": "1h",    # 441
    "6mo": "1h",    # 868
    "1y": "1h",     # 1,749
    "2y": "1h",     # 3,487
    "5y": "1d",     # 1,255
    "max": "1wk",
}
DEFAULT_INTERVAL = "1d"


def _bars_per_day(bars: list[dict]) -> float:
    """Median bars per trading day, measured from the data itself.

    The frontend scales indicator windows with this so "MA50" keeps meaning 50
    *days* whatever the bar size. Derived rather than hard-coded per interval
    because sessions differ by market — Hong Kong trades 5.5 hours against the
    US 6.5 — and half-days would skew a constant.
    """
    if not bars:
        return 1.0
    counts: dict[str, int] = {}
    for bar in bars:
        time_value = bar["time"]
        day = (datetime.fromtimestamp(time_value, tz=timezone.utc).strftime("%Y-%m-%d")
               if isinstance(time_value, (int, float)) else str(time_value)[:10])
        counts[day] = counts.get(day, 0) + 1
    if len(counts) < 3:
        return float(median(counts.values())) if counts else 1.0
    # drop the first and last day: both are usually partial sessions
    ordered = [counts[day] for day in sorted(counts)][1:-1]
    return float(median(ordered)) if ordered else 1.0


@app.get("/api/stock/{ticker}/history")
def history(ticker: str, period: str = "1y", interval: str = ""):
    """Bars plus the interval used and its bars-per-day, which the chart needs
    to keep day-based indicator windows meaning days."""
    interval = interval or PERIOD_INTERVALS.get(period, DEFAULT_INTERVAL)
    bars = _guard(provider.get_history, ticker, period, interval)
    if not bars and interval != DEFAULT_INTERVAL:
        # A thinly traded or newly listed name can have no intraday history
        # while having daily bars. Falling back beats an empty chart.
        interval = DEFAULT_INTERVAL
        bars = _guard(provider.get_history, ticker, period, interval)
    if not bars:
        raise HTTPException(status_code=404, detail=f"No price history for '{ticker}'")
    return {"interval": interval, "bars_per_day": _bars_per_day(bars), "bars": bars}


@app.get("/api/stock/{ticker}/news")
def news(ticker: str):
    return _guard(provider.get_news, ticker)


@app.get("/api/stock/{ticker}/events")
def events(ticker: str):
    """Everything datable onto the price chart: news plus SEC filings.

    Kept separate from /news because the AI context deliberately consumes
    headlines only — flooding a 7B model's prompt with Form 4 filings would
    crowd out the stories that actually explain a price move.

    `filings_supported` lets the UI say why an HK chart has no filing markers
    instead of leaving the user to wonder.
    """
    news_items = _guard(provider.get_news, ticker)
    filings = _guard(provider.get_filings, ticker)
    merged = sorted(news_items + filings, key=lambda n: n["date"] or "", reverse=True)
    return {
        "events": merged,
        "filings_supported": "." not in ticker,
        "counts": Counter(n["category"] for n in merged),
    }


@app.get("/api/stock/{ticker}/analysis")
def analysis(ticker: str):
    f = _guard(provider.get_fundamentals, ticker)
    return _guard(financial_models.full_analysis, f, peers=_peer_beta_inputs(f),
                  market_bars=_market_bars(ticker))


class DcfAssumptions(BaseModel):
    growth_rate: float | None = None
    # None => the platform's policy rate, which is TERMINAL_GROWTH held under
    # the GDP and risk-free ceilings. Sending a number overrides both, which is
    # what a what-if is for. Defaulting this to TERMINAL_GROWTH would have made
    # every request look like a deliberate override and silenced the ceilings.
    terminal_growth: float | None = None
    wacc_override: float | None = None
    # None => statutory rate for the listing's jurisdiction (HKD 16.5%, USD 21%)
    tax_rate: float | None = None


@app.post("/api/stock/{ticker}/dcf")
def custom_dcf(ticker: str, assumptions: DcfAssumptions):
    f = _guard(provider.get_fundamentals, ticker)
    return financial_models.dcf_valuation(
        f,
        growth_rate=assumptions.growth_rate,
        terminal_growth=assumptions.terminal_growth,
        wacc_override=assumptions.wacc_override,
        tax_rate=assumptions.tax_rate,
        peers=_peer_beta_inputs(f),
        market_bars=_market_bars(ticker),
    )


@app.get("/api/stock/{ticker}/peers")
def peers(ticker: str):
    return {"suggested": comps.suggest_peers(ticker)}


@app.get("/api/stock/{ticker}/comps")
def comps_endpoint(ticker: str, peer_list: str = ""):
    """peer_list: comma-separated tickers; empty uses suggestions."""
    tickers = [p.strip().upper() for p in peer_list.split(",") if p.strip()] \
        or comps.suggest_peers(ticker)
    f = _guard(provider.get_fundamentals, ticker)
    result = comps.comps_analysis(f, tickers)
    peer_betas = _peer_beta_inputs(f)
    bars = _market_bars(ticker)
    dcf = financial_models.dcf_valuation(f, peers=peer_betas, market_bars=bars)
    # The football field refuses to draw a DCF bar for a company type the model
    # does not fit, so the classification has to be resolved here — the same
    # statement-verified FCF the scorer uses, for the same reason (see
    # sector_weights.classify's docstring on info["freeCashflow"]).
    statement_fcf = financial_models._statement_fcf(f["cash_flow"])
    classification = sector_weights.classify(
        f["info"], statement_fcf[1] if statement_fcf else None)
    result["classification"] = classification
    result["dcf_applicable"] = sector_weights.dcf_applies(classification)
    # Resolved before the triangulation rather than after it: the gap bridge
    # below measures against this price, so it has to exist by then.
    result["current_price"] = f["info"].get("currentPrice") or f["info"].get("regularMarketPrice")
    result["football_field"] = comps.football_field(f, dcf, result, classification)
    result["triangulation"] = comps.triangulate(result["football_field"])
    # Why the DCF and the price differ, named. Only where a DCF applies at all —
    # for a bank or a REIT there is no gap to explain, there is no model.
    if result["dcf_applicable"]:
        result["triangulation"]["price_reconciliation"] = \
            financial_models.reconcile_to_price(f, dcf, peer_betas)
        # The same question as arithmetic rather than as a verdict: what our
        # number is, what the one justifiable adjustment does to it, and how
        # much distance is left over. Shown ahead of the conviction grade,
        # which came out LOW on every name tested and so said nothing.
        result["triangulation"]["price_gap_bridge"] = \
            comps.price_gap_bridge(dcf, result["current_price"])
    # When the anchors diverge the reference doc forbids averaging them and asks
    # for the assumption that separates them instead. Only computed on the
    # divergent path, since each back-solve runs a handful of extra DCFs.
    tri = result["triangulation"]
    if tri["diverged"] and result["dcf_applicable"] and not dcf.get("error"):
        core = next((r for r in result["football_field"]
                     if r["method"].startswith("Peer multiples")), None)
        tri["reconciling_growth"] = comps.reconciling_growth(
            f, core["mid"], peer_betas) if core else None
        tri["growth_used"] = dcf.get("assumptions", {}).get("growth_rate_year1")
        tri["growth_source"] = dcf.get("assumptions", {}).get("growth_source")
        # The other half of the explanation: the two anchors disagree partly
        # because a 2.5% perpetuity cannot express what today's multiple already
        # assumes. Carried here because the Scorecard has no other route to the
        # DCF's diagnostics.
        diag = dcf.get("diagnostics", {})
        tri["market_implied_terminal_growth"] = diag.get("market_implied_terminal_growth")
        tri["market_implied_growth_high"] = diag.get("market_implied_growth_high")
        tri["nominal_gdp_growth"] = diag.get("nominal_gdp_growth")
    return result


# ── scoring ──────────────────────────────────────────────────────────

def _score_and_record(ticker: str) -> dict:
    """Score a ticker and persist the result. Every score becomes an observation.

    The recorded price is what makes the scoring engine falsifiable later — see
    store.record_score.
    """
    f = provider.get_fundamentals(ticker)
    # resolve the DCF here so the valuation pillar sees the same peer-corrected
    # beta the Financial Models tab shows; score_company would otherwise compute
    # its own with the raw reported beta
    bars = _market_bars(f["ticker"])
    dcf = financial_models.dcf_valuation(f, peers=_peer_beta_inputs(f), market_bars=bars)
    card = scoring.score_company(f, dcf=dcf, market_bars=bars)
    # attached to the card, deliberately outside score_company: these are
    # reported beside the composite, never folded into it (see forensics.py)
    card["forensics"] = forensics.forensic_checks(f, card["classification"])
    store.record_score(card, f["info"])
    return card


@app.get("/api/score/{ticker}")
def score(ticker: str):
    return _guard(_score_and_record, ticker)


@app.get("/api/score/{ticker}/history")
def score_history(ticker: str, limit: int = 365):
    return {"ticker": ticker.upper(), "history": store.score_history(ticker, limit)}


class BatchRequest(BaseModel):
    tickers: list[str]


def _screener_row(card: dict) -> dict:
    """Compact row for the ranking table — the full card stays behind /api/score."""
    pillars = card.get("pillars", {})
    return {
        "ticker": card["ticker"],
        "composite_score": card["composite_score"],
        "tier": card.get("tier"),
        "tier_label": card.get("tier_label"),
        "confidence": card.get("confidence"),
        "coverage_pct": card.get("coverage_pct"),
        "classification": card.get("classification"),
        "flags": card.get("flags", []),
        "pillars": {name: {"score": p["score"], "insufficient": p["insufficient"]}
                    for name, p in pillars.items()},
    }


@app.post("/api/score/batch")
def score_batch(req: BatchRequest):
    """Score many tickers and return them ranked **within each classification**.

    Per docs/scoring-system-design.md §4.3, cards below 60% coverage are still
    returned but flagged `rankable: false` — they must not silently take a place
    in a ranking they cannot support.

    Ranking never crosses classifications. Composite scores from two different
    profiles are not the same measurement: the profiles score different metric
    sets (RIVN's valuation pillar is one metric, AAPL's is five), weight the
    pillars differently (G is 35% for pre-profit, 10% for a bank), score some
    shared metrics on different anchor curves (RELAXED_ND_EBITDA), and
    renormalize around whichever pillars had coverage. Measured 2026-08-07 on
    the seven fixtures, holding every pillar score fixed and changing only the
    weights to one common ruler moved three of seven positions, including 2nd
    place. Sorting them into one list asserted a comparison the engine never
    computed, so the grouping is the fix rather than a display preference.
    """
    seen, ordered = set(), []
    for raw in req.tickers:
        t = raw.strip().upper()
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    if not ordered:
        raise HTTPException(status_code=400, detail="No tickers supplied.")
    if len(ordered) > MAX_BATCH_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tickers ({len(ordered)}); limit is {MAX_BATCH_TICKERS}.",
        )

    rows, failed = [], []
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        for ticker, result in zip(ordered, pool.map(_safe_score, ordered)):
            if isinstance(result, Exception):
                failed.append({"ticker": ticker, "error": str(result)})
            else:
                rows.append(result)

    for r in rows:
        r["rankable"] = r["composite_score"] is not None and r["coverage_pct"] >= 60

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("classification") or "unclassified", []).append(r)

    ranked_total = 0
    out = []
    for classification in sorted(groups):
        members = groups[classification]
        rankable = sorted((r for r in members if r["rankable"]),
                          key=lambda r: r["composite_score"], reverse=True)
        for position, r in enumerate(rankable, start=1):
            r["rank_in_group"] = position
        unrankable = [r for r in members if not r["rankable"]]
        for r in unrankable:
            r["rank_in_group"] = None
        ranked_total += len(rankable)
        out.append({
            "classification": classification,
            "ranked": len(rankable),
            # a single-member group is a list, not a ranking — the UI says so
            "comparable": len(rankable) > 1,
            "results": rankable + unrankable,
        })

    # biggest comparable group first: that is where the ranking earns its keep
    out.sort(key=lambda g: (-g["ranked"], g["classification"]))
    unrankable_total = sum(len(g["results"]) - g["ranked"] for g in out)

    return {"groups": out, "failed": failed,
            "ranked": ranked_total, "excluded_low_coverage": unrankable_total}


def _safe_score(ticker: str):
    try:
        return _screener_row(_score_and_record(ticker))
    except Exception as e:  # one bad ticker must not fail the whole batch
        return e


# ── chart drawings ───────────────────────────────────────────────────

class DrawingRequest(BaseModel):
    kind: str                      # 'trendline' | 'hline'
    p1: float
    t1: int | None = None          # true UTC epoch, not chart-space time
    t2: int | None = None
    p2: float | None = None
    label: str | None = None


class DrawingPatch(BaseModel):
    t1: int | None = None
    p1: float | None = None
    t2: int | None = None
    p2: float | None = None
    label: str | None = None


KINDS = ("trendline", "hline")


@app.get("/api/stock/{ticker}/drawings")
def get_drawings(ticker: str):
    return {"drawings": store.list_drawings(ticker)}


@app.post("/api/stock/{ticker}/drawings")
def create_drawing(ticker: str, req: DrawingRequest):
    if req.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {KINDS}")
    if req.kind == "trendline" and None in (req.t1, req.t2, req.p2):
        raise HTTPException(status_code=400,
                            detail="a trendline needs both endpoints (t1,p1,t2,p2)")
    new_id = store.add_drawing(ticker, req.kind, req.p1, req.t1, req.t2, req.p2, req.label)
    return {"id": new_id}


@app.patch("/api/stock/{ticker}/drawings/{drawing_id}")
def patch_drawing(ticker: str, drawing_id: int, req: DrawingPatch):
    store.update_drawing(drawing_id, **req.model_dump(exclude_none=True))
    return {"ok": True}


@app.delete("/api/stock/{ticker}/drawings/{drawing_id}")
def remove_drawing(ticker: str, drawing_id: int):
    store.delete_drawing(drawing_id)
    return {"ok": True}


@app.delete("/api/stock/{ticker}/drawings")
def remove_all_drawings(ticker: str):
    store.clear_drawings(ticker)
    return {"ok": True}


def _drawing_context(ticker: str, bars: list[dict], price: float | None) -> dict:
    """Geometry of the user's lines, for the AI context. Computed, never guessed."""
    rows = store.list_drawings(ticker)
    return drawings_model.describe_all(rows, bars, price)


# ── watchlist / portfolio ────────────────────────────────────────────

class PositionRequest(BaseModel):
    ticker: str
    shares: float = 0.0
    cost_basis: float | None = None
    note: str | None = None


@app.get("/api/portfolio/tickers")
def portfolio_tickers():
    """Just the symbols, for the header's one-click chips.

    Separate from /api/portfolio because that endpoint prices every position
    live — a per-tab-change fetch of the full portfolio would spend N quote
    round-trips to render a row of buttons.
    """
    return {"tickers": [p["ticker"] for p in store.list_positions()]}


def position_values(price: float | None, shares: float, cost: float | None) -> dict:
    """The four money figures for one portfolio row.

    `unrealized_pnl` and `unrealized_pnl_pct` deliberately do **not** share a
    null condition, and a renderer that assumes they do will crash on a real
    input. A cost basis of exactly zero — a gift, a vest, or a typo in a field
    whose sibling placeholder suggests `0` — produces a genuine absolute gain
    and no meaningful percentage return, because the denominator is zero. Both
    answers are correct; the pair is simply not all-or-nothing, so each has to
    be read on its own.

    Extracted from the endpoint so that contract is pinned by a test: it was
    unreachable while it lived inline, which is why the crash shipped.
    """
    market_value = price * shares if price is not None else None
    cost_value = cost * shares if cost is not None else None
    return {
        "market_value": market_value,
        "cost_value": cost_value,
        "unrealized_pnl": (market_value - cost_value)
                          if market_value is not None and cost_value is not None else None,
        # `cost` truthiness rather than `is not None`: zero cost, no return
        "unrealized_pnl_pct": ((price / cost - 1) * 100)
                              if price is not None and cost else None,
    }


@app.get("/api/portfolio")
def portfolio():
    """Watchlist and holdings, priced live, with the latest stored score joined in.

    Weights and concentration are computed over held positions only; watchlist
    rows (shares = 0) carry no weight by definition.
    """
    positions = store.list_positions()
    if not positions:
        return {"rows": [], "totals": {}, "concentration": {}}

    tickers = [p["ticker"] for p in positions]
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        quotes = dict(zip(tickers, pool.map(_safe_quote, tickers)))
    scores = store.latest_scores(tickers)

    rows = []
    for p in positions:
        q = quotes.get(p["ticker"]) or {}
        price = q.get("price")
        shares, cost = p["shares"] or 0.0, p["cost_basis"]
        card = scores.get(p["ticker"])
        rows.append({
            **p,
            "name": q.get("name"),
            "currency": q.get("currency"),
            "price": price,
            **position_values(price, shares, cost),
            "score": card["composite"] if card else None,
            "tier": card["tier"] if card else None,
            # A composite only means something against its own profile — a bank's
            # 70 and a pre-profit company's 74 are outputs of two different
            # formulas. score_batch groups by this for exactly that reason; the
            # portfolio table lists holdings rather than ranking them, so it
            # carries the label instead of splitting the table.
            "classification": card["classification"] if card else None,
            "score_as_of": card["as_of_date"] if card else None,
            "quote_error": q.get("error"),
        })

    held = [r for r in rows if r["market_value"]]
    total_value = sum(r["market_value"] for r in held)
    total_cost = sum(r["cost_value"] for r in held if r["cost_value"] is not None)
    for r in rows:
        r["weight_pct"] = (r["market_value"] / total_value * 100) \
            if r["market_value"] and total_value else None

    weights = sorted((r["weight_pct"] for r in held if r["weight_pct"]), reverse=True)
    return {
        "rows": rows,
        "totals": {
            "market_value": round(total_value, 2),
            "cost_value": round(total_cost, 2) if total_cost else None,
            "unrealized_pnl": round(total_value - total_cost, 2) if total_cost else None,
            "unrealized_pnl_pct": round((total_value / total_cost - 1) * 100, 2)
                                  if total_cost else None,
            "holdings": len(held),
            "watchlist_only": len(rows) - len(held),
        },
        # Mixed currencies are summed at face value — see README limitations.
        "concentration": {
            "top_weight_pct": round(weights[0], 1) if weights else None,
            "top3_weight_pct": round(sum(weights[:3]), 1) if weights else None,
            # Herfindahl index on weights: 1/n = perfectly equal, 1.0 = single name
            "hhi": round(sum((w / 100) ** 2 for w in weights), 3) if weights else None,
        },
    }


def _safe_quote(ticker: str) -> dict:
    try:
        return provider.get_quote(ticker)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/portfolio/position")
def upsert_position(req: PositionRequest):
    if not req.ticker.strip():
        raise HTTPException(status_code=400, detail="Ticker is required.")
    store.upsert_position(req.ticker.strip(), req.shares, req.cost_basis, req.note)
    return {"ok": True}


@app.delete("/api/portfolio/position/{ticker}")
def remove_position(ticker: str):
    store.delete_position(ticker)
    return {"ok": True}


# ── AI (all streaming) ───────────────────────────────────────────────

@app.get("/api/ai/status")
async def ai_status():
    return await ai_client.status()


class ChatRequest(BaseModel):
    messages: list[dict]
    ticker: str | None = None


async def _ticker_context(ticker: str | None) -> str:
    if not ticker:
        return ""
    try:
        q, f = await asyncio.gather(
            asyncio.to_thread(provider.get_quote, ticker),
            asyncio.to_thread(provider.get_fundamentals, ticker),
        )
        # the user's own chart lines, reduced to computed geometry — see
        # drawings.py for why the model must be told who drew them
        bars = await asyncio.to_thread(provider.get_history, ticker, "6mo", "1d")
        return json.dumps({
            "quote": q,
            "analysis": await _analysis_with_beta(f),
            "user_chart_drawings": _drawing_context(ticker, bars, q.get("price")),
        }, default=str)
    except Exception:
        return ""  # chat still works without live context


@app.post("/api/ai/chat")
async def ai_chat(req: ChatRequest):
    context = await _ticker_context(req.ticker)
    return _ndjson(_text_stream(req.messages, context))


@app.post("/api/ai/predict/{ticker}")
async def ai_predict(ticker: str):
    q = await _aguard(provider.get_quote, ticker)
    bars = await _aguard(provider.get_history, ticker, "6mo", "1d")
    news_items = await _aguard(provider.get_news, ticker)
    f = await _aguard(provider.get_fundamentals, ticker)
    context = ai_client.outlook_context(
        q, bars[-30:], news_items, await _analysis_with_beta(f),
        drawings=_drawing_context(ticker, bars, q.get("price")))
    prompt = ai_client.outlook_prompt(ticker.upper())
    return _ndjson(_text_stream([{"role": "user", "content": prompt}], context))


@app.post("/api/score/{ticker}/narrative")
async def score_narrative(ticker: str):
    """LLM explains the already-computed score card. It never changes numbers."""
    card = await _aguard(_score_and_record, ticker)
    return _ndjson(_text_stream(
        [{"role": "user", "content": ai_client.NARRATIVE_PROMPT}], json.dumps(card)))


@app.post("/api/ai/debate/{ticker}")
async def ai_debate(ticker: str):
    """Bull vs bear vs verdict — three passes, disagreement kept visible."""
    q = await _aguard(provider.get_quote, ticker)
    f = await _aguard(provider.get_fundamentals, ticker)
    card = await _aguard(_score_and_record, ticker)
    context = json.dumps({"quote": q,
                          "analysis": await _analysis_with_beta(f),
                          "scorecard": card}, default=str)

    async def events():
        async for stage, delta in ai_client.stream_debate(ticker.upper(), context):
            yield {"stage": stage, "delta": delta}

    return _ndjson(events())
