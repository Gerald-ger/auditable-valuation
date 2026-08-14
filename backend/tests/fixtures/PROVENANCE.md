# Fixture provenance

These files are **captured third-party data, not authored content**, and are therefore not
covered by the repository's AGPL-3.0 licence.

| | |
|---|---|
| Source | Yahoo Finance, retrieved through [yfinance](https://github.com/ranaroussi/yfinance) |
| Captured by | [`backend/tests/capture_fixtures.py`](../capture_fixtures.py) |
| Captured on | fundamentals **2026-08-10**, weekly bars **2026-08-14** |
| Size | 424 KB across 16 files |

## What is here

**Fundamentals** (7 files) — one `get_fundamentals` payload per ticker: `income_statement`,
`balance_sheet`, `cash_flow`, `estimates`, and a whitelisted 47-key `info` dict.

`AAPL` · `MSFT` · `JPM` · `O` · `XOM` · `RIVN` · `0700_HK`

**Bars** (`bars/`, 9 files) — weekly closes only, thinned to `{time, close}`, ~261 rows each.
The same seven tickers plus `_GSPC` (S&P 500) and `_HSI` (Hang Seng) as regression benchmarks
for the beta and relative-strength calculations.

## Why they are committed

Each ticker is here because it exercises a distinct branch of `sector_weights.classify` —
technology, bank, REIT, energy, pre-profit and the Hong Kong / non-USD reporting path.
Regenerating with different names would silently stop testing those branches.

Committing them is what lets the 408-test backend suite run **entirely offline**, in CI on a
clean runner, with no network access and no API key. `pytest.ini` deselects the 16
`network`-marked tests by default for the same reason.

## Standing

This is factual market and financial-statement data — prices, reported line items, ratios —
which is not itself copyrightable subject matter in the United States. No personal data is
present: `companyOfficers`, `longBusinessSummary`, addresses, phone numbers and employee
counts are excluded by the `get_fundamentals` whitelist, and no news content is stored.

That said, **yfinance is documented personal-use-only** and Yahoo's terms address automated
access and redistribution. The position taken, and why no free redistribution-clean
alternative covers Hong Kong, is set out in
[`docs/data-sources-review.md`](../../../docs/data-sources-review.md) §3. If you are
re-publishing this repository or hosting it as a service, read that first.

Regenerate with:

```powershell
backend\.venv\Scripts\python.exe backend\tests\capture_fixtures.py
```
