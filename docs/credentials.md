# Credentials

The one credential this platform reads, what OpenBB is actually used for, and the two rate
curves that do not come through it. Split out of the README on 2026-08-28.

**The short version: skipping this is fine.** Without an FMP key you lose automatic peer
discovery and nothing else. The easiest way to add one is the **🔑 API Key** tab in the app,
which verifies the key against FMP before writing anything.

[← back to the README](../README.md)

---

Only one of the four OpenBB calls needs a key: `equity.compare.peers`, which uses
Financial Modeling Prep's free tier. **Skipping this is fine** — peer discovery falls back to
the built-in `PEER_SUGGESTIONS` table in [backend/comps.py](../backend/comps.py) and everything
else runs unchanged.

**The easiest way is the 🔑 API Key tab.** It verifies the key against FMP before writing
anything, keeps everything else in that file, and leaves the previous version as a `.bak` — so
a key that turns out to be wrong costs nothing, and one that is right is confirmed on screen
rather than assumed. The rest of this section is what it does, and how to do it by hand.

To add one by hand: get a free key at https://site.financialmodelingprep.com, then create
`~/.openbb_platform/user_settings.json` (on Windows, `%USERPROFILE%\.openbb_platform\`):

```json
{
  "credentials": {
    "fmp_api_key": "your key here"
  }
}
```

That file lives outside the repo and is never committed. OpenBB 4.7.2 has no
`obb.account.save()`, which is why the tab writes the JSON itself rather than asking OpenBB
to. The other three calls (`treasury_rates`, `equity.search`,
`equity.fundamental.filings`) need no key at all.

`FMP_API_KEY` in the environment works too, and **wins over the file**. Not
`OPENBB_FMP_API_KEY`: OpenBB lower-cases the variable name and matches it against its own
credential fields, so the prefixed spelling lands under `openbb_fmp_api_key` and is never read
as the FMP key.

**How to tell whether it worked.** `GET /api/health` reports it, and the app raises a banner
when — and only when — a key is configured *and* its last real call to FMP failed:

```json
"fmp": { "configured": true, "last_call": "ok" }
```

`configured` answers the setup question (was the file found, is the field name right, is the
JSON valid) without a network request of any kind. `last_call` is `null` until a lookup
actually happens, then `"ok"` or `"failed"` — recorded from calls the app was making anyway, so
it costs no quota. A ticker that genuinely has no peers counts as `"ok"`: the call reached FMP
and FMP answered.

Before this, all six ways of getting it wrong — no file, wrong path, malformed JSON, `fmp_apikey`
instead of `fmp_api_key`, a rejected key, a spent quota — produced exactly the same silence,
because [comps.py](../backend/comps.py)'s FMP tier catches everything and falls through to the
keyless one.

**What OpenBB is actually used for today** — four calls, all on the free tier, all with a
fallback when the fetch fails:

| call | what it feeds | where |
|---|---|---|
| `fixedincome.government.treasury_rates` (`federal_reserve`) | US 10Y yield → CAPM in `_wacc()` for a USD reporter, and the last-resort fallback for the other two currencies; cached once per calendar day, falls back to a constant offline | [backend/data_provider.py](../backend/data_provider.py) |
| `equity.fundamental.filings` (`sec`) | the SEC filing markers on the chart | [backend/data_provider.py](../backend/data_provider.py) |
| `equity.search` (`sec`) | the 10,398-symbol index behind typo-tolerant search; fetched once, cached to disk for 30 days | [backend/search.py](../backend/search.py) |
| `equity.compare.peers` (`fmp`) | the peer set behind peer comps and the re-levered beta | [backend/comps.py](../backend/comps.py) |

So OpenBB is not an optional extra: without it you lose SEC chart depth, typo tolerance
and peer betas as well as the live risk-free rate.

**Two rates do not come through OpenBB.** Since 2026-08-19 a CNY-reporting issuer — `0700.HK`
is the one in the fixture set — is discounted at China's own 10-year rather than America's,
read from ChinaBond's published CGB curve by a direct HTTP call in
[backend/data_provider.py](../backend/data_provider.py). No key, one fetch per calendar day. The
ten-year is picked out by the **column header ChinaBond itself labels `10Y`** rather than by a
tenor in the URL, so a wrong tenor is not something the request can express.

**When ChinaBond does not answer** — which on this machine has meant nine failure episodes
across two days, twice going working-to-dead inside fifteen minutes — the last good reading is served
instead, labelled `cgb_10y_stored_less_spread`, for as long as the yield it came from was
published within a fortnight. That is the same freshness bound a live reading has to satisfy,
so no second judgement enters. Past it, or with nothing stored, it degrades to the US 10Y
labelled `usd_proxy` — what the platform did before any of this existed. Keeping the *currency*
right is worth more than keeping the date right: China's 10-year moves ~22bp across a year,
where the gap to the US one is ~360bp and worth 30% of Tencent's fair value.

The curve itself is fetched at runtime and never committed here — CCDC restricts redistribution
rather than access — and the one cached reading lives in `backend/data/`, which is already
outside the repository.

Since 2026-08-26 an HKD-reporting issuer — `0002.HK` in the fixture set — reads Hong Kong's,
from the daily `.xls` the HKSAR Government publishes at `hkgb.gov.hk`. Same shape: no key, one
fetch per calendar day, a stored fallback bounded by the yield's own published date, and the
tenor found by the label `10-year` rather than by a column position. TODOLIST had this recorded
as blocked on HKMA being unreachable across three attempts; measured 2026-08-26, HKMA answers in
2.6s and its bond-yield endpoint returns `success: true` with 12 of 13 fields null at every date
sampled — alive and empty. The ten-year was published somewhere nobody had looked.

`hkgb.gov.hk` is treated the same way and for the same reason: the workbook asks that the
Government be quoted as owner of the Closing Reference Pricings, so the reading is cached rather
than vendored, in the same directory and equally outside the repository.

**Free-tier reality check** (measured 2026-08-02 with valid Tiingo + FMP free keys, verified
by raw HTTP against both vendors):

| Endpoint | Free tier | Note |
|---|---|---|
| `fixedincome.government.treasury_rates` (`federal_reserve`) | ✅ no key | **wired in** |
| `equity.search` (`sec`) | ✅ no key | **wired in** — the local symbol index |
| `equity.compare.peers` (`fmp`) | ✅ | **wired in**; works for HK too, quality is inconsistent |
| `equity.fundamental.filings` (`sec`) | ✅ no key | **wired in** — ~5 y of dated 8-K/10-Q events, US only |
| `equity.estimates.consensus`, `fundamental.metrics` (`fmp`) | ✅ | yfinance already covers these |
| `equity.price.historical` (`tiingo`) | ✅ | negligible gain over yfinance |
| **`news.company` / `news.world`** | ❌ | Tiingo `403 no permission`; FMP `402 restricted` |
| `estimates.price_target`, `fundamental.income/balance/cash` (`fmp`) | ❌ `402` | yfinance already covers these |

Historical news needs a paid plan — and paying may still not solve it: Tiingo's news API
backfills only ~7 months, and FMP Starter is US-only. **Neither covers HK news at all.**

To swap the whole data layer later: implement `OpenBBProvider` with the same six methods as
`YFinanceProvider` in [backend/data_provider.py](../backend/data_provider.py) — `get_quote`,
`get_history`, `get_news`, `get_peer_snapshot`, `get_filings`, `get_fundamentals` — and swap
the last line (`provider = ...`). Nothing else in the app changes. Miss `get_filings` and
the app still runs, but every SEC marker disappears from the chart. The endpoint mapping for
every model input is documented in
[docs/financial-models-reference.md](financial-models-reference.md) (Section 6); note
that its "free provider" column predates the measurements above.
