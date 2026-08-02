# Changelog

Notable changes to the Stock Analysis Platform. Newest first.

Format note: entries record *what changed and why it mattered*, with the measured
before/after where a change moved numbers the UI displays.

---

## 2026-08-02 — OpenBB installed; DCF correctness fixes

### Fixed

- **Momentum pillar was silently dropped from every scorecard.**
  `get_fundamentals()` whitelists the `info` fields it forwards, and five momentum
  inputs were missing: `twoHundredDayAverage`, `fiftyTwoWeekLow`, `fiftyTwoWeekHigh`,
  `52WeekChange`, `SandP52WeekChange`. Only 1 of pillar M's 4 metrics survived, so
  `available_fraction` (0.25) fell below the 0.4 threshold, `insufficient` was set, and
  the pillar's **15% weight was redistributed away** on every company.
  The bar shown in the UI came from `analyst_upside` alone and was badly unrepresentative
  — 0700.HK displayed momentum **97** while down 13.6% over 52 weeks.
  Verified all five fields are present for US and HK tickers alike.
  *Impact:* coverage 89–92% → **100%**, zero missing metrics. Composite moved −5 to +3;
  AAPL and KO crossed B → A. `backend/data_provider.py`

- **DCF base free cash flow could be off by 4x.**
  `dcf_valuation()` preferred `info["freeCashflow"]`, which yfinance reports annually for
  some issuers and quarterly for others — MSFT returned 16.4 B against a statement figure
  of 67.0 B (0.24x), rescaling the whole valuation. The statement is now the primary
  source and `info["freeCashflow"]` the fallback, recorded in `assumptions.fcf_source`.
  Added `_statement_fcf()`, which takes both legs from the **same** period; the previous
  fallback used two independent `_latest()` lookups and could pair this year's operating
  cash flow with last year's CapEx.
  *Impact:* MSFT fair value 37.57 → **166.50**; NVDA 25.84 → **50.59**;
  0700.HK 341.07 → **462.05** (upside −28.2% → −2.8%, scorecard 68 → 71).
  `backend/financial_models.py`

- **Risk-free rate was a hardcoded 4.3%**, ~38 bp stale against the actual US 10Y (4.68%).
  `_wacc()` now calls `data_provider.risk_free_rate()`, and reports the rate used in
  `assumptions.risk_free_rate`. `backend/financial_models.py`, `backend/data_provider.py`

- Provider interface was documented as "four methods" in both the module docstring and the
  README; it is **five** — omitting `get_peer_snapshot` would break the comps table and
  football field. `backend/data_provider.py`, `README.md`

### Added

- `risk_free_rate(fallback)` in `backend/data_provider.py` — US 10Y treasury yield via
  `obb.fixedincome.government.treasury_rates(provider="federal_reserve")`. Free, no API
  key. Cached once per calendar day; **failures are not cached**, so it resumes live rates
  as soon as connectivity returns. Sanity band `0 < rate < 0.25` guards against a provider
  switching to percent units. The `openbb` import is deferred into the function: backend
  startup stays at 1.3 s and only the first request that runs a DCF pays the ~4 s import.

- `backend/requirements.lock.txt` — 43 packages, the pre-OpenBB state. This is the rollback
  target if the `fastapi`/`uvicorn` downgrade ever causes trouble.
- `backend/requirements.post-openbb.txt` — 107 packages, the current state.

### Changed

- **OpenBB Platform 4.7.2 installed** into the existing venv: 41 MB, 66 wheels, no sdists
  (so no C compiler needed), on Python 3.14.6. Downgraded `fastapi` 0.141.1 → 0.136.3 and
  `uvicorn` 0.52.0 → 0.40.0; `pandas`, `numpy`, `pydantic` and `yfinance` were untouched.
  Verified after install: `pip check` clean, backend serves `/api/health` and
  `/api/score/AAPL`, `wacc_override` still honoured, football field intact, zero 500s.

- README corrected on three points that were **factually wrong**:
  the install size (~2 GB → 41 MB), the claim that OpenBB fixes sparse historical news
  (false on the free tier), and the claim that value turnover "becomes available with
  OpenBB" (unverified, now stated as not implemented).

### Investigated — no code change

- **Historical news is paywalled on both free tiers.** Verified by raw HTTP against each
  vendor, bypassing OpenBB: Tiingo `403 {"detail":"You do not have permission to access
  the News API"}`, FMP `402 Restricted Endpoint: not available under your current
  subscription`. Both keys are valid — the same keys return `200` on
  `tiingo/daily/AAPL/prices` and `fmp/stable/stock-peers`. **403/402 is a plan-entitlement
  refusal, not an authentication failure**; a bad key returns 401, which never occurred.
  Matches both vendors' published pricing (Tiingo News ✗ on free; FMP news starts at
  Starter $22/mo).

- **Caching layer deliberately deferred.** Installing OpenBB consumes no API quota, so it
  was not a prerequisite, and a cache actively obstructs integration debugging — you edit
  provider code, refresh, and get stale results. The correct trigger is the first
  FMP-backed endpoint going into the request path. See `TODOLIST.md`.

---

## 2026-07-31 — Initial platform

- FastAPI backend + React (Vite) frontend, three tabs: Tracker, Financial Models, Scorecard.
- yfinance data adapter behind a five-method `provider` interface.
- 5-year FCFF DCF with sensitivity grid, ratio analysis, DuPont decomposition, peer comps,
  football-field valuation ranges.
- Deterministic 0–100 scoring engine with a sector weight library and coverage-aware
  pillar weighting.
- Optional local AI (Ollama) for chat, outlook and scorecard narration — degrades to an
  "AI offline" state when absent.
