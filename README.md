# Financial-model-analyse — Stock Analysis Platform

A local website for tracking stocks, explaining price moves with news, chatting with a
local AI financial expert, and running investment-banking financial models — powered by
the methodology in [docs/financial-models-reference.md](docs/financial-models-reference.md).

## Architecture

```
React (localhost:5173)  ──►  FastAPI (localhost:8000)  ──►  yfinance (today) / OpenBB (later)
      │                            │
      │  Tab 1: Tracker            └──►  Ollama (localhost:11434) — local AI, optional
      │  Tab 2: Financial Models
```

- **Tab 1 — Tracker**: candlestick chart (any period, US + HK tickers like `AAPL`, `0700.HK`).
  Gold dots mark dates with news; hovering the chart pops up the stories near that date.
  "AI outlook" generates a past/present/future analysis; the chat box talks to your local
  AI, which is grounded in the financial-models reference document plus live data for the
  loaded ticker.
- **Tab 2 — Financial Models**: pulls the company's financial reports automatically and runs
  a 5-year FCFF DCF (editable growth / terminal growth / WACC, with a sensitivity grid,
  anchored to analyst consensus growth when available), ratio analysis, DuPont ROE
  decomposition, valuation multiples, and revenue trend.
- **Tab 3 — Scorecard**: deterministic 0–100 score and S/A/B/C/D tier per company, built
  from five pillars (Valuation, Quality, Health, Growth, Momentum) weighted by a sector
  library ([backend/sector_weights.py](backend/sector_weights.py) — banks, REITs,
  pre-profit companies get substituted metrics). Includes a valuation-range "football
  field" (DCF vs peer multiples vs analyst targets), an editable peer-comparison table,
  and an optional AI-written explanation of the score. Design rationale:
  [docs/scoring-system-design.md](docs/scoring-system-design.md). Validation:
  `backend\.venv\Scripts\python.exe backend\test_scoring.py`.

All AI features degrade gracefully: until Ollama is installed the site shows an
"AI offline" notice and everything else keeps working.

## Run it

Double-click **`start.bat`** (or run `.\start.ps1` from PowerShell).

or manually, in two terminals:

```powershell
# terminal 1 — backend
backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --port 8000

# terminal 2 — frontend
cd frontend; npm run dev
```

Then open http://localhost:5173.

---

## Install guidance (on hold — do these when ready)

Your machine: **15.6 GB RAM, Intel Iris Xe (no dedicated GPU), i7-1355U, 747 GB free disk.**
Disk is not a constraint; RAM and CPU-only inference are what size the choices below.

### 1. Local AI — Ollama

| | |
|---|---|
| Download | https://ollama.com/download/windows (~1 GB installer, installs to `C:\Users\<user>\AppData\Local\Programs\Ollama`) |
| Model storage | `C:\Users\<user>\.ollama\models` — change by setting the `OLLAMA_MODELS` environment variable before first pull |
| Recommended model | `qwen2.5:7b-instruct` — ~4.7 GB disk, ~6–8 GB RAM while running. Best quality/speed balance for finance reasoning on your CPU (expect ~5–10 tokens/sec). |
| Faster fallback | `qwen2.5:3b-instruct` (~2 GB) if the 7B feels too slow — noticeably weaker analysis. |
| Avoid | Anything ≥ 13B — will swap on 16 GB RAM and crawl. |

Steps:
```powershell
# after installing the Ollama app:
ollama pull qwen2.5:7b-instruct
```
That's it — the backend polls `localhost:11434` and the website's chat + AI outlook
activate automatically (green dot in the chat panel). To use a different model, change
`MODEL` at the top of [backend/ai_client.py](backend/ai_client.py).

### 2. OpenBB Platform

| | |
|---|---|
| Install | `backend\.venv\Scripts\python.exe -m pip install openbb` (~2 GB with dependencies, into the existing venv — no new environment needed) |
| Free providers | yfinance (no key), FMP / Tiingo / Polygon free tiers (need free API keys, stored via `obb.user.credentials`) |
| When it's worth it | Deeper fundamentals history, analyst estimates, economy/macro data, and **historical news** (yfinance only returns ~10 recent stories, so hover-news is sparse on older dates — OpenBB providers fix this) |

To switch the website to OpenBB: implement `OpenBBProvider` with the same four methods as
`YFinanceProvider` in [backend/data_provider.py](backend/data_provider.py) and swap the
last line (`provider = ...`). Nothing else in the app changes. The endpoint mapping for
every model input is already documented in
[docs/financial-models-reference.md](docs/financial-models-reference.md) (Section 6).

---

## Notes & limitations

- News hover coverage is limited to the ~10 most recent stories per ticker until OpenBB
  (or another news provider) is installed.
- The default DCF assumptions are deliberately conservative heuristics (CAPM cost of
  equity, revenue-growth-capped FCF growth). Always sanity-check with the sensitivity
  grid and the editable assumptions.
- Everything runs locally; nothing is sent to any cloud service.
- **Decision support only — not certified financial advice.**
