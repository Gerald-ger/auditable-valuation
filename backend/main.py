"""FastAPI backend for the stock analysis platform.

Run:  backend\\.venv\\Scripts\\python.exe -m uvicorn main:app --app-dir backend --port 8000
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ai_client
import comps
import financial_models
import scoring
import store
from data_provider import provider

# yfinance is IO-bound but throttles bursts, so batch work fans out narrowly
# rather than one thread per ticker.
BATCH_WORKERS = 4
MAX_BATCH_TICKERS = 50


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


def _peer_betas(f: dict) -> list[float] | None:
    """Peer betas, but only when the company's own reported beta is not credible.

    resolve_beta prefers a plausible reported beta, so fetching peers otherwise
    would be pure waste — and this is the only network call the valuation path
    makes beyond the fundamentals themselves. yfinance returned 0.173 for XOM,
    which alone moved its DCF upside by ~79 points, so the rare fetch is worth it.
    """
    beta = f["info"].get("beta")
    if beta is not None and financial_models.BETA_MIN <= beta <= financial_models.BETA_MAX:
        return None
    return comps.peer_betas(f["ticker"])


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
    """full_analysis off the event loop — _peer_betas can hit the network."""
    return await asyncio.to_thread(
        lambda: financial_models.full_analysis(f, peer_betas=_peer_betas(f)))


async def _text_stream(messages: list[dict], context: str) -> AsyncIterator[dict]:
    async for delta in ai_client.stream_chat(messages, context=context):
        yield {"delta": delta}


@app.get("/api/health")
async def health():
    return {"status": "ok", "ai": await ai_client.status()}


@app.get("/api/stock/{ticker}/quote")
def quote(ticker: str):
    q = _guard(provider.get_quote, ticker)
    if q["price"] is None:
        raise HTTPException(status_code=404, detail=f"No data for ticker '{ticker}'")
    return q


@app.get("/api/stock/{ticker}/history")
def history(ticker: str, period: str = "1y", interval: str = "1d"):
    # short periods need intraday bars or the chart shows 1-5 candles
    if interval == "1d":
        interval = {"1d": "15m", "5d": "60m"}.get(period, "1d")
    bars = _guard(provider.get_history, ticker, period, interval)
    if not bars:
        raise HTTPException(status_code=404, detail=f"No price history for '{ticker}'")
    return bars


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
    return _guard(financial_models.full_analysis, f, peer_betas=_peer_betas(f))


class DcfAssumptions(BaseModel):
    growth_rate: float | None = None
    terminal_growth: float = financial_models.TERMINAL_GROWTH
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
        peer_betas=_peer_betas(f),
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
    dcf = financial_models.dcf_valuation(f, peer_betas=_peer_betas(f))
    result["football_field"] = comps.football_field(f, dcf, result)
    result["current_price"] = f["info"].get("currentPrice") or f["info"].get("regularMarketPrice")
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
    dcf = financial_models.dcf_valuation(f, peer_betas=_peer_betas(f))
    card = scoring.score_company(f, dcf=dcf)
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
    """Score many tickers and return them ranked.

    Per docs/scoring-system-design.md §4.3, cards below 60% coverage are still
    returned but flagged `rankable: false` — they must not silently take a place
    in a cross-company ranking they cannot support.
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
    rankable = sorted((r for r in rows if r["rankable"]),
                      key=lambda r: r["composite_score"], reverse=True)
    unrankable = [r for r in rows if not r["rankable"]]

    return {"results": rankable + unrankable, "failed": failed,
            "ranked": len(rankable), "excluded_low_coverage": len(unrankable)}


def _safe_score(ticker: str):
    try:
        return _screener_row(_score_and_record(ticker))
    except Exception as e:  # one bad ticker must not fail the whole batch
        return e


# ── watchlist / portfolio ────────────────────────────────────────────

class PositionRequest(BaseModel):
    ticker: str
    shares: float = 0.0
    cost_basis: float | None = None
    note: str | None = None


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
        market_value = price * shares if price is not None else None
        cost_value = cost * shares if cost is not None else None
        card = scores.get(p["ticker"])
        rows.append({
            **p,
            "name": q.get("name"),
            "currency": q.get("currency"),
            "price": price,
            "market_value": market_value,
            "cost_value": cost_value,
            "unrealized_pnl": (market_value - cost_value)
                              if market_value is not None and cost_value is not None else None,
            "unrealized_pnl_pct": ((price / cost - 1) * 100)
                                  if price is not None and cost else None,
            "score": card["composite"] if card else None,
            "tier": card["tier"] if card else None,
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
        return json.dumps({"quote": q,
                           "analysis": await _analysis_with_beta(f)}, default=str)
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
        q, bars[-30:], news_items, await _analysis_with_beta(f))
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
