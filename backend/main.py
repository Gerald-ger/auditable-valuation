"""FastAPI backend for the stock analysis platform.

Run (from the repo root):
    Windows       backend\\.venv\\Scripts\\python.exe -m uvicorn backend.main:app --port 8000
    macOS/Linux   backend/.venv/bin/python -m uvicorn backend.main:app --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import ai_client
from backend import comps
from backend import drawings as drawings_model
from backend import financial_models
from backend import forensics
from backend import scoring
from backend import search
from backend import sector_weights
from backend import statements
from backend import store
from backend.data_provider import (DEMO_MODE, demo_data_as_of, fx_rate,
                                   home_index, provider, with_fresh_price)

# What the portfolio's aggregate figures are denominated in. A total is a sum,
# and a sum needs one unit — holdings that trade in USD and HKD were previously
# added at face value, which produces a number in no currency at all.
BASE_CURRENCY = "HKD"

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


app = FastAPI(title="Auditable Valuation", lifespan=lifespan)

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


def _fundamentals(ticker: str, fresh_price: bool = True) -> dict:
    """Fundamentals, with the price brought up to date by default.

    The statements are TTL-cached for fifteen minutes because they only change
    quarterly. The price rides in the same payload and does not have that luxury,
    and stacked on the vendor's own fifteen-minute delay it left the valuation
    screen up to half an hour behind the market.

    `fresh_price=False` is for the batch screener, which ranks up to fifty
    companies: a stale quote cannot reorder a ranking, and a fetch per ticker
    would roughly double that run's network work.
    """
    f = provider.get_fundamentals(ticker)
    return with_fresh_price(f) if fresh_price else f


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


_NO_EVENT = object()


async def _ndjson(events: AsyncIterator[dict]) -> StreamingResponse:
    """Serialize an async event stream as newline-delimited JSON.

    A failure *before* the first event becomes a real status. A failure after it
    cannot: 200 is already on the wire by then, so it arrives as a terminal
    in-body event instead. That asymmetry is HTTP's, not a preference.

    Which half a failure lands in is not evenly split. `ai_client` raises
    AIUnavailable from two places — a mid-stream `{"error": ...}` chunk, and the
    `except (ClientError, TimeoutError)` around `session.post`. The second is a
    connection failure, so it happens before anything is yielded, and it is the
    one every request takes while Ollama is not running. Until 2026-08-28 that
    case also answered 200, which meant a client doing the ordinary thing —

        r = requests.post(..., stream=True); r.raise_for_status()

    could never see it fail. The app's own `stream()` was never fooled: it
    checks `res.ok` first (frontend/src/api.js) and reads `detail` off the body,
    which is why the status raised here is an HTTPException rather than a
    hand-built response.

    Pulling one event to find out costs nothing extra — it is the same event the
    body would have yielded first, held rather than re-requested.
    """
    first = _NO_EVENT
    try:
        first = await anext(events)
    except StopAsyncIteration:
        pass  # an empty stream is a 200 with an empty body, as before
    except ai_client.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"stream_failed: {e}") from e

    async def body():
        if first is not _NO_EVENT:
            yield (json.dumps(first) + "\n").encode()
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


def _source_fingerprint() -> str:
    """A digest of the backend source this process could be running.

    Content-hashed rather than mtime-compared: an editor or a checkout can touch
    a file without changing a byte of it — `sector_weights.py` did exactly that
    on 2026-08-14 while `git status` stayed clean — and an mtime test would
    report that as a stale server.

    Read as *text*, so line endings are normalised before hashing. On a Windows
    checkout that is not a detail: measured 2026-08-14, `git checkout` restored
    `sector_weights.py` with 252 CRLF where the running process had loaded LF, so
    a byte hash reported a stale server for a file git itself called unmodified.
    A false positive here is cheap but not free — a banner nobody can clear is a
    banner people learn to ignore.
    """
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(path.read_text(encoding="utf-8").encode("utf-8"))
    return digest.hexdigest()[:12]


# Captured at import, so it is the source this interpreter actually loaded.
SOURCE_AT_START = _source_fingerprint()


@app.get("/api/health")
async def health():
    """Liveness, AI status, and whether this process is still running the code
    on disk.

    The last one exists because a stale backend is this project's most repeated
    self-inflicted wound — three times on 2026-08-14 alone. It is nastier than a
    crash: an endpoint added after the server booted simply returns nothing, the
    UI panel that reads it correctly renders nothing, and the result is
    indistinguishable from a feature that was never built. `ErrorBoundary`
    already tells the reader to suspect it; this lets the app say so first.
    """
    return {"status": "ok", "ai": await ai_client.status(),
            # Same reasoning as `demo` below, and the same poll. Costs a file
            # read: `fmp_status` deliberately does not ask OpenBB, whose
            # credentials model takes 3.37 s to import.
            "fmp": comps.fmp_status(),
            "source_changed_since_start": _source_fingerprint() != SOURCE_AT_START,
            # Rides this poll rather than adding an endpoint: the frontend
            # already calls `/health` on mount and every 30 s, and a second
            # timer for a value that cannot change within a process would be
            # two requests answering one question.
            "demo": DEMO_MODE}


class FmpKeyRequest(BaseModel):
    key: str


def _reject_key_writes_in_demo():
    """Demo mode must never write a credential, and this is the load-bearing half.

    Hiding the tab is the visible half and is not a control: the endpoint is
    reachable regardless. On a hosted demo the filesystem being written would be
    the *host's*, so a visitor typing a key would either overwrite the operator's
    or leave their own on a stranger's machine for every later visitor to use.
    """
    if DEMO_MODE:
        raise HTTPException(
            status_code=403,
            detail="Demo mode uses committed fixtures and reaches no vendor, so a "
                   "key would do nothing — and this may not be your machine.")


@app.post("/api/settings/fmp-key")
async def set_fmp_key(req: FmpKeyRequest):
    """Verify an FMP key, and store it only if it works.

    Verify *then* store, in that order. The reverse cost a real key on
    2026-08-28: a placeholder typed to see what the tab did overwrote a working
    one before the check ran, and the accurate "failed" that came back was a
    report on damage already done.

    The response carries `saved`, because "the key you have is failing" and "what
    you just typed was rejected and nothing changed" are different sentences.
    On a rejection nothing on disk moves and `last_call` is left as it was —
    that verdict belonged to the candidate, not to the key still stored.

    There is deliberately no GET counterpart. Nothing here is authenticated, and
    an endpoint that returns a stored credential is how a convenience becomes a
    disclosure. `/api/health` reports *whether* one is set, never what it is.
    """
    _reject_key_writes_in_demo()
    try:
        return await asyncio.to_thread(comps.save_fmp_key, req.key)
    except comps.CredentialFileError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/settings/fmp-key")
async def delete_fmp_key():
    """Remove the key, leaving every other setting in that file as it was."""
    _reject_key_writes_in_demo()
    try:
        return await asyncio.to_thread(comps.clear_fmp_key)
    except comps.CredentialFileError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


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


# Bar size per period. Until 2026-08-19 this table chose the **finest** interval
# Yahoo serves, which is how 1y and 2y arrived as 1,740 and 3,487 hourly bars.
# Finest is the wrong objective. MA20/MA50, RSI(14) and MACD(12,26,9) are
# daily-line conventions and the chart counts *bars*, so a one-year chart at 1h
# was drawing a fourteen-**hour** RSI under the label RSI(14), and an MA50 that
# spanned 7.7 sessions rather than fifty days. 6mo, 1y and 2y are daily now, so
# those three ranges mean what their names have always claimed.
#
# Two hard Yahoo limits bound the top of the table — measured 2026-08-07, API
# limits rather than preferences:
#   sub-hourly data -> last 60 days only  (3mo at 30m returns ZERO bars)
#   hourly data     -> last 730 days only (5y at 1h returns ZERO bars)
#
# A third bounds the bottom, measured 2026-08-19 and the reason `max` did **not**
# move to monthly: Yahoo caps a monthly response at **500 bars**, so max at 1mo
# starts XOM in 1985 instead of 1962 — twenty-three years dropped from the one
# button whose whole job is showing all of them, and dropped *silently*, because
# the fallback below only fires on zero bars. RIVN would fall to 58 monthly bars,
# where MA50 alone consumes fifty of them.
#
# Bar counts are AAPL on 2026-08-19; 0700.HK lands within a few percent of each.
PERIOD_INTERVALS = {
    "1d": "1m",     # 390 bars — the finest Yahoo serves, and its most rate-limited
    "5d": "5m",     # 390
    "1mo": "1h",    # 154
    "3mo": "4h",    # 126 — exactly two bars a session (09:30 and 13:30, measured
                    # on AAPL and 0700.HK alike), so MA50 spans ~25 days. Daily
                    # would be 63 bars here and MA50 needs 50 of them, leaving
                    # the line absent from 79% of the chart.
    "6mo": "1d",    # 125
    "1y": "1d",     # 251
    "2y": "1d",     # 501
    "5y": "1wk",    # 262
    "max": "1wk",   # 2,385 for AAPL, back to 1980 — see the 500-bar note above
}
DEFAULT_INTERVAL = "1d"

# Bars of lead-in fetched *before* the requested window, so the indicators exist
# at its left edge instead of starting a third of the way in.
#
# 50 is MA50, the longest window the chart draws, and `smaSeries` emits from
# index `period - 1` — so exactly 50 leading bars put MA50 on the **first**
# displayed bar. The other three windows are shorter and ride along: the SD band
# needs 20, RSI(14) needs 15, and MACD(12,26,9)'s signal line first exists at
# bar 34 (`slow - 1` for the MACD line, then 9 more for its EMA).
WARMUP_BARS = 50

# Where the lead-in comes from: the next period up that Yahoo serves at the same
# interval. It is trimmed to WARMUP_BARS before going out, so the wire cost is
# **flat** however much larger the source is — measured 2026-08-19 across both
# markets, +5.2 to +5.8 KB on every range, because 50 bars of JSON is 50 bars of
# JSON. The extra fetch is the real cost and it is bounded by the 15-minute
# provider cache.
#
# `1d` and `5d` are absent deliberately, and it is a measurement rather than an
# oversight. Their sources would be 5d at 1m (1,950 bars fetched to display 390)
# and 1mo at 5m (1,716 for 390) — a 4-5x fetch against the two endpoints Yahoo
# rate-limits hardest, `1m` most of all — to buy the last 13% of a chart that
# already carries MA50 across 87% of itself. `max` is absent because no bar
# exists before the first one.
WARMUP_SOURCE = {
    "1mo": "3mo",
    "3mo": "6mo",
    "6mo": "1y",
    "1y": "2y",
    "2y": "5y",
    "5y": "max",
}


def _lead_in(ticker: str, period: str, interval: str, first_time) -> list[dict]:
    """Up to WARMUP_BARS bars immediately before `first_time`, or `[]`.

    Deliberately **not** wrapped in `_guard`. That helper turns any provider
    exception into a 502, which is right for the bars a chart cannot be drawn
    without and wrong for these: a lead-in failure must cost the left edge of an
    indicator, never the chart. Same rule as `risk_free_rate`, `fx_rate` and
    `live_price` — degrade the number, never the request.

    Returns fewer than WARMUP_BARS, including none at all, whenever the source
    has no earlier history. A company listed inside the requested window is the
    ordinary case: RIVN's 5y and its max are the same 250 weekly bars, so it
    gets no lead-in and the chart behaves exactly as it did before.
    """
    source = WARMUP_SOURCE.get(period)
    if source is None:
        return []
    try:
        longer = provider.get_history(ticker, source, interval)
    except Exception:
        return []
    # `time` is an ISO string for daily-and-coarser bars and an epoch int for
    # intraday ones. Both series come from the same `interval`, so the two sides
    # of this comparison are always the same type.
    earlier = [b for b in longer if b["time"] < first_time]
    return earlier[-WARMUP_BARS:]


def _bars_per_day(bars: list[dict]) -> float:
    """Median bars per trading day, measured from the data itself.

    Derived rather than hard-coded per interval because sessions differ by
    market — Hong Kong trades 5.5 hours against the US 6.5 — and half-days would
    skew a constant.

    **Served in the payload, and consumed by nothing.** This docstring claimed
    until 2026-08-19 that *"the frontend scales indicator windows with this so
    MA50 keeps meaning 50 days whatever the bar size"*. It does not: searching
    the tree finds `bars_per_day` here, in `CHANGELOG.md`, and in one comment
    naming the payload shape — nowhere else. The chart keeps its windows in bars
    and *names* the span instead (`indicators.windowSpan`), which
    `PriceChart.jsx` has always said in as many words.

    Corrected rather than deleted because of what the false version cost: it is
    exactly the mitigation someone would assume already exists before changing an
    interval above. It does not exist, so **an interval change really does change
    what every indicator measures**, and the only defence is the label.
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
    """Bars, the interval used, and how many leading bars are lead-in only.

    `bars` is the lead-in followed by the requested window, in one ascending
    series, because every indicator is a function of the bars before it and
    handing the chart two arrays would only make it join them again.
    `warmup_bars` is where the requested window starts, and it is the whole
    contract: a client that ignores it draws a chart a little longer than it
    asked for, rather than a wrong one.
    """
    interval = interval or PERIOD_INTERVALS.get(period, DEFAULT_INTERVAL)
    bars = _guard(provider.get_history, ticker, period, interval)
    if not bars and interval != DEFAULT_INTERVAL:
        # A thinly traded or newly listed name can have no intraday history
        # while having daily bars. Falling back beats an empty chart.
        interval = DEFAULT_INTERVAL
        bars = _guard(provider.get_history, ticker, period, interval)
    if not bars:
        raise HTTPException(status_code=404, detail=f"No price history for '{ticker}'")
    warmup = _lead_in(ticker, period, interval, bars[0]["time"])
    return {"interval": interval, "warmup_bars": len(warmup),
            "bars_per_day": _bars_per_day(bars), "bars": warmup + bars}


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
    f = _guard(_fundamentals, ticker)
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
    f = _guard(_fundamentals, ticker)
    return financial_models.dcf_valuation(
        f,
        growth_rate=assumptions.growth_rate,
        terminal_growth=assumptions.terminal_growth,
        wacc_override=assumptions.wacc_override,
        tax_rate=assumptions.tax_rate,
        peers=_peer_beta_inputs(f),
        market_bars=_market_bars(ticker),
    )


# Which override each model calls its first-order driver. They are not
# interchangeable and the endpoint below refuses to treat them as such: a return
# on equity and a dividend growth rate are different quantities, and a body that
# quietly dropped the one that did not apply would let a caller believe it had
# changed something.
INTRINSIC_DRIVERS = {"excess_return": "roe", "dividend_discount": "growth_rate"}


class IntrinsicAssumptions(BaseModel):
    """What-ifs for the two models a DCF cannot build. `None` means "measured".

    Same convention as `DcfAssumptions`: an omitted field is the platform's own
    figure, and sending one overrides it. `terminal_growth` sent as a number
    overrides both ceilings, which is what a what-if is for.

    `tax_rate` looks inert here and is not. Neither model discounts at WACC, so
    the tax shield on debt reaches nothing they compute — measured on the JPM
    and O fixtures 2026-08-29, 21% against 45% changes not one output, only the
    reported `tax_rate`, `cost_of_debt_after_tax` and `wacc`.

    That measurement was taken without peers, and it is why the first draft of
    this model left the field out on the stated grounds that neither model reads
    it. **That was false.** `resolve_beta` unlevers a peer beta as
    `Bu = Bl / (1 + (1 - Tc) x D/E)` and relevers it to the target, so the tax
    rate sets the beta whenever the peer ladder is reached — which this endpoint
    reaches through `_peer_beta_inputs` for any issuer whose own reported beta
    is outside the credibility band, a condition the beta comment records
    hitting an entire sector at once. Measured on a JPM fixture with an
    incredible beta and three peers: at 21% the beta relevers to 1.7855 and the
    fair value is 192.13; at 45% it is 1.5937 and 215.41. Twenty-three points a
    share, from the field that "could not move the answer". Found in
    adversarial review 2026-08-29.
    """

    # Excess return only: the return on equity whose spread over the cost of
    # equity is the whole valuation.
    roe: float | None = None
    # Dividend discount only: the rate the dividend per share compounds at
    # through the explicit stage.
    growth_rate: float | None = None
    terminal_growth: float | None = None
    # Named for what it is rather than `wacc_override`. These models never form
    # a WACC — there is no debt weighting in either — so borrowing the DCF's
    # field name would invite a reader to think the two mean the same thing.
    cost_of_equity: float | None = None
    # None => statutory rate for the listing's jurisdiction (HKD 16.5%, USD 21%),
    # exactly as `DcfAssumptions` has it. See the note above for why it is here.
    tax_rate: float | None = None


@app.post("/api/stock/{ticker}/intrinsic")
def custom_intrinsic(ticker: str, assumptions: IntrinsicAssumptions):
    """Re-run whichever intrinsic model fits this company, with overrides.

    Mirrors `custom_dcf` above, including its error convention: a model that
    refuses returns its `{"error": ...}` with a 200, because a refusal is a
    result the panel renders rather than a failure of the request. The 400s
    below are different — they mean the request itself does not describe
    anything this company has.

    **The two inequality refusals stand against a user; the data-quality band
    does not, and the difference is the point.** Both models assign the supplied
    cost of equity before their guards run, so a rate at or below terminal
    growth still refuses and, for a REIT, a rate below its own pre-tax cost of
    debt still refuses. Those are statements about arithmetic and seniority: a
    user is no more entitled to divide by a negative spread than the platform
    is. `GROWTH_VALIDITY_RANGE` is a different kind of check — it rejects a
    *measured* dividend series compounding at an impossible rate, which is a
    judgement about vendor data — and it is skipped entirely when the caller
    supplies the rate, because a figure someone typed is not a measurement.

    So nothing here bounds the magnitude of `roe` or `growth_rate`, and that is
    deliberate rather than missing. A cost of equity of 2.51% — one basis point
    above the refusal — values JPM at 256,233.12 a share against a price of
    359.24, and no invented ceiling would have been the right way to say so.
    What says so is the model's own `terminal_value_share`: 99.87% at that rate,
    against the conventional 75% line the panel already flags, and 81.07% at a
    4% cost of equity. The diagnostic that exists catches the region that blows
    up, measured across the sweep 2026-08-29; a bound would have had to invent
    a number to do worse.
    """
    f = _guard(_fundamentals, ticker)
    # Classified the same two lines `comps_endpoint` uses, off the
    # statement-verified free cash flow rather than `info["freeCashflow"]` —
    # see `sector_weights.classify`. Passed into the model below so one request
    # cannot classify the same company twice and disagree with itself.
    statement_fcf = statements.statement_fcf(f["cash_flow"])
    classification = sector_weights.classify(
        f["info"], statement_fcf[1] if statement_fcf else None)
    model = sector_weights.valuation_model_for(classification)
    driver = INTRINSIC_DRIVERS.get(model)
    if driver is None:
        raise HTTPException(
            status_code=400,
            detail=f"No intrinsic model applies to a {classification.replace('_', ' ')}"
                   + (". A discounted cash flow does — POST to /dcf instead."
                      if model else ". Neither this nor a discounted cash flow does."))

    supplied = {k: v for k in INTRINSIC_DRIVERS.values()
                if (v := getattr(assumptions, k)) is not None}
    if wrong := set(supplied) - {driver}:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(sorted(wrong))} is not an input to the "
                   f"{model.replace('_', ' ')} model this company uses; it takes "
                   f"{driver}.")

    return financial_models.intrinsic_valuation(
        f, classification,
        terminal_growth=assumptions.terminal_growth,
        cost_of_equity_override=assumptions.cost_of_equity,
        tax_rate=assumptions.tax_rate,
        peers=_peer_beta_inputs(f),
        market_bars=_market_bars(ticker),
        **supplied,
    )


@app.get("/api/stock/{ticker}/peers")
def peers(ticker: str):
    return {"suggested": comps.suggest_peers(ticker)}


@app.get("/api/stock/{ticker}/comps")
def comps_endpoint(ticker: str, peer_list: str = ""):
    """peer_list: comma-separated tickers; empty uses suggestions."""
    tickers = [p.strip().upper() for p in peer_list.split(",") if p.strip()] \
        or comps.suggest_peers(ticker)
    f = _guard(_fundamentals, ticker)
    result = comps.comps_analysis(f, tickers)
    peer_betas = _peer_beta_inputs(f)
    bars = _market_bars(ticker)
    dcf = financial_models.dcf_valuation(f, peers=peer_betas, market_bars=bars)
    # The football field refuses to draw a DCF bar for a company type the model
    # does not fit, so the classification has to be resolved here — the same
    # statement-verified FCF the scorer uses, for the same reason (see
    # sector_weights.classify's docstring on info["freeCashflow"]).
    statement_fcf = statements.statement_fcf(f["cash_flow"])
    classification = sector_weights.classify(
        f["info"], statement_fcf[1] if statement_fcf else None)
    result["classification"] = classification
    result["dcf_applicable"] = sector_weights.dcf_applies(classification)
    # Which intrinsic model this type gets, which since 2026-08-29 is a
    # different question from whether a DCF applies: a bank answers False above
    # and "excess_return" here. Everything gated on `dcf_applicable` below is
    # DCF machinery specifically — a growth-rate back-solve, an enterprise-value
    # bridge — and none of it means anything for a model that values equity
    # directly off book value, so those gates stay exactly as they were.
    result["valuation_model"] = sector_weights.valuation_model_for(classification)
    excess_return = (
        financial_models.excess_returns_valuation(f, peers=peer_betas, market_bars=bars)
        if result["valuation_model"] == "excess_return" else None)
    dividend_discount = (
        financial_models.dividend_discount_valuation(f, peers=peer_betas, market_bars=bars)
        if result["valuation_model"] == "dividend_discount" else None)
    # Resolved before the triangulation rather than after it: the gap bridge
    # below measures against this price, so it has to exist by then.
    result["current_price"] = f["info"].get("currentPrice") or f["info"].get("regularMarketPrice")
    result["football_field"] = comps.football_field(
        f, dcf, result, classification, excess_return=excess_return,
        dividend_discount=dividend_discount)
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

def _score_and_record(ticker: str, fresh_price: bool = True) -> dict:
    """Score a ticker and persist the result. Every score becomes an observation.

    The recorded price is what makes the scoring engine falsifiable later — see
    store.record_score.
    """
    f = _fundamentals(ticker, fresh_price)
    # resolve the DCF here so the valuation pillar sees the same peer-corrected
    # beta the Financial Models tab shows; score_company would otherwise compute
    # its own with the raw reported beta
    bars = _market_bars(f["ticker"])
    peers = _peer_beta_inputs(f)
    dcf = financial_models.dcf_valuation(f, peers=peers, market_bars=bars)
    # And the same for whichever intrinsic model fits a company the DCF cannot
    # value. Resolved here rather than left to `score_company`'s fallback so the
    # pillar reports the same valuation the chart drew, from one resolution
    # rather than two that merely ought to agree.
    #
    # The peers are the part the fallback cannot reproduce — it has no `peers`
    # parameter to be given any. They bind rarely: `resolve_beta` prefers a
    # regression when bars exist and a credible reported beta when they do not,
    # so on JPM the peer set changes nothing and passing it here is provably a
    # no-op. It is not a no-op for an issuer whose reported beta is missing or
    # outside the credibility band and whose series is too thin to regress,
    # which is the case this argument is actually about.
    #
    # Resolved for every ticker rather than only for the profiles that score it,
    # so a REIT pays for a dividend discount model whose answer the scorecard
    # then discards. Deliberate symmetry rather than an oversight: the line
    # above resolves a DCF for every ticker too, including the banks whose
    # profile has no `dcf_upside_pct` to spend it on. Both are cheap beside the
    # fetches that precede them, and gating either would put a second copy of
    # the profile's metric list here, where it could disagree with the first.
    valuation = financial_models.intrinsic_valuation(f, peers=peers, market_bars=bars)
    card = scoring.score_company(f, dcf=dcf, market_bars=bars, valuation=valuation)
    # attached to the card, deliberately outside score_company: these are
    # reported beside the composite, never folded into it (see forensics.py)
    card["forensics"] = forensics.forensic_checks(f, card["classification"])
    # `as_of` above is when this score was computed; both modes report it
    # truthfully and neither says anything about the data underneath. `None`
    # here means live. Set outside `score_company` for the same reason
    # `forensics` is: the scorer is a pure function of its arguments and does
    # not know which provider filled them.
    card["data_as_of"] = demo_data_as_of(f["ticker"])
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
        # Snapshot price on purpose: a 15-minute-old quote cannot change a
        # *ranking*, and a quote fetch per ticker would roughly double the
        # network work of a fifty-name run.
        return _screener_row(_score_and_record(ticker, fresh_price=False))
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
    """404 when the drawing is not this ticker's, rather than a silent success.

    `ticker` was in the path and never used, so any ticker's URL could move any
    drawing. The frontend cannot notice either way — all three call sites in
    PriceChart.jsx catch and discard, deliberately, so that a failed save does
    not break the gesture that caused it. That is what made this quiet.
    """
    if not store.update_drawing(drawing_id, ticker, **req.model_dump(exclude_none=True)):
        raise HTTPException(status_code=404,
                            detail=f"No drawing {drawing_id} on '{ticker.upper()}'")
    return {"ok": True}


@app.delete("/api/stock/{ticker}/drawings/{drawing_id}")
def remove_drawing(ticker: str, drawing_id: int):
    if not store.delete_drawing(drawing_id, ticker):
        raise HTTPException(status_code=404,
                            detail=f"No drawing {drawing_id} on '{ticker.upper()}'")
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

    # One lookup per distinct currency rather than per row: `fx_rate` caches per
    # calendar day, and a portfolio spans a handful of listing currencies however
    # many positions it holds. Rows whose money figures are all zero or absent —
    # a watchlist entry, an unpriced ticker with no cost — need no rate, because
    # zero is zero in every currency.
    rates = {c: fx_rate(c, BASE_CURRENCY)
             for c in {r["currency"] for r in rows
                       if r["market_value"] or r["cost_value"]}}
    # `or "unreported"` because a quote that failed carries no currency at all,
    # and a blank in this list would read as though nothing were wrong.
    unconverted = sorted({c or "unreported"
                          for c, rate in rates.items() if rate is None})

    # All or nothing. Converting the rows that have a rate and leaving the rest
    # native would put two units in one column, which is the defect rather than
    # a partial fix — so on any failure every row stays as reported and the
    # totals refuse instead of falling back to the face-value sum, which is
    # today's wrong number with a warning beside it.
    if not unconverted:
        for r in rows:
            rate = rates.get(r["currency"])
            if rate is None:
                continue
            for key in ("market_value", "cost_value", "unrealized_pnl"):
                if r[key] is not None:
                    r[key] = r[key] * rate
            # `unrealized_pnl_pct` is deliberately absent from that list. It is
            # a ratio of two figures in the same currency, so the rate cancels;
            # multiplying it would be a category error.

    held = [r for r in rows if r["market_value"]]
    total_value = None if unconverted else sum(r["market_value"] for r in held)
    total_cost = None if unconverted else sum(
        r["cost_value"] for r in held if r["cost_value"] is not None)
    for r in rows:
        r["weight_pct"] = (r["market_value"] / total_value * 100) \
            if r["market_value"] and total_value else None

    weights = sorted((r["weight_pct"] for r in held if r["weight_pct"]), reverse=True)
    return {
        "rows": rows,
        "totals": {
            # Stated rather than assumed: the figures below are a sum, and a sum
            # in an unnamed unit is what this endpoint used to return.
            "currency": None if unconverted else BASE_CURRENCY,
            "unconverted_currencies": unconverted,
            "market_value": round(total_value, 2) if total_value is not None else None,
            "cost_value": round(total_cost, 2) if total_cost else None,
            "unrealized_pnl": round(total_value - total_cost, 2) if total_cost else None,
            "unrealized_pnl_pct": round((total_value / total_cost - 1) * 100, 2)
                                  if total_cost else None,
            "holdings": len(held),
            "watchlist_only": len(rows) - len(held),
        },
        # Weights are shares of the converted total, so these are comparable
        # across currencies — which the face-value versions were not.
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
    ticker = req.ticker.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker is required.")
    if DEMO_MODE:
        # A hosted demo takes writes from strangers and gives none of them a way
        # to undo one. Unguarded, this accepted any string: `TSLA` became a
        # permanent row whose quote read "TSLA is not one of the demo tickers" —
        # accurate, and nobody's to clear.
        #
        # `get_quote` rather than a ticker list, because it is the same call the
        # portfolio makes to render the row: what is accepted here is exactly
        # what can be priced there. Live mode is deliberately *not* checked — a
        # provider call on this path is a network round trip standing between
        # you and your own record of what you hold.
        try:
            provider.get_quote(ticker)
        except KeyError as e:
            raise HTTPException(status_code=400, detail=e.args[0]) from e
    store.upsert_position(ticker, req.shares, req.cost_basis, req.note)
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
    return await _ndjson(_text_stream(req.messages, context))


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
    return await _ndjson(_text_stream([{"role": "user", "content": prompt}], context))


@app.post("/api/score/{ticker}/narrative")
async def score_narrative(ticker: str):
    """LLM explains the already-computed score card. It never changes numbers."""
    card = await _aguard(_score_and_record, ticker)
    return await _ndjson(_text_stream(
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

    return await _ndjson(events())


# ── The built frontend, served from this same process ────────────────────────
#
# Mounted last, and only when the directory exists. Every route above is under
# `/api/`, and FastAPI's own `/docs`, `/redoc` and `/openapi.json` are registered
# before any of them, so nothing here can shadow a route: Starlette matches in
# registration order, and a mount is a prefix match of last resort.
#
# This is the whole of what a single-origin deployment needs from the backend.
# `frontend/src/api.js` already requests a relative `/api` — deliberately, after
# an absolute host once made a shifted dev-server port fail silently — so with
# the UI served from here there is no second origin and no CORS handshake at all.
# The `allow_origins` list above is left alone: in a single-origin deployment
# nothing matches it, and the Vite dev server still needs it.
#
# `html=True` serves `index.html` at `/`. `App.jsx` switches tabs with `useState`
# rather than a router, so there are no deep links needing a rewrite rule.
#
# In development this directory does not exist — `frontend/dist/` is gitignored,
# and only `npm run build` creates it — so the mount is simply absent and Vite
# serves the UI on its own port, proxying `/api` back here.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
