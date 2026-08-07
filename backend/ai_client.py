"""Local AI (Ollama) client — async, streaming, reproducible.

Three deliberate properties:

1. **Async.** Every call goes over aiohttp inside `async def` endpoints. The old
   client posted synchronously with a 300 s timeout from a `def` endpoint, so a
   single reply parked a uvicorn threadpool worker for minutes and three
   concurrent AI features made the whole site feel dead.

2. **Reproducible.** `temperature: 0` plus a fixed `seed`. Ollama defaults to
   temperature 0.8, which meant the same question produced a different answer
   every time — unacceptable next to a deterministic scoring engine.

3. **Adversarial.** `stream_debate` runs bull → bear → verdict as three separate
   passes, each seeing the previous ones, instead of asking one model to hold
   all three views at once. Disagreement is surfaced, not averaged away.

The LLM still never computes or changes a number; it only argues over figures
supplied in the context.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import aiohttp

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b-instruct"  # good finance/reasoning quality at CPU-friendly size
REFERENCE_DOC = Path(__file__).resolve().parent.parent / "docs" / "financial-models-reference.md"
REFERENCE_CHAR_BUDGET = 16000  # keep system prompt within a 7-8B model's context

# Determinism: the scoring engine is exactly reproducible, so the commentary on
# it should be too. seed is arbitrary but must stay fixed to keep it that way.
OPTIONS = {"temperature": 0, "seed": 7, "top_p": 1.0}

STATUS_TIMEOUT_S = 2
# A 7B model on CPU emits its first token slowly; cap the gap *between* tokens
# rather than the total, so long answers are not truncated mid-sentence.
READ_TIMEOUT_S = 300

_SYSTEM_PROMPT = (
    "You are a professional financial analyst assistant specialized in investment-"
    "banking valuation models. Ground every answer in the methodology excerpts "
    "provided below and in the live market data given per request. Always give "
    "ranges rather than point estimates, state your assumptions, and end "
    "predictions with a reminder that this is decision support, not certified "
    "financial advice.\n\n"
    "If the context contains `user_chart_drawings`, those lines were drawn by "
    "the user on the price chart — they are the user's own claim about where a "
    "level sits, not a level this system derived. Their geometry (price on the "
    "line today, slope, how many bars touched it, whether price is above or "
    "below) has been computed for you and is accurate. Discuss whether the "
    "evidence supports the line, say so plainly when it does not, and never "
    "present a drawn level as a model output. Do not compute new prices; use "
    "only the figures supplied.\n\n"
)


class AIUnavailable(RuntimeError):
    """Ollama is not running, or the request to it failed."""


def _reference_excerpt() -> str:
    try:
        text = REFERENCE_DOC.read_text(encoding="utf-8")
        return text[:REFERENCE_CHAR_BUDGET]
    except OSError:
        return ""


def _system_prompt(context: str) -> str:
    system = _SYSTEM_PROMPT + "## Methodology reference (excerpt)\n" + _reference_excerpt()
    if context:
        system += "\n\n## Live data for this conversation\n" + context
    return system


async def status() -> dict:
    timeout = aiohttp.ClientTimeout(total=STATUS_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{OLLAMA_URL}/api/tags") as resp:
                resp.raise_for_status()
                body = await resp.json()
    except (aiohttp.ClientError, TimeoutError):
        return {"online": False, "models": [], "configured_model": MODEL, "model_ready": False}
    models = [m["name"] for m in body.get("models", [])]
    return {"online": True, "models": models, "configured_model": MODEL,
            "model_ready": any(m.startswith(MODEL.split(":")[0]) for m in models)}


async def stream_chat(messages: list[dict], context: str = "") -> AsyncIterator[str]:
    """Yield reply text deltas as the model produces them.

    Raises AIUnavailable if Ollama cannot be reached or errors mid-stream.
    """
    payload = {
        "model": MODEL,
        "stream": True,
        "options": OPTIONS,
        "messages": [{"role": "system", "content": _system_prompt(context)}] + messages,
    }
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=READ_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for raw in resp.content:
                    line = raw.strip()
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise AIUnavailable(chunk["error"])
                    delta = (chunk.get("message") or {}).get("content")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        return
    except (aiohttp.ClientError, TimeoutError) as e:
        raise AIUnavailable(
            f"Local AI unreachable ({e}). Install/start Ollama first (see README)."
        ) from e


def outlook_prompt(ticker: str) -> str:
    return (
        f"Analyze {ticker}. Using the live data provided in the system context: "
        "1) summarize how the stock got to its current price (past), "
        "2) assess whether it looks under/over/fairly valued right now (present), "
        "3) give a bull/base/bear outlook for the next 6-12 months with the key "
        "drivers and risks (future). Be concise — under 400 words."
    )


def outlook_context(quote: dict, history_tail: list[dict],
                    news: list[dict], analysis: dict,
                    drawings: dict | None = None) -> str:
    """Everything the model may talk about, already computed.

    `drawings` is kept in its own key rather than folded into `model_outputs`
    on purpose: those are engine results, a drawing is the user's own assertion
    about the chart, and the two must not read as the same kind of thing.
    """
    context = {
        "quote": quote,
        "recent_prices_last_30_bars": history_tail,
        "recent_news_headlines": [
            {"date": n["date"], "title": n["title"]} for n in news[:15]
        ],
        "model_outputs": {
            "dcf": analysis.get("dcf"),
            "key_ratios": analysis.get("ratios", {}).get("market"),
            "analyst_target_mean": analysis.get("company", {}).get("targetMeanPrice"),
        },
    }
    if drawings and drawings.get("count"):
        context["user_chart_drawings"] = drawings
    return json.dumps(context, default=str)


NARRATIVE_PROMPT = (
    "You are given a completed company score card. Write 4-6 sentences "
    "explaining the strongest pillar, the weakest pillar, and what any "
    "flags mean. Do not compute or change any numbers. Do not state any "
    "figure not present in the input."
)

# Three passes, not one. Each stage sees the previous stages' text, so the bear
# is attacking a specific argument rather than reciting generic risks.
DEBATE_STAGES: list[tuple[str, str]] = [
    ("bull", "You are the BULL-side analyst for {ticker}. Argue the strongest "
             "honest case FOR owning this stock, using only figures present in "
             "the system context. Cite the specific metrics that support you. "
             "Under 250 words. Do not hedge — the bear will answer you."),
    ("bear", "You are the BEAR-side analyst for {ticker}. The bull case is in the "
             "debate transcript below. Attack its weakest assumptions specifically "
             "— name which metric or claim you think is fragile and why. Add the "
             "risks the bull ignored. Use only figures present in the system "
             "context. Under 250 words."),
    ("verdict", "You are the portfolio manager for {ticker}. Both sides have argued "
                "below. Do NOT split the difference. State: (1) which side carried "
                "the stronger evidence and why, (2) the single assumption the whole "
                "thesis rests on, (3) what specific, observable development would "
                "change your mind. Under 200 words. End with the reminder that this "
                "is decision support, not certified financial advice."),
]


async def stream_debate(ticker: str, context: str) -> AsyncIterator[tuple[str, str]]:
    """Yield (stage, text_delta) across the bull → bear → verdict passes."""
    transcript: list[str] = []
    for stage, instruction in DEBATE_STAGES:
        prompt = instruction.format(ticker=ticker)
        if transcript:
            prompt += "\n\n## Debate transcript so far\n" + "\n\n".join(transcript)
        buffer: list[str] = []
        async for delta in stream_chat([{"role": "user", "content": prompt}], context=context):
            buffer.append(delta)
            yield stage, delta
        transcript.append(f"### {stage.upper()}\n{''.join(buffer).strip()}")
