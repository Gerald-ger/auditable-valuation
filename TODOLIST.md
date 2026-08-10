# TODO

Open work, ranked. Each item records the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated.

Status: 🔴 open bug · 🟡 improvement · 🔵 decision needed · ⚪ deliberately deferred

---

## Now

### 🔵 The FCFF add-back does not net off interest income

Resolved 2026-08-09 (b) below, with one deliberate gap. The add-back is **gross**
interest, so wherever it fires, the interest *income* still sitting inside operating cash
flow is valued a second time — once through the `EV − net_debt` bridge that already
treats cash as a separately-valued asset, and once as a perpetuity.

Netting it off was rejected on basis-consistency grounds: US filers disclose cash
interest *paid* but no matching cash interest *received*, so netting would mean adding a
cash figure and subtracting an accrual one.

**Currently latent, not active.** XOM is the only fixture the add-back fires on and it
reports no interest income. The first issuer that discloses cash interest paid *and*
earns interest income will activate it. Measured on an accrual basis for comparison, the
effect is worth roughly 3% of FCF on MSFT and AAPL.

**Trigger: a source that discloses cash interest received**, or a decision to accept a
mixed basis.

### 🔵 Two US filers cannot be verified, so they get no FCFF adjustment

AAPL's newest period and all five of MSFT's report no interest row in the cash-flow
statement at all, so there is no evidence of which side of the statement interest sits
on. Both are skipped and flagged `unverified_interest_classification` rather than
guessed at. AAPL does carry `Interest Paid Supplemental Data` in 2023 and earlier — using
it would mean pulling a figure from a different year than the FCF, which is the exact
period-drift this codebase has already fought twice.

**Trigger: a fundamentals source that reports interest paid every period.**

### 🔴 The debate, streaming and every AI reply are unverified end-to-end

Ollama has never been installed on this machine, so `localhost:11434` has never
answered. What *is* verified: all four AI endpoints (`/ai/chat`, `/ai/predict`,
`/score/../narrative`, `/ai/debate`) return a well-formed `ai_unavailable` NDJSON
event, the UI renders it, and nothing hangs or 500s.

What has **never been observed**: token-level streaming, the bull → bear → verdict
staging, whether a 7B model on CPU produces a usable debate at all, and how long
three sequential passes actually take (estimate: 3–9 minutes, untested).

**Trigger: install Ollama.** `ollama pull qwen2.5:7b-instruct`, then run the debate on
AAPL and time it. If three passes are unbearable on CPU, the fix is to make the stage
list configurable rather than to abandon the adversarial structure.

### 🟡 Score history is empty until you use the app

The calibration record starts accumulating from first use — there is no backfill,
because scoring a past date would need point-in-time fundamentals that yfinance does
not expose. A meaningful read on "did S tiers outperform C tiers" needs quarters, not
days. Nothing to do now except use it.

**Trigger: ~2 quarters of rows.** Then write the calibration query (join each score to
the price N months later, bucket by tier) and find out whether the anchor tables in
`scoring.py` mean anything.

### 🔵 The beta credibility band catches extremes, not merely wrong values

`resolve_beta` rejects a beta outside `[0.3, 2.5]`. That caught XOM's 0.173, but a
plausible-looking 0.45 for an oil major would pass straight through. And because
yfinance's energy betas are broken sector-wide (CVX 0.488, COP 0.123, SHEL −0.218,
BP −0.212), peer substitution cannot rescue that sector either — XOM falls through
to the neutral 1.0 default.

Peer betas are now unlevered and re-levered (2026-08-07), which fixes *which*
capital structure the substitute carries but not the band problem: a wrong-but-
plausible input still passes, and a sector-wide break still defeats the peer tier.

**Options:** accept it (the audit row shows the beta and its source, and beta is
inspectable); add a sector-median beta table as a third tier; or compute beta from
price history directly, which is the only real fix and needs 2–5 years of weekly
returns for the stock and its index.

### 🔵 Cross-sectional normalization needs a universe, not a `scoring.py` change

Quant review §6 item 2 (score against the peer *distribution*, not absolute
thresholds) is the right diagnosis and is **blocked on data, not effort**. A
sector z-score or percentile needs a universe to rank within; this app has 21
hand-curated peer entries, ~2.5 s per ticker, and no bulk endpoint. Four peers
cannot produce a percentile.

**Trigger: a data source that can return a sector's constituents in one call.**
Until then the scores stay absolute-anchored, which means they carry market
direction — in a rally every valuation score falls and every momentum score
rises together.

### 🔵 Forensic checks are displayed but not scored

`forensics.py` computes Altman Z, Piotroski F, accruals and net share issuance;
none feed the composite. That was deliberate — folding four more uncalibrated
curves into a composite that has never been validated adds motion, not evidence.

**Trigger: the IC study below.** If tier separation turns out to be real, these
are the first candidates to add; if it does not, nothing should be added to the
composite at all.

---

## Next

### 🟡 The methodology reference is truncated, not retrieved

[backend/ai_client.py](backend/ai_client.py) does `text[:16000]` on a 1,087-line
document, so everything past roughly the first 40% never reaches the model — including
§6 (endpoint mapping) and §7.1 (the model-priority matrix). "Grounded in the
methodology" is therefore only true of the opening sections.

**Fix:** chunk the document and select sections by keyword against the user's question.
**Trigger: after Ollama is installed** — worth measuring whether the 7B model even uses
the excerpt it already gets before building retrieval for it.

### 🟡 Growth sourcing is doing more work than anything else in the DCF

XOM's `growth_rate_year1` is **0.0%**, taken from analyst forward consensus, and it
drives the −55.7% result more than the beta correction does. The input is capped at
25% and floored at 0%, so a company in consensus decline is modelled as flat forever
through stage 1. Cyclicals are exactly where a single-year consensus figure is least
meaningful.

**Trigger: before trusting DCF upside on any cyclical.** Options: use a multi-year
consensus average, use the 3-year revenue CAGR for cyclicals specifically (the
sector profile already knows which they are), or widen the floor to allow decline.

### 🟡 Portfolio totals ignore FX

Holdings in USD and HKD are summed at face value. The UI warns when more than one
currency is present, but the total is wrong, not merely imprecise.
**Trigger: actually holding both.** Needs a rate source; `obb.currency` is free.

### 🟡 Cosmetic

Line references re-verified 2026-08-09.

- A non-existent ticker in the screener returns a row with 0% coverage rather than
  landing in `failed`, because yfinance returns an empty payload instead of raising.
  The row is greyed and unranked, so it is honest, just not obvious. *(Not re-verified
  2026-08-09.)*
- `ScorecardTab.jsx:225` carries an unsuppressed `exhaustive-deps` lint warning on
  `loadComps` (pre-existing, emitted by oxlint on every build). Separately,
  [PriceChart.jsx:398](frontend/src/components/PriceChart.jsx#L398) *disables* the same
  rule on `visibleGroups` deliberately — rebuilding the chart on a marker-filter change
  would discard the user's zoom. (An earlier revision of this list called the
  ScorecardTab warning miscatalogued; the linter does emit it — that claim was wrong.)

**Done since:** `assumptions.fcf_source` and `assumptions.risk_free_rate` are now
surfaced in the DCF panel alongside `beta_source`
([ModelsTab.jsx:164-178](frontend/src/components/ModelsTab.jsx#L164-L178)). The
null-renders-green upside chip and the dead `equity_multiplier = None` line were fixed
2026-08-09 (c).

---

## Decisions needed (not bugs — your call)

### 🔵 HK stocks are benchmarked against the S&P 500

`rel_52w_change = 52WeekChange − SandP52WeekChange` treats every ticker as US.
0700.HK (−13.6%) is scored against the S&P (+18.3%) for a −31.9% relative reading.
[docs/scoring-system-design.md:89](docs/scoring-system-design.md#L89) specifies this
formula and flags a sector-ETF-relative upgrade as future work.
**Options:** keep as "relative to global equity", or benchmark HK names to `^HSI`
(costs one extra fetch). Investment judgement, not correctness.

### 🔵 HK stocks still use the USD risk-free rate, and ERP is flat 5% everywhere

The tax rate is fixed (HKD → 16.5%), but `_wacc()` still applies the US 10Y to HK
issuers and `EQUITY_RISK_PREMIUM = 0.05` is constant across every market and period.
The HKD peg makes the risk-free proxy defensible; a flat global ERP is a simplification
with no such excuse. A HKD government-bond yield and a per-market ERP would be the
correct inputs.

### 🔵 HK charts still have almost no event markers

SEC filings gave US tickers ~5 years of dated events (AAPL: 278 events, 140 dates),
but EDGAR has no CIK for HK listings, so `0700.HK` falls back to the ~10 news dates
yfinance provides. The chart states this rather than looking broken.

**Options:** accept the asymmetry; scrape HKEX news/announcements (they publish a
filings feed, but it is not in OpenBB and would need its own adapter); or drop event
markers for HK entirely so the gap is not implied to be a bug.

### 🟡 Volume pane shows no intermediate axis ticks

Volume now has its own pane and scale, so it can no longer be misread against the
price axis — but lightweight-charts renders only the last-value badge (`49.18M`) in
a pane that short, not tick labels. A custom price formatter was tried and reverted:
it changed the badge format without producing ticks. The value is legible from the
badge and the hover legend, so this is cosmetic.

**Fix if it matters:** a taller volume pane, or a hand-drawn axis overlay.

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

## Done

### ✅ 2026-08-09 (d) — event markers land on the right session, and on the right bar

Two changes, in that order, because the second is pointless on top of the first.

**The marker was on the wrong session.** Events were grouped by the bar's
GMT+8-shifted date while `e.date` arrives from the backend as a UTC date.
`charttime.js` already documents that a shifted US session straddles midnight —
09:30-16:00 ET renders 21:30 on the session's own date through 04:00 the next —
so the second calendar date mapped onto a bar *mid-way through the previous
session*. An event dated D sat three hours into session D-1. Verified before
fixing by evaluating the real function source against synthetic US and HK
sessions. Matching now happens in true UTC, where every US and HK session sits
inside one date; the group's displayed `date` stays chart-space, preserving the
file's stated invariant that axis, popup header and hover legend cannot disagree.
HK was already correct and is unchanged.

**The marker was at the session open.** yfinance's news feed carries a real
publish time — an ISO string or a unix epoch — that `_parse_news` was discarding
with `str(pub)[:10]`. It is now kept as `published_at` (UTC epoch, additive, so
`/news`, the AI context and SEC filings are untouched), and an intraday chart
places a timestamped story on the bar it happened *during*, so the reader sees
the reaction that followed. Stories landing in a gap — after the close, over a
weekend — move to the next bar, matching the existing next-trading-day rule.
Grouping is now keyed on the bar rather than the date, so clustering follows
whatever interval the user picked: identical to before on daily charts, hourly
on an hourly one.

Deliberately not done: netting the two precisions into one look. News has a
time, SEC filings do not, and the dots are identical — so the popup states which
it is (`2026-08-06 22:05` against `2026-08-06 · day only`) and the tooltip says
the timestamp is the publisher's, not the moment the market learned. Adding a
marker shape for it would have collided with the existing size-by-count rule.

`groupEventsByBar`, `toDateStr` and `eventStamp` moved to `src/events.js` — the
same pure-module pattern as `indicators.js` and `charttime.js`. **This is the
first frontend test suite**: vitest, 22 tests, wired into CI, plus 7 backend
tests for the timestamp parsing. Mutation-tested: reverting the timezone match,
the containing-bar rule and the median bar-span each fail only the tests that
own them. The median case initially survived — the fixture's gaps did not
distinguish it from the mean — and a test was added for it.

### ✅ 2026-08-09 (c) — negative denominators no longer score as cheap

Full-calculation audit: DCF engine cross-checked against the closed-form annuity
(agreement to 4e-13), dividend-yield `/100` convention verified as percent on all six
paying fixtures, comps currency and positive-only-median guards verified, forensics
directions verified. Three unguarded sign flips found in `scoring.extract_metrics` —
each mapped distress to the **best** anchor score, because the "lower = better" tables
clip at their left edge:

- **`ev_ebitda`** — negative EBITDA (or negative EV) → ratio ≤ 4 → scored 100.
  Synthetic loss-year energy clone: valuation pillar 50 → 60, composite 68 → 71 —
  three points *gained* for EBITDA going negative.
- **`p_b`** — negative book value was clamped to 0 → scored 100. REIT clone:
  valuation pillar 76 → 82.
- **`roe`** — negative equity with a spuriously positive vendor ROE scored 100, on the
  same card that already carried `debt_equity_skipped_negative_equity` from the same
  negative equity.

All three are now excluded as `None`, following the file's own precedent
(`fcf_conversion`, `net_debt_ebitda`, `debt_equity`), with `roe_skipped_negative_equity`
flagged. Latent — no fixture carries a negative denominator, so the goldens are
byte-identical; like the FCFF fix, the goldens structurally cannot police this, so six
direct tests pin the guards (168 total). Weakening the ev_ebitda guard fails exactly
the two tests that own it. Also fixed in the same pass: the DCF upside chip rendered
green when upside was unavailable (`null >= 0` is `true` in JS), and the dead
`equity_multiplier = None` line.

### ✅ 2026-08-09 (b) — the DCF now discounts an unlevered cash flow

`_statement_fcf` returns `CFO − CapEx`. Under US GAAP interest paid runs through
operating activities, so that is a **levered** measure; discounting it at WACC and then
bridging `EV − net_debt` charged the debt twice and understated equity value.

Three findings changed the shape of the fix:

- **The shared function could not be changed in place.** It has four callers and they
  disagree: `dcf_valuation` needs FCFF, but `scoring.fcf_yield` divides by market cap and
  `scoring.fcf_conversion` divides by net income — both equity-side, both correct
  *levered*. `classify()` only reads the sign. So the add-back went into a new
  `_fcff_interest_addback` used by the DCF alone, and `_statement_fcf` now documents that
  it is levered on purpose.
- **Classification is read from the statement, not assumed.** IFRS permits classifying
  interest paid as financing, in which case operating cash flow is already unlevered and
  an add-back would *overstate* FCFF. 0700.HK reports `Interest Paid Cff` in all four
  captured periods; every US fixture reports `Interest Paid Supplemental Data`. Keying on
  the row that exists means a new IFRS listing is handled without anyone knowing its GAAP.
  Had the naive one-line add-back shipped, it would have moved 0700.HK's upside from
  +30.5% to +38.2% — entirely spurious, and the largest move in the fixture set.
- **Cash, not accrual.** The quantity being adjusted is cash, and the two diverge when
  interest is capitalised: XOM's accrual is 603M against 1,752M paid, a factor of 2.9.

Measured result — the correction fires on exactly one fixture:

| fixture | basis | effect |
|---|---|---|
| XOM | `cash_interest_paid` | upside −53.4% → **−50.3%** |
| 0700.HK | `not_required_interest_in_financing` | unchanged, correctly |
| AAPL, MSFT | `unverified_interest_classification` | unchanged, flagged |
| JPM, O | `no_statement_fcf` | unchanged |
| RIVN | `cash_interest_paid` | still FCF ≤ 0, DCF still declines |

Composite scores and tiers did not move, and **`golden_scores.json` is unchanged** — XOM's
`dcf_upside_pct` was already clipped at the −40 anchor floor, so both values score 0. That
means the goldens are structurally unable to police this, which is why nine direct tests
were added instead. They were mutation-tested: breaking the financing branch fails exactly
three of them.

### ✅ 2026-08-09 (a) — CI had never run the backend job

Runs #1–#4 on `openBB-testing` all failed. Two root causes, the second hidden behind
the first.

- **The runner died before doing any work.** `actions/setup-python@v5` was given
  `cache: pip` with no `cache-dependency-path`, so it globbed for `**/requirements.txt`
  or `**/pyproject.toml`. This repo has neither *name* — the files are
  `backend/requirements-test.txt`, `.lock.txt` and `.post-openbb.txt` — so the action
  errored at step 3 and *Install*, *Lint* and *Test* were all skipped. The frontend job
  was unaffected because it already passed an explicit `cache-dependency-path`; that
  asymmetry inside one file is what gave it away.
- **Then the Test step ran for the first time and aborted during collection.**
  `test_search_and_history.py` imports `main` for `PERIOD_INTERVALS` and `_bars_per_day`;
  `main` imports `fastapi` and `pydantic` at module scope and pulls in `ai_client`, which
  imports `aiohttp`. `requirements-test.txt` listed only pytest, yfinance and pandas.
  Invisible locally, because the dev `.venv` carries the full runtime set.

Fixes: added `cache-dependency-path: backend/requirements-test.txt`, pinned
`ruff==0.15.22` so a future ruff release cannot fail lint on a commit that changed
nothing, and added `fastapi` + `aiohttp` to the test requirements.

Verified by building a venv from `requirements-test.txt` alone, reproducing the exact
`ModuleNotFoundError`, then re-running there after the fix: ruff clean, 153 passed,
8 deselected. CI run #5 green on both jobs.

Also corrected the README's test count: **140 → 153**. The old figure predated
`test_drawings.py`, which contributes exactly the missing 13.

### ✅ 2026-08-07 — comparability, beta methodology, forensic checks

Measured before/after in `CHANGELOG.md`. Acts on quant-review §6 items 1 and 4,
plus four defects found reading the code.

- **Screener ranked across company types** — the one thing in the app that was
  provably wrong rather than merely unvalidated. Now grouped by classification;
  single-member groups are listed, not ranked. Changing only the pillar weights
  to one common ruler had moved three of seven fixture positions.
- **`classify()` read `info["freeCashflow"]`** — the field the codebase had
  already rejected, deciding which *profile* a company gets. Now statement FCF.
  No fixture changed classification; this was latent.
- **Football field used the sensitivity grid's corners** — now 25th–75th per
  reference doc §5.2. Bars roughly halved; 0700.HK's verdict flipped.
- **`analyst_upside` sat in Momentum**, opposing the other three metrics. Moved
  to Valuation. AAPL crosses B→A.
- **Peer betas were a raw levered median** — now unlevered and re-levered to the
  target's own D/E, per reference doc §1.1.2 and the Simply Wall St spec.
- **Added forensic checks** (Altman Z, Piotroski F, accruals, net issuance),
  display-only, with explicit applicability.

Deliberately **not** taken from Simply Wall St: terminal growth = 10Y yield
(would set terminal growth above long-run nominal GDP, which reference doc
§1.1.3 forbids). Not yet taken: Damodaran ERP (needs sourced figures) and the
5-year-average risk-free rate (the free `treasury_rates` call returns 1 year).

### ✅ 2026-08-06 (c) — price chart

Verified in a real browser over CDP, not by inspection. Details in `CHANGELOG.md`.

- **Volume read against the price axis** — the data was correct all along; the
  histogram was overlaid on the price pane with a hidden scale. Volume now has its
  own pane and axis.
- **News dots flashed and were unclickable** — the popup sat under the cursor and
  fought the chart for mouse events. Now a click-through preview plus a click-to-pin
  panel; verified stable on 20/20 jitter samples with a working SEC link.
- **Only 2 dots** — the chart was already drawing everything it had; yfinance gives
  AAPL 3 distinct news dates. SEC filings added 278 events over 140 dates, so a 5-year
  chart went from 2 markers to 142 (62 with insider filings off).
- **Markers required an exact date match** — events on non-trading days produced no
  dot, and the ±3-day popup window disagreed with the dots. Both now snap to the same
  next-trading-bar.
- **No filtering** — per-category chips with live counts; toggling no longer rebuilds
  the chart and loses your zoom.
- **Thin interaction set** — added magnet crosshair, Lin/Log/%, zoom ±, Reset and
  double-click-to-fit.

### ✅ 2026-08-06 (b) — valuation accuracy

Measured before/after in `CHANGELOG.md`.

- **Unvetted beta** — XOM's reported 0.173 swung its upside 79 points. `resolve_beta`
  now bands the reported value and substitutes a peer median (min. 2 credible peers).
- **Flat credit spread** — every issuer paid `rf + 1.5%`. Now a synthetic-rating
  ladder on interest coverage; MSFT 0.6% vs O 3.0%.
- **Single 5-year fade** — replaced with two-stage 5+5. Also cut terminal value from
  72–88% of EV to 51–66%.
- **Terminal value invisible** — now reported with a >75% warning, alongside the
  implied exit EV/EBITDA vs today's multiple.
- **HK taxed at 21%** — now 16.5% via listing currency, in both WACC and ROIC.
- **FCF / net-income period drift** — `_statement_fcf` returns its period and
  `fcf_conversion` is pinned to it.
- **Peers limited to 21 tickers** — FMP fallback behind the curated map; ASML went
  from 0 peers to 4 and its football field from 2 bars to 3.

Checked and found **not** broken, so left alone: interest-expense sign, DuPont period
alignment, `sharesOutstanding` vs `marketCap/price`, and the `revenue_cagr_3y` window.

### ✅ 2026-08-06 (a)

- **Scorecard used the FCF source the DCF fix rejected** — `fcf_yield` and
  `fcf_conversion` read `info["freeCashflow"]` (a single quarter for MSFT/GOOGL). Now
  statement-first with a fallback flag. See `CHANGELOG.md` for measured impact.
- **Scorecard hid that a pillar was excluded from the composite** — `ScorecardTab` now
  branches on `data.insufficient`, not just `score === null`.
- **No caching** — 15-minute TTL on `get_fundamentals` / `get_peer_snapshot`;
  `get_quote` left live. 2.57 s cold → 0.0000 s warm.
- **`full_analysis()` was not guarded** — now wrapped, returns 502 with a message.
- **Local AI blocked a threadpool worker for up to 300 s** — all AI endpoints are async
  and stream NDJSON; blocking calls go through `asyncio.to_thread`.
- **No CI** — ruff + pytest + oxlint + vite build on push and PR. *(Amended 2026-08-09:
  the workflow was added, but its backend job never actually executed until 2026-08-09 —
  see that entry. Only the frontend was protected in between. Recorded as it was
  understood at the time rather than rewritten.)*
- **No memory** — SQLite score history with the price at scoring time.
- **No screening** — Screener tab and `POST /api/score/batch`.
- **No portfolio layer** — Portfolio tab with weights, P&L and concentration.
- **Single-perspective AI** — bull → bear → verdict debate.
- **Irreproducible AI** — `temperature: 0`, fixed seed.

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

### ⚪ HTTP-layer (TestClient) tests

Starlette's `TestClient` needs `httpx`, which is still not installed, and the OpenBB
install already demonstrated that adding packages to this venv can shift
`fastapi`/`uvicorn` versions. The endpoints are thin wrappers over tested functions; they
were smoke-tested live instead. Revisit if the endpoint layer grows real logic.

*(2026-08-09: `fastapi` is now an explicit test requirement, but only because `main` is
imported for two constants — it does not bring `httpx`, so the conclusion is unchanged.)*
