"""Local AI (Ollama) client.

Talks to Ollama's HTTP API on localhost. Degrades gracefully: every call
first checks availability so the website can show an 'AI offline' state
until Ollama is installed (see README for install guidance).
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5:7b-instruct"  # good finance/reasoning quality at CPU-friendly size
REFERENCE_DOC = Path(__file__).resolve().parent.parent / "docs" / "financial-models-reference.md"
REFERENCE_CHAR_BUDGET = 16000  # keep system prompt within a 7-8B model's context

_SYSTEM_PROMPT = (
    "You are a professional financial analyst assistant specialized in investment-"
    "banking valuation models. Ground every answer in the methodology excerpts "
    "provided below and in the live market data given per request. Always give "
    "ranges rather than point estimates, state your assumptions, and end "
    "predictions with a reminder that this is decision support, not certified "
    "financial advice.\n\n"
)


def _reference_excerpt() -> str:
    try:
        text = REFERENCE_DOC.read_text(encoding="utf-8")
        return text[:REFERENCE_CHAR_BUDGET]
    except OSError:
        return ""


def status() -> dict:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"online": True, "models": models, "configured_model": MODEL,
                "model_ready": any(m.startswith(MODEL.split(":")[0]) for m in models)}
    except requests.RequestException:
        return {"online": False, "models": [], "configured_model": MODEL, "model_ready": False}


def chat(messages: list[dict], context: str = "") -> dict:
    """messages: [{role: user|assistant, content: str}, ...]"""
    st = status()
    if not st["online"]:
        return {"error": "ollama_offline",
                "message": "Local AI is not running. Install/start Ollama first (see README)."}
    system = _SYSTEM_PROMPT + "## Methodology reference (excerpt)\n" + _reference_excerpt()
    if context:
        system += "\n\n## Live data for this conversation\n" + context
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": MODEL, "stream": False,
                  "messages": [{"role": "system", "content": system}] + messages},
            timeout=300,
        )
        r.raise_for_status()
        return {"reply": r.json()["message"]["content"]}
    except requests.RequestException as e:
        return {"error": "ollama_error", "message": str(e)}


def predict(ticker: str, quote: dict, history_tail: list[dict],
            news: list[dict], analysis: dict) -> dict:
    """One-shot outlook summary for the tracker tab."""
    context = json.dumps({
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
    }, default=str)
    prompt = (
        f"Analyze {ticker}. Using the live data provided in the system context: "
        "1) summarize how the stock got to its current price (past), "
        "2) assess whether it looks under/over/fairly valued right now (present), "
        "3) give a bull/base/bear outlook for the next 6-12 months with the key "
        "drivers and risks (future). Be concise — under 400 words."
    )
    return chat([{"role": "user", "content": prompt}], context=context)
