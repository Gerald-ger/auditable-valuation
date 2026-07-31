"""FastAPI backend for the stock analysis platform.

Run:  backend\\.venv\\Scripts\\python.exe -m uvicorn main:app --app-dir backend --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import ai_client
import comps
import financial_models
import scoring
from data_provider import provider

app = FastAPI(title="Stock Analysis Platform")

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


@app.get("/api/health")
def health():
    return {"status": "ok", "ai": ai_client.status()}


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


@app.get("/api/stock/{ticker}/analysis")
def analysis(ticker: str):
    f = _guard(provider.get_fundamentals, ticker)
    return financial_models.full_analysis(f)


class DcfAssumptions(BaseModel):
    growth_rate: float | None = None
    terminal_growth: float = financial_models.TERMINAL_GROWTH
    wacc_override: float | None = None
    tax_rate: float = financial_models.DEFAULT_TAX_RATE


@app.post("/api/stock/{ticker}/dcf")
def custom_dcf(ticker: str, assumptions: DcfAssumptions):
    f = _guard(provider.get_fundamentals, ticker)
    return financial_models.dcf_valuation(
        f,
        growth_rate=assumptions.growth_rate,
        terminal_growth=assumptions.terminal_growth,
        wacc_override=assumptions.wacc_override,
        tax_rate=assumptions.tax_rate,
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
    dcf = financial_models.dcf_valuation(f)
    result["football_field"] = comps.football_field(f, dcf, result)
    result["current_price"] = f["info"].get("currentPrice") or f["info"].get("regularMarketPrice")
    return result


@app.get("/api/score/{ticker}")
def score(ticker: str):
    f = _guard(provider.get_fundamentals, ticker)
    return scoring.score_company(f)


@app.post("/api/score/{ticker}/narrative")
def score_narrative(ticker: str):
    """LLM explains the already-computed score card. It never changes numbers."""
    import json
    f = _guard(provider.get_fundamentals, ticker)
    card = scoring.score_company(f)
    prompt = ("You are given a completed company score card. Write 4-6 sentences "
              "explaining the strongest pillar, the weakest pillar, and what any "
              "flags mean. Do not compute or change any numbers. Do not state any "
              "figure not present in the input.")
    result = ai_client.chat([{"role": "user", "content": prompt}],
                            context=json.dumps(card))
    result["scorecard"] = card
    return result


@app.get("/api/ai/status")
def ai_status():
    return ai_client.status()


class ChatRequest(BaseModel):
    messages: list[dict]
    ticker: str | None = None


@app.post("/api/ai/chat")
def ai_chat(req: ChatRequest):
    context = ""
    if req.ticker:
        try:
            q = provider.get_quote(req.ticker)
            f = provider.get_fundamentals(req.ticker)
            import json
            context = json.dumps({"quote": q,
                                  "analysis": financial_models.full_analysis(f)},
                                 default=str)
        except Exception:
            pass  # chat still works without live context
    return ai_client.chat(req.messages, context=context)


@app.post("/api/ai/predict/{ticker}")
def ai_predict(ticker: str):
    q = _guard(provider.get_quote, ticker)
    bars = _guard(provider.get_history, ticker, "6mo", "1d")
    news_items = _guard(provider.get_news, ticker)
    f = _guard(provider.get_fundamentals, ticker)
    return ai_client.predict(ticker.upper(), q, bars[-30:], news_items,
                             financial_models.full_analysis(f))
