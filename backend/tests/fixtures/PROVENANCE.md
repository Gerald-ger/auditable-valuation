# Fixture provenance

> ### ⛔ Do not edit this to agree with the fixtures. Check the fixtures.
>
> This file is the only record of what was captured, when, and what was altered by hand
> afterwards — nothing in the repository can reconstruct those facts from the data. So a
> figure here that disagrees with the files is a **finding**, not a typo: read the files
> first, and if they moved without a dated line here saying why, that is the bug.
>
> Adding a fixture means adding a dated line. Re-capturing means recording that it was
> re-captured, because every pinned figure and golden score moves with it.

These files are **captured third-party data, not authored content**, and are therefore not
covered by the repository's AGPL-3.0 licence.

| | |
|---|---|
| Source | Yahoo Finance, retrieved through [yfinance](https://github.com/ranaroussi/yfinance) |
| Captured by | [`backend/tests/capture_fixtures.py`](../capture_fixtures.py) |
| Captured on | fundamentals **2026-08-10**, weekly bars **2026-08-14** — except `0002_HK`, both halves **2026-08-19** |
| Amended | **2026-08-18** — `regularMarketTime` and `exchangeDataDelayedBy` added as `null`; see below |
| Size | 421 KiB across 18 files |

## What is here

**Fundamentals** (8 files) — one `get_fundamentals` payload per ticker: `income_statement`,
`balance_sheet`, `cash_flow`, `estimates`, and a whitelisted `info` dict of the
`data_provider.INFO_KEYS` fields, currently **51**.

`AAPL` · `MSFT` · `JPM` · `O` · `XOM` · `RIVN` · `0700_HK` · `0002_HK`

Two of those 51 are `null` in every file **captured before 2026-08-19** rather than
captured — `0002_HK` came after the fix and carries real values for both, which makes it
the only fixture here with no `null` among those 51. (Its *statements* carry 202 nulls, which is
ordinary rather than universal — across the eight the count runs 58 to 205, since an absent line
item is absent.) `regularMarketTime` and
`exchangeDataDelayedBy` were added to `INFO_KEYS` on 2026-08-14, four days after the
capture, and the fixtures went on being a 49-key subset of a 51-key contract with nothing
able to notice — every test reading either field saw `None` and could not distinguish
"not captured" from "not reported by the vendor". They were added as `null` on 2026-08-18
so the sets match exactly; no other value was touched. `test_fixtures.py` now asserts the
match, so the next field added to `INFO_KEYS` fails the suite instead of passing quietly.
Re-capturing would replace both nulls with real figures, at the cost of moving every
pinned figure and golden score with them.

**Bars** (`bars/`, 10 files) — weekly closes only, thinned to `{time, close}`, ~261 rows each.
The same eight tickers plus `_GSPC` (S&P 500) and `_HSI` (Hang Seng) as regression benchmarks
for the beta and relative-strength calculations.

## Why they are committed

Each ticker is here to exercise a branch of `sector_weights.classify` — the eight resolve to
`technology` (AAPL **and** MSFT), `financials_bank`, `real_estate_reit`, `energy`,
`pre_profit_growth`, `utilities` and `communication_svcs`. Seven branches, not eight: MSFT
doubles up deliberately, because its `info["freeCashflow"]` reports a single quarter and that
FCF-source regression needed a fixture of its own. Regenerating with different names would
silently stop testing these branches.

`0002_HK` (CLP Holdings) carries a second job the others do not: it is the only filer here
that both **reports in HKD** and is eligible for a DCF, so it is what exercises a discount
rate in a currency other than USD. The obvious HKD names cannot — `classify` routes
`sector == "real estate"` and `"bank" in industry` away from the model before the rate is
reached.

Committing them is what lets the 667-test backend suite run **entirely offline**, in CI on a
clean runner, with no network access and no API key. `pytest.ini` deselects the 27
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

That rewrites **every** file above and moves every pinned figure and golden score with them.
To add or refresh one name without disturbing the rest — which is how `0002_HK` was added:

```powershell
backend\.venv\Scripts\python.exe backend\tests\capture_fixtures.py --only 0002.HK
```
