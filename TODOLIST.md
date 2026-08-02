# TODO

Open work, ranked. Each item records the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated.

Status: 🔴 open bug · 🟡 improvement · 🔵 decision needed · ⚪ deliberately deferred

---

## Now

### 🔴 Scorecard hides that a pillar was excluded from the composite

[frontend/src/components/ScorecardTab.jsx:11](frontend/src/components/ScorecardTab.jsx#L11)
checks `data.score === null`, but a pillar can have a real score *and* `insufficient: true`
— in which case the composite drops it while the UI still draws a full-width bar. The user
sees a pillar scored 97 and a composite that cannot be reconciled with it.

The momentum fix (2026-08-02) makes all pillars 100%-covered for normal tickers, so this
path is rare now, but it still fires on genuinely sparse names.
**Fix:** also branch on `data.insufficient`. ~3 lines.

### 🟡 Peer suggestions cover only 21 tickers

[backend/comps.py:12](backend/comps.py#L12) is a hand-curated map; every other ticker gets
an empty list, so the comps table and one football-field bar are missing.

`obb.equity.compare.peers(provider="fmp")` works on the free tier **and covers HK**, but
its quality is inconsistent — measured 2026-08-02:

| Ticker | Curated | FMP |
|---|---|---|
| UPS | FDX, GXO, CHRW, EXPD ✅ | HWM, GD, MMM, WM ❌ generic industrials |
| 0700.HK | 9988, 3690, 9999, 1024 ✅ | 9888, 1024, 1698, 1357 ⚠️ obscure small caps |
| ASML | *(none)* | MU, AMD, AMAT, LRCX, KLAC ✅ |
| SHOP | *(none)* | AMAT, LRCX, ANET, SAP ❌ |

**Design:** curated map first, FMP only as fallback. Never degrades the 21 curated names;
turns "nothing" into "usually usable" for the rest. The peer box in the UI is already
editable, so bad auto-peers are visible and correctable.

### 🟡 Commit the pending work

`backend/data_provider.py`, `backend/financial_models.py`, `README.md` and the two
requirements files are modified/untracked and unreviewed by git.

---

## Next

### 🔴 No caching — Scorecard costs ~8 yfinance fetches per load

`/api/score/{t}` and `/api/stock/{t}/comps` each call `get_fundamentals(ticker)`, so the
**same ticker is fetched twice within one page load**, plus 4 peer snapshots. Each
`yf.Ticker().info` is a full scrape and yfinance throttles bursts.

**Trigger: the first FMP-backed endpoint entering the request path.** FMP free is 250
calls/day and this pattern would exhaust it. Not done earlier on purpose — a cache
obstructs integration debugging (edit provider → refresh → get stale results), and the
TTL is a judgement call (a live tracker tolerates less staleness than a scorecard).
Scope it to `get_fundamentals` + `get_peer_snapshot`; leave `get_quote` uncached.

### 🔴 `full_analysis()` is not guarded

[backend/main.py:66](backend/main.py#L66) wraps `get_fundamentals` in `_guard` but not the
model layer, so an exception there surfaces as a bare 500 instead of a 502 with a message.

### 🟡 Local AI blocks a threadpool worker for up to 300 s

[backend/ai_client.py](backend/ai_client.py) posts synchronously and every endpoint is
`def`, so uvicorn runs them in its threadpool. A 7B model on CPU takes 60–180 s per reply;
chat + outlook + narrative at once will feel stuck. **Trigger: after Ollama is installed**
— there is nothing to measure until then. Fix is streaming (`"stream": true`) plus an
async endpoint.

### 🟡 No CI

`.github/` is empty and [backend/test_scoring.py](backend/test_scoring.py) is an assert
script, not pytest — it must be run by hand and its live-network section fails offline.
Convert to pytest, mark the network tests, add a workflow.

### 🟡 Cosmetic

- [frontend/src/components/ModelsTab.jsx:128](frontend/src/components/ModelsTab.jsx#L128) —
  `dcf.upside_pct >= 0` is `true` when the value is `null`, so an unavailable upside renders
  green.
- [backend/scoring.py:176](backend/scoring.py#L176) — `equity_multiplier = None` is
  overwritten on the next line.
- `assumptions.fcf_source` and `assumptions.risk_free_rate` are returned by the API but not
  surfaced in the DCF panel; showing them would make the valuation auditable at a glance.

---

## Decisions needed (not bugs — your call)

### 🔵 HK stocks are benchmarked against the S&P 500

`rel_52w_change = 52WeekChange − SandP52WeekChange` treats every ticker as US.
0700.HK (−13.6%) is scored against the S&P (+18.3%) for a −31.9% relative reading.
[docs/scoring-system-design.md:89](docs/scoring-system-design.md#L89) specifies this
formula and flags a sector-ETF-relative upgrade as future work.
**Options:** keep as "relative to global equity", or benchmark HK names to `^HSI`
(costs one extra fetch). Investment judgement, not correctness.

### 🔵 HK stocks use the USD risk-free rate

`_wacc()` applies the US 10Y to HK issuers. The HKD peg makes this defensible but not
correct. A HKD government-bond yield would be the right input.

### 🔵 Historical news — pay, work around, or drop

Measured 2026-08-02 (details in `CHANGELOG.md`):

| Option | Cost | Depth | HK |
|---|---|---|---|
| Tiingo paid | plan-dependent | ~7 months backfill only | ❌ |
| FMP Starter | $22/mo billed annually | unknown, untested | ❌ US-only |
| **SEC filings** (`provider="sec"`) | **$0, no key** | **2.5 y** (AAPL: 200 filings, 8-K/10-Q/Form 4) | ❌ US-only |
| status quo (yfinance) | $0 | ~10 recent stories | ~same |

**No option on this list solves HK news.** That needs a non-OpenBB source (AAStocks,
ET Net, or similar) and is a separate project.

SEC filings are the only free improvement, but they are a **new feature, not a data-source
swap** — 8-K/10-Q are regulatory events, not headlines, and the chart's COMPANY/MACRO tags
would need a third category. Decide whether you want that before it gets built.

---

## Deliberately not doing

### ⚪ Full `get_fundamentals` migration to OpenBB

The `info` dict carries ~42 fields that yfinance returns in one call. OpenBB has no
equivalent single endpoint — it would take `equity.profile` + `fundamental.metrics` +
`price.quote` + `estimates.consensus` stitched together, with different field names
throughout, and `fundamental.income/balance/cash` are `402` on the FMP free tier anyway.
High risk, no measured gain. yfinance stays the fundamentals source.

### ⚪ `get_history` migration to Tiingo

Works on the free tier, but returns materially the same bars as yfinance for this app's
purposes. No reason to spend the quota.

### ⚪ Rewriting the curated peer map

FMP peers are worse than the curated list where the list exists (see above). Keep both.
