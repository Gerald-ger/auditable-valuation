# TODO

Open work, ranked. Open items record the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated. Entries under *Deliberately not doing* carry no trigger, which is
deliberate: they are settled rather than waiting, and inventing a reopening condition for
them would suggest otherwise. Some of them do name a **reopening condition**, and the test for
whether one belongs is narrow: the entry may name it only when the trigger is a *decision or
event outside this entry* — a data source beginning to carry a field, a second provider being
added, a type checker entering CI. Reconsidering the item **on its own merits** does not
qualify; that is re-litigation, and it is what the rest of the entry exists to prevent. The
distinction is not external-versus-internal but **elsewhere-versus-here**: adding mypy is a
decision, but it is a separate and costly one that nobody makes in order to reopen a `TypedDict`
entry.

*(This clause used to enumerate its exceptions, having already noted that a count "goes stale
every time an entry is added — it already had, twice". Enumerating them was the same mistake in
another form, and it went stale a third time on 2026-08-18 when the migrated entries arrived.
A first attempt at the replacement said those entries carried conditions "that were not data
sources at all", which is half wrong — "a second data provider being added" is exactly a data
source, and only the mypy/pyright one is a different category. Stated as a criterion now, and
the criterion had to be widened rather than the entries excused.)*

Status: 🔴 open bug · 🟡 improvement · 🔵 decision needed · ⚪ deliberately deferred

**Provenance: † marks a live measurement.** Most figures here are reproducible from a checkout —
run the suite, read the fixtures, count the lines. Some are not: they required a network call, a
vendor credential, or both, and a reader cannot re-derive them without the same access. Those
carry a **†** and a date. It is not a confidence marker — a live measurement is often the more
direct evidence — it is a **reproducibility** marker, and it means the figure can go stale
without anything in this repo noticing. Vendor peer lists in particular are unstable: FMP's UPS
peers changed between 2026-08-14 and 2026-08-18 † while the conclusion drawn from them held —
`test_comps.py:714-715` still records the earlier list (HWM, GD, MMM, WM) and the later one
(HWM, GD, **JCI**, MMM) is written down nowhere but here, which is the marker's own point made
against itself.

---

## Now

### 🟡 The WACC debt weight assumes zero, and the two legs cancel by accident *(measured 2026-08-31)*

`financial_models.py`'s `_wacc` reads `(info.get("totalDebt") or 0)` as the debt weight of the
capital structure. It is the **second** reading of that field — `dcf_valuation`'s equity bridge
is the first — and unlike the bridge it has no refusal available: there is no discount rate
that means *unknown*, so a missing balance weights the company as fully equity-financed.

**Decomposed by holding the bridge complete and overriding only the rate** — take the WACC
`_wacc` returns with `totalDebt` removed, then pass it as `wacc_override` to `dcf_valuation`
on the *complete* fixture. **`market_bars=load_market_bars(stem)` on every call**, without
which beta falls back off the regression and the whole table is different — 0002.HK reads
83.83 rather than 234.83. An independent reproduction needed that line and the entry did not
carry it, which for a file whose header promises figures reproducible from a checkout is the
same defect in miniature.

| fixture | fair value | WACC leg alone | | both legs | |
|---|---|---|---|---|---|
| 0002.HK | 234.83 | 205.85 | **−12.3%** | 232.78 | −0.9% |
| 0700.HK | 652.41 | 585.94 | **−10.2%** | 635.49 | −2.6% |
| AAPL | 122.26 | 120.49 | −1.4% | 126.27 | +3.3% |
| MSFT | 219.31 | 212.68 | −3.0% | 230.02 | +4.9% |
| **O** | **27.04** | **33.20** | **+22.8%** | **65.69** | **+142.9%** |
| XOM | 157.30 | 151.55 | −3.7% | 161.78 | +2.8% |

Three things this says. **The sign is not fixed** — it lifts WACC wherever after-tax cost of
debt sits below cost of equity, and lowers it on O, whose 7.30% pre-tax debt exceeds its 6.20%
equity. **The two legs cancel for five of six**, and that cancellation is an accident nobody
chose: 0002.HK is −12.3% on the rate alone and −0.9% once the bridge moves with it. **On O they
compound instead**, because it is both the most levered fixture and the only one with inverted
capital costs.

**Fixed 2026-08-31, but only the reporting half.** The chip in `ModelsTab.jsx` said the field
was "assumed zero in the equity bridge" and stopped there; it now names the discount rate as
well — and only for `total_debt`, because `_wacc` never reads `totalCash` and a missing cash
balance moves the rate by exactly 0.00pp. Two tests, two mutations.

**What was deliberately not done, and why.** Refusing the whole DCF the way a missing market
cap does was rejected on its own precedent: that refusal was justified by a measured **+362% to
+942%** collapse, an order of magnitude above the −12.3% to +22.8% here, so applying the same
remedy would turn a readable bias into no answer at all. Substituting a peer or sector capital
structure was rejected as an assumption with no measurement behind it.

*A correction to how this was first reported: it was described as unflagged. It is not — the
existing `diagnostics.net_debt_assumed_zero` fires and names `total_debt`. What was missing was
that the flag's wording pointed at only one of the two places the field is read.*

**Trigger: evidence that a real issuer omits `totalDebt`.** No committed fixture does, so
nothing here is currently wrong; what is recorded is what happens the first time one is.

### ⚪ ~~A throw in the header blanked the whole app~~ — closed 2026-08-31

`ErrorBoundary` wrapped only the tab body ([App.jsx](frontend/src/App.jsx)), so the title,
the search box and the **tab nav** rendered unprotected. A render throw in React unmounts the
entire tree — which is the exact failure that boundary was written to stop, occurring in the
part of the page it did not cover. The nav is what made it expensive: lose the header and the
reader cannot switch to a tab that still works.

**Scoped to the search box, not the header**, and a mutation proves the scoping rather than
just the code. `<h1>` is a string literal and `<nav>` maps a module constant, so neither can
throw on data; `SearchBar` is the only part of the header that renders a fetched payload and
reads `localStorage`. Wrapping the whole header is *worse* — a search failure would take the
nav down with it, which is the outcome being prevented. Mutation C does exactly that and the
test goes red.

`ErrorBoundary` gained an optional `fallback`, because its default is a panel with a heading,
a paragraph, a stack disclosure and a Try-again button — correct for a tab body, wrong wedged
between the title and the nav. `resetKey={tab}` gives the search box another attempt on the
next tab change, since the compact fallback carries no button.

**Cost: 180 bytes.** Bundle 491.42 → 491.60 kB. Two tests, three mutations, each landing on
exactly the intended test.

### ⚪ ~~Four documented claims that a reader would be misled by~~ — closed 2026-08-31

Found by the desktop verification sweep, ranked by how little work it takes a reader to
catch them out. All four were **corrected in place where the file describes the app**, and
**recorded as `As implemented` notes where the file is a specification** — the two scoring
and reference docs are specs, and editing a spec to match code is what
`docs/financial-models-reference.md`'s own header forbids in as many words.

- **`docs/features.md` — the chart interval table, six of nine rows wrong.** The one a
  reader catches without opening any source: the chart legend prints `bars @ 4h` while the
  doc said 3mo was hourly. 1mo is `1h` not 30-min, 3mo is `4h`, 6mo/1y/2y are `1d` not
  hourly, 5y is `1wk` not daily. The *reason* was wrong too, and more interestingly: the
  Yahoo caps it cited are real and measured, but they bound `3mo at 30m` and `5y at 1h` —
  not "5y and max", which are weekly for a different reason entirely (indicator semantics,
  and a 500-bar cap on monthly responses). Rewritten from `main.py:329-363`'s own comments.
- **`financial-models-reference.md` §1.1.2's `As implemented` note said the opposite of the
  code.** It read "Peer betas are **not** unlevered and re-levered" against a
  `peer_median_relevered` tier that does exactly that, and it predated the regression tier
  that now outranks the vendor figure entirely. This is the worst of the four: a spec body
  going stale is allowed, an `As implemented` note going stale is the mechanism failing.
- **README and `data_provider.py` contradicted `PROVENANCE.md`.** "The eight fixtures are
  eight *sectors*" against PROVENANCE's "Seven branches, not eight: MSFT doubles up
  deliberately". AAPL and MSFT are both `Technology`; it is **8 fixtures, 7 sectors**. The
  wrong sentence had been copied into the code as well.
- **`scoring-system-design.md` documented `tier` as an integer.** §4.3's example response
  shows `"tier": 2`; the engine returns the **letter** `S/A/B/C/D`. A client coded against
  that example breaks — and `test_plausibility.py` already builds a letter-to-number map to
  bridge the same gap, so the repo was working around its own doc. Its anchor tables are
  also printed descending while the engine stores them ascending, which the file's own
  `piecewise_score` pseudocode assumes.

**Three of my own errors were caught by verification and are worth recording**, because two
of them are the same class as the defects being fixed. The `resolve_beta` note first dated
the re-levering to 2026-08-18 — that is when TODOLIST closed an **audit** of it; the code
landed in `7cdb32a` on **2026-08-07**, and reading an audit date as an implementation date is
exactly the drift this entry is about. The same note also omitted the `BETA_MAX` cap and the
**0.0** floor that applies when the regression's confidence interval falls short of
`BETA_MIN` — the second being a policy this session had itself changed hours earlier.

*The reference doc's header percentage moved as a side effect and is corrected with it:
16,000 characters is **19.7%** of the file, not the 21.2% it claimed on 2026-08-26.*

### ⚪ ~~An unreported debt balance scored as a debt-free company~~ — closed 2026-08-31

`scoring.py` read `(total_debt or 0) - (total_cash or 0)` for net debt, and the same
subtraction again for ROIC's invested capital. `or 0` reads "the vendor did not report this"
as "the company has none of it", and the direction is the dangerous one: net debt collapses
to `-cash`, which `max(net_debt, 0)` clamps to **0.0 — the top anchor**.

**Measured across every fixture, and the error scales with the thing being measured.** With
`totalDebt` unreported, the leverage metric scored **100 for all six** fixtures that carry it,
regardless of how levered the company actually is:

| fixture | true reading | true score | scored as | error |
|---|---|---|---|---|
| 0700.HK | 0.0000 | 100 | 100 | +0 |
| AAPL | 0.1307 | 98.7 | 100 | +1.3 |
| MSFT | 0.2685 | 97.3 | 100 | +2.7 |
| XOM | 0.4678 | 95.3 | 100 | +4.7 |
| 0002.HK | 2.6341 | 69.9 | 100 | +30.1 |
| **O** | **5.7151** | **5.7** | **100** | **+94.3** |

The most levered fixture read as the least. And nothing in the output distinguished it from
0700.HK's *genuine* net cash position, which reads 0.0 with both legs reported — which is why
it survived every review until a sweep went looking for this specific coercion.

**This is not the 2026-08-27 audit's entry reopening.** That audit enumerated six `or 0` sites
"on model inputs" and closed them in `financial_models.py` and `comps.py`; `scoring.py` was
never in its scope. `comps.py:635-637` has carried the correct guard — and a comment
explaining it — since 2026-08-30. The fix is that guard arriving in the scoring engine.

**No new flag, which was a correction the verification produced.** The first design appended
one. The nearest precedent is `cash_runway_q`, guarded on *these same two fields*, and
measurement showed it introduces **zero** flags: an absent input is reported through
`missing_metrics`, and the engine's coverage/confidence/reweighting machinery does the rest.
Flags mark something notable that *happened*; absence is not an event.

**Five tests, four mutations, and one of the mutations found a placebo.** Swapping the guard
for a truthiness test left all 807 tests green — `if net_debt` and `if net_debt is not None`
diverge only at exactly zero, and no fixture has debt matched to the dollar by cash. That case
is now constructed and pinned. The golden file is byte-unchanged, which is the point: for
complete data nothing moved.

### ⚪ ~~A CNY reporter inherits China's sovereign yield as its perpetual growth ceiling~~ — closed 2026-08-31

**`financial_models.py:573` has said "See TODOLIST" about this since 2026-08-19 and no entry was
ever written.** The comment reads: *"What keeps it open is the terminal-growth ceiling: a
1.1-1.7% CNY rate also asserts 1.1-1.7% perpetual growth for Tencent."* Every CNY entry that does
exist in this file is about the **discount rate** — closed 2026-08-26 — or about cache staleness
— closed 2026-08-20. The largest single sensitivity measured anywhere in this platform was
flagged in code, referred to a tracker, and the tracker never received it.

All three models take `terminal_growth = min(TERMINAL_GROWTH, risk_free_rate)`
(`financial_models.py:808`, `:1388`, `:1764`). For a USD or HKD reporter the 2.5% side binds and
nothing happens. For a **CNY** reporter the risk-free rate is 1.10% — CGB 1.70% net of the
vendored sovereign spread — and it binds instead. Of the eight fixtures **only 0700.HK is
caught**: 0002.HK reports HKD, whose 3.00% clears 2.5%.

Tencent's own year-one consensus growth is **9.39%**. The model grants it **1.10%** in
perpetuity. Measured 2026-08-30, production path, every input pinned including the exchange rate:

| terminal growth | fair value | vs price | V pillar | composite |
|---|---|---|---|---|
| 1.10% — today, `capped_at_risk_free_rate` | 539.04 | +12.0% | 67 | 73 |
| 2.50% — the platform default, unbound | 652.41 | +35.5% | 72 | 74 |
| 4.00% — `NOMINAL_GDP_GROWTH`, already computed | 880.65 | +82.9% | 75 | 75 |

**A 63.4% swing in fair value, and 2 points of composite.** The score barely moves because the
upside anchor curve saturates above +40%, so this is a defect in the number the Models tab
prints rather than in the ranking — which is an argument about *which* readers it misleads, not
about whether it is one.

**The mechanism was designed for the opposite direction.** The Done entry of 2026-08-06 records
declining Simply Wall St's *terminal growth = 10Y yield* on the grounds it "would set terminal
growth **above** long-run nominal GDP, which reference doc §1.1.3 forbids". That is a ceiling
against too-*high* growth. The CNY curve arrived on **2026-08-19**, after that decision, and
binds from underneath. §1.1.3 itself says only `g_terminal ≤ long-run nominal GDP` — it does not
mention the risk-free rate at all, so the `min(..., rf)` half is this platform's own addition and
dropping it would still satisfy the spec.

**The counter-argument, which is real:** a perpetual growth rate above the risk-free rate claims
a company outgrows government paper forever. Mechanically applying that to a policy-suppressed
domestic curve is the thing in question — not the principle.

**Cost.** Three call sites share the line; five assertions across four test files name
`capped_at_risk_free_rate`; `ModelsTab.jsx` has a display branch for it; `golden_scores.json`
holds `0700_HK` and would need re-baking. Calibrated against this repo's own recent commits
that is a **medium** change — roughly 6-11 files and 100-330 lines, the size of `65450ec`.

**Decision needed, not a trigger:** anchor the ceiling to a long-run nominal growth estimate
independent of the sovereign curve (`NOMINAL_GDP_GROWTH` is already computed and already
published in `terminal_growth_ceilings` as a ceiling it never enforces), or keep the rf cap and
accept that a CNY reporter is valued on a 1.1% perpetuity, or make it currency-conditional.
The measurement above does not choose between them.

**Closed 2026-08-31 — the ceiling is published, not applied.**

Neither of the three options in the paragraph above was taken as written. Anchoring to
`NOMINAL_GDP_GROWTH` alone would have deleted a guard that measurement says is doing real work,
and making it currency-conditional needed a judgment about which sovereign curves read as market
prices — the kind of constant this list refuses to invent, on the same grounds it refused a beta
precision threshold eleven days ago.

**What was measured before choosing.** The `min(..., rf)` half was never in the specification —
§1.1.3 asks only `g ≤ long-run nominal GDP` — but deleting it is not free:

| 10Y | AAPL, ceiling kept | AAPL, ceiling dropped | JPM kept | JPM dropped |
|---|---|---|---|---|
| 4.30% (today) | 122.26 | 122.26 | 330.52 | 330.52 |
| 1.50% | 171.74 | 207.28 | 549.62 | 653.04 |
| **0.60%** | **177.17** | **266.87** | **606.95** | **909.11** |

So the two errors point opposite ways: keeping the ceiling understates a CNY reporter today,
dropping it overstates everything in a low-rate regime — about +50% on both models. No evidence
in this repository decides between them, so neither was chosen. The anchor is the published
answer because the specification asks for it in every rate regime; the ceiling's own reading is
published beside it as `assumptions.terminal_growth_alternative` and rendered by `ModelsTab`.

**Result.** 0700.HK **539.04 → 652.41**, +12.0% → +35.5%, valuation pillar 67 → 72, composite
73 → 74. The golden diff is three lines and no other fixture moves — predicted by two independent
measurements before the edit and confirmed by the diff after it.

**Two corrections this produced.** The entry above says the assertions span "four test files";
there are three. And the specification's warning that an uncapped bank terminal value goes
*negative* does not forbid this change — what prevents the negative is the 2.5% anchor, not the
risk-free half, and JPM at a 0.60% ten-year still has `Re` of 5.07% against a 2.5% perpetuity.
That note has been amended to say which half was load-bearing, because read carelessly it would
have stopped the change for a reason that was not true.

*What is not closed: `NOMINAL_GDP_GROWTH` is a single global 4%, so it is a ceiling that never
binds rather than an economy-specific one. Making it per-economy would change nothing today —
every candidate value sits above the 2.5% anchor — which is why it was not done.*

### 🔵 The valuation-upside metric is scored on one observation *(2026-08-29)*

`valuation_upside_pct` joined the V pillar for `financials_bank` and
`financials_insurance`. The `analyst_upside` note at the top of `sector_weights.py`
sets three tests for adding a scored upside metric. Two are cleared and stated there.
The third is not:

> An undeclared level bias. The curve in scoring.METRIC_ANCHORS scores 0% upside at 45
> [...] the seven fixtures came out at 96/53/52/72/62/83/65 — mean **69** against a
> centred 50. Seven names do not settle the size of the bias [...]

Seven was called insufficient. This metric has **one** — JPM. There is no insurer
fixture, and the one REIT refuses once real market bars are supplied, so the dividend
discount model contributes nothing to the question either. What holds the risk down is
that the curve is `dcf_upside_pct`'s, unchanged and already in use, and that unlike a
published target an intrinsic model has no known reason to sit off-centre. That is an
argument for proceeding, not a measurement.

**Trigger:** a second bank or any insurer fixture. Two observations do not settle it
either, but they are the first point at which the question can be asked at all.

### ⚪ REITs route to a valuation model their scorecard cannot use *(2026-08-29)*

`real_estate_reit` routes to `dividend_discount`, draws its bar on the football field,
and is deliberately **not** given `valuation_upside_pct` in its scoring profile. On O —
the only REIT fixture — the model refuses once `market_bars` are supplied, because a
beta regression of 0.4263 (R² 0.148) puts the cost of equity at 6.20% against a 7.30%
pre-tax cost of debt. Scoring a metric this repository has never observed produce a
value would be adding an unmeasurable input.

Not a defect in the model and not a gap in the routing: the chart and the scorecard
answer separate questions, which is the distinction `VALUATION_MODELS` versus
`SECTOR_PROFILES` exists to keep.

**Reopening condition:** a REIT fixture whose cost of equity clears its own cost of
debt, or a resolution of the CAPM inversion question recorded against the DCF's
`cost_of_equity_below_debt` diagnostic. Both are decisions made elsewhere.

### 🟡 Four things the demo-mode review left open *(2026-08-27)*

The review that produced demo mode found six defects in it; four were fixed in the same
commit. These are the remainder, none of them load-bearing.

- **`backend/store.py` now costs ~1 s to import on its own.** It reads `DEMO_MODE` from
  `data_provider`, which transitively imports `yfinance` — measured with `-X importtime`:
  `store` itself is under 1 ms, `yfinance` is 94% of the ~1 s. **No effect on the running
  app** (`main.py` already imports `data_provider`) or on CI. It would matter to a
  standalone maintenance script that wanted a cheap sqlite wrapper. The alternative is
  parsing `DEMO_MODE` a second time inside `store.py`, which trades one import for two
  places that must agree about the same flag — the trade this project usually refuses.
  *Trigger: a script or tool imports `backend.store` without `data_provider`.*
- ~~**`POST /api/portfolio/position` accepts any ticker with no provider check.**~~
  **Closed 2026-08-31 — the trigger discharged itself.** The reason for leaving it was that
  the message `"TSLA is not one of the demo tickers"` is accurate and actionable and the row
  is the visitor's own to delete. Hosting removed the second half of that sentence without
  touching the first, which is what the trigger — *"the same input reaches a hosted demo,
  where a stranger cannot delete the row"* — was written to notice. Demo mode now calls
  `provider.get_quote` before the write and refuses with a 400 carrying the same message.

  `get_quote` rather than a ticker list, because it is the call the portfolio already makes
  to render the row: what is accepted is exactly what can be priced. **Live mode is
  deliberately not checked**, and a test pins that rather than a comment — a provider call on
  the write path is a network round trip between you and your own record of what you hold, so
  a Yahoo outage would refuse a position that exists. That is a worse failure than the row
  this refuses. Three mutations, each landing on exactly one test: deleting the guard,
  running it in live mode too, and changing the status code.
- **`test_the_demo_rates_are_the_published_readings_not_the_round_test_constants`** pins
  `_demo_cgb_10y()` against the literal it returns. The assertion that earns its place in
  that test is the one comparing the demo constants against `conftest`'s; the rest is a
  one-line function checked against its own body. Fold it into
  `test_the_demo_mode_rate_readings_carry_labels_that_are_true`. *Trigger: the next pass
  over that file.*
- ~~**The GitHub *About* description still says "409 offline tests".**~~ Corrected to 793
  (628 backend + 165 frontend) on 2026-08-27, minutes after this entry was written. Kept
  struck through rather than deleted because the *class* of defect recurs: that line is the
  most-read text in the repo — search results, the sidebar, every link preview — it is
  edited outside git, so no commit ever forces a second look at it, and nothing in CI checks
  it. **It goes stale again on the next commit that adds a test.** *Trigger: any change to
  the suite size.*

  **Fifth recurrence, 2026-08-31 — and this one was caught by the sweep that came looking.**
  `gh repo view` read **1016** against a suite of 1040. Corrected to **1043**, which is the
  number after the three tests the entry above adds: the commit that closed one finding moved
  the count that another finding is about, in the same working tree. That is the cleanest
  demonstration available of why this line cannot be maintained by intention — nothing warned,
  because nothing can. `test_documented_counts.py` caught the *in-repo* half in the same run
  and named all eight stale lines across three files, which is exactly the split it
  predicts: the
  guard reaches everything in git and nothing outside it.

### 🔵 The review's 32 standing findings, none of them written down until now *(2026-08-27)*

> **Re-checked 2026-08-30 against the live repo and GitHub. The count decays faster than the
> entry does, and five sub-findings are already closed:**
>
> - ~~"zero badges"~~ — `README.md:3-6` now carries four (CI, tests, licence, Python 3.12/13/14).
> - ~~"no release"~~ — `gh release list` shows **v0.1.0**, tagged 2026-08-27, *before this entry
>   was written*.
> - ~~"`docs/release-readiness.md` appears only as plain text"~~ — `README.md:37` links it.
>   The other two named in the same bullet are **still unlinked**: `grep` for
>   `currency-consistent-discounting` and `valuation-triangulation-review` in `README.md`
>   returns nothing, and `quant-review-2026-08-06.md` is still plain text at `README.md:407`.
> - `docs/images/social-preview.png` now exists (92,748 bytes, 2026-08-27), though whether it is
>   wired into GitHub's social-preview setting cannot be told from the repo — left open.
> - **The About-description staleness this entry predicted has recurred, and can now be shown
>   rather than argued.** ~~Three numbers for one fact are in circulation right now: GitHub's
>   About says **856 offline tests**, `README.md:4` says **987**, and this entry records having
>   corrected it to **793**.~~ The prediction was "it goes stale again on the next commit that
>   adds a test"; it has gone stale twice more since.
>
>   **Closed later the same day.** All of them now read **1008**, and a test enforces it:
>   `backend/tests/test_documented_counts.py` reads eleven claims out of README, `docs/testing.md`
>   and `backend/tests/fixtures/PROVENANCE.md` and fails naming the file and line of any that
>   drifts. The About was corrected by hand, and **no test can reach it** — it lives outside git.
>   That half of the prediction stands.
>
>   *Struck rather than rewritten because it was a present-tense claim that outlived its own
>   subject: those three numbers really were in circulation when it was written, and were not
>   four hours later. Leaving it unstruck would have made this entry an instance of the defect
>   it is about — which is how it was found, by a sweep looking for exactly that.*
>
> **Confirmed unchanged:** Website field still empty, still 14 topics, no `docs/README.md` index,
> first screen still defaults to Tracker/AAPL (`App.jsx:43-44`), neither start script checks
> `node_modules` (`start.bat:8`), `aria-*` still only in `SearchBar.jsx`.
>
> **And the line-number joke landed a fourth time.** This entry says the exhaustive-deps disable
> "is now at `:366`". It is at **`PriceChart.jsx:716`** — 398 → 344 → 366 → 716 across the file's
> history. Four data points now say the same thing the entry already argues: reference the
> symbol, not the line.

The same four-agent review ran twice today — once before demo mode, once after — and produced
**32 findings about the repo as a stranger meets it**. That is a different axis from the rest of
this file: everything else here asks whether a number is right; these ask whether anyone gets
far enough to see the number.

They lived only in a conversation, which is why the second run could report *0 fixed, 0 worse,
32 unchanged* with nothing having gone wrong in between — there was nothing recorded to act on.
**That is the defect this entry fixes first.** Re-verified against `6a8dd5a` after today's two
commits, so the evidence below is today's rather than the review's. Two are now closed.

**The one thing, if only one gets done — now half done.** Stand up a hosted, zero-install
instance of demo mode, and put the link in the three places a visitor looks: the GitHub
*Website* field (empty today), the first lines of the README, and the CV. It is the only item
that reaches all three audiences at once.

**The mechanism landed 2026-08-27.** `main.py` mounts `frontend/dist` after every route, so one
process serves the API and the UI on one port, and a `Dockerfile` bakes in `DEMO_MODE=1`;
`deploy/huggingface/` carries the two files a Space needs. Verified in a browser: exactly one
origin, zero console errors. The API-base and CORS work this entry predicted turned out to be
**already done** — `api.js` has requested a relative `/api` for months — so nothing was needed
there at all.

**What is left is not code — but the host is now an open question.** Walking through Space
creation on 2026-08-27 turned up the thing that decides it: **Hugging Face gated Docker Spaces
behind PRO** ($9/month) some time in 2026. Gradio too. Only Static Spaces remain free, and a
Static Space cannot run FastAPI. The `deploy/huggingface/` files are therefore for a paid
account, and the free-tier reasoning that picked Hugging Face is dead.

Three replacements, all verified against current terms rather than remembered:

- **Render free tier + a keep-alive.** No credit card, Docker supported, and the `Dockerfile`
  at the root works unchanged. It sleeps after 15 minutes idle and takes 30-50 s to wake — the
  exact failure this entry warns about two paragraphs down. But the free allowance is **750
  hours a month against the 744 a month has**, so a GitHub Actions cron pinging it every ten
  minutes keeps it awake and still inside the free tier. Public-repo Actions are free.
- **Render free tier, plain.** Nothing extra to build; accept the cold start. Fine for an
  engineer who will wait, poor for a recruiter with one click.
- **Hugging Face PRO, $9/month.** Everything already written applies unchanged, and Hugging
  Face is somewhere engineers and AI recruiters already browse — which no generic host is.

*A fourth shape exists and is worth naming: the demo's responses are deterministic, so all
eight tickers could be snapshotted to static JSON and served from GitHub Pages — free, and
with no cold start at all, ever. It costs a snapshot generator, and search and Portfolio writes
would have to degrade, because a static host cannot answer a query string or a POST.*

*Trigger: picking one. The container has still never been built — this machine has no Docker —
so whichever host is chosen, its first build is that Dockerfile's first test.*

**The host was picked 2026-08-31 — Render free tier + an Actions keep-alive — and everything
that can be prepared without a Docker daemon or a Render account now is.**

`render.yaml` (blueprint: free plan, Singapore, `healthCheckPath: /api/health`, `autoDeploy`)
and `.github/workflows/keep-alive.yml` (`*/5` cron against `vars.DEMO_URL`, failing on any
non-200). `DEMO_MODE` is deliberately *not* repeated in the blueprint — the Dockerfile bakes it
and the blueprint pins `dockerfilePath`, so the safety-critical flag keeps one home.

**A blocker was found and fixed, and it would have failed the first deploy.** `CMD` was exec
form with a literal `--port 7860`, which performs no variable expansion — so the container would
always have bound 7860 while Render routed to its injected `$PORT`, booting cleanly and never
going live. It is now `["sh", "-c", "exec python -m uvicorn ... --port ${PORT:-7860}"]`. The
`exec` is the part that is easy to omit: without it `sh` stays PID 1 and swallows SIGTERM, so
every one of the several daily spin-downs would cut in-flight requests instead of closing them.
Proven both ways locally without Docker — `PORT=8797` binds 8797 and answers 200, unset binds
7860, so Spaces keeps working.

**Measured rather than assumed, since the container has still never been built.** The app was
run exactly as Render will run it — `DEMO_MODE=1`, single process, single origin: `/` serves the
built UI, `/api/health` returns 200 with `demo: true`, `0700.HK` values from the fixtures, an
unknown ticker returns a 502 that only a hand-typed URL can reach (search returns `{"results":
[]}` at 200). **131.6 MB working set** after three heavy endpoints, against the free tier's
512 MB, and `openbb` confirmed absent from `sys.modules` — the deferred imports hold.

**Two claims from an independent audit were refuted by measurement, and both are worth
recording.** It called the 107-pin `requirements.txt` install untested by CI: `ci.yml` does
install only the six-entry test set, but `runtime-install.yml` has installed the full set on
3.12, 3.13 *and* 3.14 since 2026-08-28 — `f6af67b` exists precisely to do that, and it passes.
And it called shipping `backend/tests/` unnecessary image weight: `DEMO_DIR` is
`backend/tests/fixtures`, so excluding it would break demo mode outright.

**One audit finding stands, and it should be known before the link is shared.** `ai_client.py`
posts to `http://localhost:11434`; Render's free tier is one container with no sidecar, so every
AI feature — chat, predict, debate, the scorecard narrative — answers 503 permanently. It
degrades cleanly rather than crashing, and `DEMO_MODE` is unrelated to it. Recorded in
`render.yaml` beside the config it constrains.

**What is left needs an account and a browser, not this repository:** create the Render service
from the blueprint, set `DEMO_URL` as an Actions variable, then fill the GitHub *Website* field
and the README. *The Dockerfile's first build is still its first test — that has not changed, it
has only been narrowed to the one thing that cannot be checked from here.*

**Two things to settle before that link goes anywhere.** Free tiers spin down when idle, and a
recruiter's one click landing on a thirty-second cold start is worse than no link at all — so
measure wake latency first. And serving *frozen committed fixtures* is a materially smaller act
than the live-yfinance redistribution the licensing entry under **Decisions needed** calls a
blocker. Smaller, but a different question, and not an answered one.

**A scoping assumption that no longer holds, and would otherwise be inherited in silence.**
`NEXT-STEPS.md` — a local, untracked planning file, so it is not in this repo — deferred the
Dockerfile, the desktop installer and GitHub Releases, and
`.env.example` plus env-var config for API base and CORS — whose trigger is written as *"Any
deployment that is not localhost"* — on 2026-08-14, **"because the audience is portfolio piece
only"**: read, not run. The goal stated on 2026-08-27 is three-part: people using it, stars, and
a CV a banking recruiter may open. That third audience is arguably the *"Non-technical users"*
trigger already written beside "Desktop installer, GitHub Releases". Re-check the decision
deliberately rather than letting the old scope carry by default.

**Promotional — what a visitor sees before deciding to spend any time (8, plus one new).**

- **The differentiator is buried.** [README.md:3-5](README.md) is still plain prose, and the
  sharpest line in the document — *"7.3% here, against an economy that grows 4%"* — is still
  inside the `models.png` caption paragraph at `:32-36`. *Trigger: any rewrite of the first screen.*
- **Zero badges.** `grep -i "badge\|shields.io" README.md` finds nothing. Three of them — CI,
  licence, Python — is about ten minutes. *Trigger: none. It is simply absent.*
- **No release, no custom social preview, no issue templates.** `gh release list` is empty,
  [.github/](.github/) holds only `workflows/ci.yml`, and the `og:image` is still GitHub's
  auto-generated card. *Trigger: the first outside visitor, or the link being posted anywhere.*
- ~~**The About description said "409 offline tests".**~~ Closed 2026-08-27 → 793. The *class*
  of defect recurs, and is recorded in the entry above.
- **14 topics** — unchanged, and the one promotional thing already done right.
- **Five plain screenshots, no hero image and no GIF.** [docs/images/](docs/images/) holds
  exactly five PNGs, and `models.png` — the one showing the actual engine — is **second in the
  README and the smallest file of the five**, 107,407 bytes against tracker's 202,769.
  *Trigger: a hosted demo would make a GIF redundant; rejecting hosting would make one the
  fallback.*
- ~~**Python 3.14 filters out most visitors, and demo mode sits behind that wall.**
  `requires-python = ">=3.14"`~~ — **half closed 2026-08-28.** The floor is now `>=3.12`, which
  is where `numpy==2.5.1` puts it; 3.12 and 3.13 were measured rather than assumed (full 107-pin
  install, 667 tests, and 2,288 API fields identical to 3.14 across eight companies) and both run
  in CI on every push. Ubuntu 24.04 LTS ships 3.12 as its `python3`, so the wall is now roughly
  where a stock LTS install already is. **Still open:** `start-demo.bat` delegates to `start.bat`,
  which hard-fails without an existing venv. *Trigger: a decision to host.*
- **The ceiling stands at low double digits, 50-100 stars.** 2 stars, 0 forks, 0 watchers.
- **New: the GitHub *Website* field is empty.** `homepage: ""` — the slot directly under the
  repo name, in search results, and on the profile. *Trigger: the moment any link exists.*

**Software — what a reader of the code finds (8).**

- **`dcf_valuation` is one 447-line function**, [financial_models.py:701-1147](backend/financial_models.py#L701-L1147).
  *Trigger: a change that has to be made in two places inside it.*
- **`PriceChart.jsx` is 1,262 lines with 19 `useState` and 14 `useRef`.** The count is higher
  than first cited because it was recounted, not because it grew. *Trigger: the CSS-Modules
  entry's trigger, or the first bug needing two of those refs read together.*
- ~~**`ModelsTab` and `ScorecardTab` have no tests.**~~ **Closed 2026-08-27.** Eight tests
  across two new files, pinning the blast radius of a missing number rather than the
  arithmetic: a refused DCF costs its own panel and not the tab, a null upside stays
  uncoloured, an all-insufficient card does not throw past `verdict()`'s guard, and a
  scored-but-excluded pillar reads as excluded. Every mock shape was read out of the running
  engine rather than written from the component's side. `App.test.jsx` still stubs both,
  which is correct — it tests the shell.
- ~~**Drawings PATCH and DELETE ignore `ticker`, and report success for an id that does not
  exist.**~~ **Closed 2026-08-27.** Both store functions now scope on `id AND ticker` and
  return `cur.rowcount == 1`; both endpoints 404 on a miss. Six tests where there were none,
  and the empty-patch branch — every `DrawingPatch` field is optional, so no UPDATE runs and
  no rowcount can answer — checks the id explicitly rather than falling back to claiming
  success. Safe to change the signature because `main.py` was the only caller.
- **`aria-*` appears in exactly one file**, `SearchBar.jsx`. The two `.notice-banner` divs added
  today carry none either. *Trigger: any accessibility claim, or a screen-reader user.*
- ~~**CI runs one OS and one version.**~~ **Closed 2026-08-28.** Both jobs now run a
  three-OS matrix with `fail-fast: false`, so one leg failing does not hide the other two.
  All six legs passed on the first run, macOS included — which had never been run at all, and
  was the one genuine unknown; Windows was low-risk only because it is this machine. Lint and
  the coverage upload stay on ubuntu alone, since three legs would buy the same answer three
  times. Wall clock 37 s → 74 s, not ×3, because the legs run in parallel and the slowest one
  sets the time. Python and Node are still single-valued: no evidence yet says a version
  matrix would find anything, and the OS one is what Windows-only assumptions needed.
- ~~**No coverage measurement anywhere.**~~ **Closed 2026-08-28.** `pytest-cov` and
  `@vitest/coverage-v8`, run in CI on ubuntu and uploaded as artifacts. No threshold and no
  gate: a percentage target is met by exactly the kind of assertion that cannot fail, two of
  which this repo found by mutation on 2026-08-27.

  First reading — **82%** backend, **69.8%** frontend lines. The shape says more than the
  number. The deterministic engine is 96–100% (`scoring` 99, `financial_models` 96,
  `market_series` 100) and every layer around it is thinner: `main.py` 57%, `ai_client.py`
  45%. Four frontend files are at **0%** — `api.js`, `ScreenerTab.jsx`, `ChatBox.jsx`,
  `Debate.jsx`. `api.js` is the one that matters: every network call in the app goes through
  it and every suite mocks it, so nothing has ever executed it. Those four are now a finding
  with a number attached rather than a suspicion. *Trigger for acting on them: unchanged — a
  change to any of the four.*
- ~~**Streaming errors arrive as in-body events under HTTP 200.**~~ **Closed 2026-08-28**,
  for the half that could be closed. `_ndjson` pulls one event before deciding: a failure
  before it is a real 503 (or 500), a failure after it stays an in-body event, because 200 is
  already on the wire by then and HTTP cannot take it back. That asymmetry is not a
  compromise — it is the constraint.

  The half that moved is the one that mattered: `ai_client` raises `AIUnavailable` from the
  `except` around `session.post`, a connection failure before anything is yielded, and that is
  the path every request takes while Ollama is not running. The status is an `HTTPException`
  so the body carries `detail`, which is the key `frontend/src/api.js` already reads — it
  checked `res.ok` all along, so nothing in the UI changed.

  Five tests where these four endpoints had none, mutation-proved both ways: dropping the
  replay of the peeked event fails exactly the two tests about losing the first token,
  dropping the 503 clause fails exactly the one about an unreachable model.

**Structural — how the repo reads as a set of files (9; four actionable).**

- ~~**Four of seven `docs/*.md` are unreachable from the README.**~~ **Closed 2026-08-31.**
  `currency-consistent-discounting.md` and `valuation-triangulation-review.md` — the two at
  **zero** mentions — are now on the *"Deeper than this file goes"* line, which is the
  README's own docs index and therefore the place a reader looks. The FX working being
  unreachable was the sharpest form of this: it is the derivation behind the whole
  currency-consistent discount, and the front page had no route to it.

  The project-structure tree was **separately incomplete** — it enumerated ten of twelve
  `docs/*.md`, omitting the same two, so the file listing did not even assert they existed.
  Both added. The tree is a fenced code block, so its entries cannot be links; that is why
  completeness there and a link on the index line are two fixes rather than one.
  92 relative links across README and all twelve docs re-checked, 0 broken.
- **`docs/quant-review-2026-08-06.md` is entirely Traditional Chinese with no language notice.**
  *Trigger: an English-only reader opening it from the tree.*
- **No `docs/README.md` index** — seven `.md` files and `images/`, nothing to enter by.
  *Trigger: doc number eight.*
- **WORSE: root clutter grew.** 13 tracked root files, **five of them start scripts**.
  Case-insensitively `CHANGELOG.md` still sorts above `LICENSE` and `README.md`, and
  `TODOLIST.md` sorts last — with two more files now sitting between the two. *Trigger: moving
  `CHANGELOG.md` and `TODOLIST.md` into `docs/` was already proposed in that same local file.*
- **Five confirmed fine, recorded so they are not re-proposed:** flat `backend/` (13 modules)
  and flat `frontend/src/` are **correct at this size**; naming is internally consistent;
  missing CONTRIBUTING / CODE_OF_CONDUCT / SECURITY was **re-confirmed as cargo cult** for the
  recruiter audience, credentials already being spelled out in README prose; 10,166 tracked Markdown
  lines against 12,676 lines of non-test `.py`/`.jsx`/`.js` — measured before this entry,
  which itself adds 136; and **zero broken relative links across 70
  checked**, README and all seven docs.

*The review's two structural **new** findings — the demo section swallowing the both-mode
dev-server prose, and demo mode being announced only after the install wall — were both fixed
today in `f492687`.*

**First run — what someone who actually tries it hits (7).**

- ~~**The Python 3.14 hard gate**~~, as above — the *version* half closed 2026-08-28 (`>=3.12`, all three in CI). What a first-timer still hits is the venv one: the start
  scripts hard-fail without an existing virtualenv.
- ~~**No offline or demo mode.**~~ Closed 2026-08-27 in `f492687`, and driven end-to-end against
  a live server: all eight tickers return complete Scorecard and Financial Models data, and
  unsupported paths degrade rather than 500.
- **Neither start script checks for `node_modules`.** `start.bat` checks only for the venv, and
  `start-demo.bat`/`start-demo.sh` are pure delegators, so they inherit the gap. *Trigger: the
  first run on a clone where `npm install` was skipped.*
- **OpenBB's 4-5 s cold start is invisible** — no spinner. **Moot in demo mode**, which never
  imports OpenBB at all: every demo request measured 12-20 ms. *Trigger: live mode only.*
- **`start.sh`'s Ctrl-C trap is documented as unverified**, and `start-demo.sh` reuses it
  without verifying it. *Trigger: the same macOS or Linux user as the CI finding above.*
- **Time to first value is 5-8 minutes on Windows, 15-25 on macOS.** Demo mode does not touch
  the install phase, so this floor is unchanged. *Trigger: a decision to host removes it.*
- **The first screen still defaults to Tracker/AAPL.**
  [App.jsx:41-42](frontend/src/App.jsx#L41-L42). Demo mode flips to Scorecard only *after*
  `/health` resolves, so the first render still mounts Tracker and swaps it out; normal mode is
  completely unchanged. *Trigger: a judgement about which tab should greet a first-time visitor
  in normal mode.*

### 🔵 The pre-profit calibration is now enforced, but still unvalidated

Resolved 2026-08-10 (b) below: RIVN moved 74/A → 60/B and `tests/test_plausibility.py`
went green. What that did **not** do is make the anchors evidential. §5.2 is a
plausibility expectation someone wrote down in advance; enforcing it substitutes one
judgement for another. The composite still has no forward-return validation, exactly as
`docs/scoring-system-design.md` §5.6 and the README say.

**Corrected 2026-08-18.** This paragraph asserted that the `pre_profit_growth` series in
`score_history` is *"discontinuous at 2026-08-10"*, with rows before that date coming from
the old weights, and instructed any calibration study to segment across the boundary. **The
break does not exist.** The stored history holds exactly two `pre_profit_growth` rows —
SPCX on 2026-08-12 and 2026-08-13 — both recorded *after* the change. There are nine rows
of other profiles before 2026-08-10, but none in this one, so there is no old-side data to
be discontinuous with.

What is true prospectively: **no pre-2026-08-10 pre-profit row can ever appear**, because
there is no backfill. So the series is short, not broken, and a calibration study needs no
special handling for it.

**Trigger: the same ~2 quarters of data as the score-history item below.**

### 🔵 The FCFF add-back does not net off interest income

Resolved 2026-08-09 (b) below, with one deliberate gap. The add-back is **gross**
interest, so wherever it fires, the interest *income* still sitting inside operating cash
flow is valued a second time — once through the `EV − net_debt` bridge that already
treats cash as a separately-valued asset, and once as a perpetuity.

Netting it off was rejected on basis-consistency grounds: US filers disclose cash
interest *paid* but no matching cash interest *received*, so netting would mean adding a
cash figure and subtracting an accrual one.

**Currently latent, but not for the reason this entry gave until 2026-08-18.** It said *"XOM
is the only fixture the add-back fires on and it reports no interest income. The first
issuer that discloses cash interest paid **and** earns interest income will activate it."*
Measured across the fixtures:

| | add-back | basis | interest income at that period |
|---|---|---|---|
| XOM | 1,384,080,000 | `cash_interest_paid` | −603,000,000 (net *expense*) |
| **RIVN** | **175,380,000** | `cash_interest_paid` | **+293,000,000** |
| others | 0 | not required / unverified | — |

**RIVN already meets the stated condition** — it fires the add-back *and* earns interest
income. The condition the entry treats as future has been met since the fixtures were
captured. What actually keeps the defect dormant is different and narrower: RIVN's free cash
flow is −2.489bn, so `dcf_valuation` returns *"No positive free cash flow available"* and no
valuation ever consumes the add-back. **If RIVN turns FCF-positive the case activates with
no code change and no trigger firing.**

The ~3% of FCF figure for MSFT and AAPL still reproduces on an accrual basis (AAPL FY2023
2.97%, MSFT FY2026 3.89% after tax) — note AAPL's newest period reports no interest-income
row at all, so that figure necessarily comes from FY2023.

**Trigger: a source that discloses cash interest received**, a decision to accept a mixed
basis, **or any FCF-positive issuer that reports cash interest paid alongside interest
income** — which is the case that would actually bite.

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

### 🟡 The beta credibility band may be miscalibrated for decoupled sectors

*Superseded 2026-08-14: beta is now regressed from five years of weekly returns, so
the vendor figure no longer decides anything. What is left is the band itself.*

This item used to say yfinance's energy betas were **broken**. The regression says
otherwise. XOM's vendor 0.173, its measured **0.2888**, and its peers' 0.488 and
0.123 all agree that an oil major's correlation to the S&P is genuinely very low —
oil moves on its own drivers. The vendor was directionally right.

What was wrong was `BETA_MIN = 0.3`. It rejected every one of those readings and
substituted a neutral 1.0 that nobody measured, and on XOM that alone was worth
roughly **half the valuation**. The floor now binds on a *measured* value, pulling
0.2888 up to 0.30 — a small distortion, but the clamp firing on a good measurement
is the signal worth watching.

*Trigger discharged 2026-08-17 (e), and the sentence above needs one correction.*
The trigger read "a name whose measured beta sits below 0.3 and whose valuation
looks implausible because of it": XOM, at a **5.64% cost of equity** for an oil
major — 134bp over treasuries — and a resulting "+3.7%, fairly valued".

**"All agree" overstated it.** Those four figures span 0.123 to 0.488, a factor of
four. Measured properly, XOM's regression has R² **0.028** and a 95% interval of
**[0.08, 0.49]** — an interval that contains every one of them. They are not four
corroborating readings; they are four points inside one very wide interval. The
low correlation is real (0.168), and what does not follow from it is that the
resulting slope is precise enough to be a point estimate. Its window sensitivity
says the same: 0.048 at 2y, 0.040 at 3y, 0.254 at 4y, 0.289 at 5y.

What shipped is publication, not judgement: R², the interval and the unclamped
slope are on the audit row, so XOM and 0700.HK (R² 0.691) no longer look alike.
A rejection threshold was considered and **not** taken — it sends XOM to a flat
1.0, and R² jumps 0.028 → 0.148 across the fixtures with nothing between, so any
cutoff from 0.05 to 0.14 rejects exactly one name. See CHANGELOG 2026-08-17 (e).

**One of the three options below was taken on 2026-08-20 — "a floor keyed on
something other than the band" — and this entry's own framing was too kind to the
floor.** It said the clamp firing on XOM's good measurement was "a small
distortion… the signal worth watching". Watching it across all eight fixtures
found the case that is not small: **`0002_HK` regresses at 0.1518 with a 95%
interval of [0.0747, 0.2289]**, which excludes 0.30 outright. The clamp there was
overruling a measurement the data supports, and it was worth **74.05 against
97.27** on the fair value — a factor of fourteen more than the 1.7% it costs XOM.

The floor now applies only where the interval **cannot reject it**, which leaves
XOM clamped (0.30 sits inside [0.0828, 0.4948]) and frees 0002_HK. That is the
distinction this entry had the evidence for and did not draw: a wide interval is
the thin-series case the band exists for; a tight one below the floor is a
measurement. Golden effect: 3 of 260 leaf values, all `0002_HK`.

**Note it is one-directional** — both clamped names move up — so it cannot claim
the two-directionality that made the ERP change self-evidently a correction. It
rests entirely on the interval, not on the resulting price.

**What remains open is the modelling question, unchanged and now genuinely
isolated.** CAPM prices only systematic risk, so a genuinely uncorrelated business
gets a low required return however volatile it is on its own terms. Whether that is
right for a commodity cyclical is a known criticism of CAPM, and no better beta
fixes it — freeing the floor makes the model *more* faithfully CAPM, which is the
question rather than the answer.

**Trigger: a decision to depart from CAPM.** Two options are left of the original
three: a total-risk adjustment (Damodaran's own suggestion for exactly this case),
or accepting CAPM's answer — which is now stated on screen with its precision
attached, and no longer silently overridden by a constant.

### 🟡 Only beta shows its uncertainty

Raised 2026-08-17 (e) by the change that added it. The audit row now carries an R²
and a confidence interval for a regressed beta, and nothing else on the panel
carries either. The growth rate, the equity risk premium and the terminal rate are
all estimates too, and displaying an interval on one input while the rest are bare
numbers can read as a precision claim about the rest.

Not obviously fixable by symmetry: beta has a residual because it is regressed, and
the others have no sampling distribution to quote. A consensus growth figure has a
dispersion across analysts, which yfinance does not forward; the ERP is a dated
vendor snapshot with no interval published.

**Trigger: a second input acquiring a defensible interval.** One input with an
honest error bar is better than none; three with invented ones would be worse than
either. Until then the README says so in the same bullet that introduces it.

### 🔵 The FMP peer tier is guarded by convention, one tier above the one that is guarded *(found 2026-08-31)*

Raised by an independent review of the yfinance guard, and it is the same defect that guard was
written for, sitting one step higher in the same expression:

```python
comps.py:514   return PEER_SUGGESTIONS.get(t) or _fmp_peers(t) or _screener_peers(t)
```

`_screener_peers`, the **lower** tier, is force-stubbed by the autouse `no_live_screener`, whose
docstring says why in as many words: *"Nothing does that today; the point is that nothing can
start doing it by accident."* `_fmp_peers` — which calls
`obb.equity.compare.peers(symbol=..., provider="fmp")` and reaches a real vendor — has no such
fixture. That reasoning was applied one tier too late, and the same docstring even names
*"an `_fmp_peers` stub returning `[]`"* as a precondition it assumes rather than supplies.

It degrades the same invisible way, too: `comps.py:391-396` catches `Exception`, records
`_FMP_LAST_CALL = "failed"` and returns `[]`, so an outage and a success are indistinguishable
from a test — exactly the mechanism that let the yfinance count drift from 2 to 17.

**Not currently reached, and that is the whole status.** Every default-suite path into
`suggest_peers` either uses a curated ticker or stubs `comps._fmp_peers` itself, across roughly
fifteen tests. It is safe by convention, not by construction. `openbb` is installed in
`backend/.venv`, so locally there is no `ImportError` standing in the way; CI is shielded only
because `requirements-test.txt` deliberately omits openbb, which is a different fact that could
change on its own.

**Why it was not fixed on 2026-08-31 with the rest.** The obvious fix — add
`_fmp_peers` to `no_live_screener` — breaks `test_fmp_status.py`, which calls `comps._fmp_peers`
**directly** at five sites with a faked `sys.modules["openbb"]` and needs the real function. Doing
it properly means that file capturing the real reference at import, the way `test_comps.py`
already does for `_screener_peers`. That is a change to an unrelated test file, on a path that is
not currently leaking, so it was recorded rather than folded into a commit about yfinance.

**Trigger: the next change to `test_fmp_status.py` or to `suggest_peers`' fallback chain** — or
any test that calls `suggest_peers`, `peer_beta_inputs` or `comps_endpoint` with an uncurated
ticker, which is the case the convention does not cover.

*(A smaller relative of the same shape, recorded here rather than separately: `ai_client.status`
and `stream_chat` make real `aiohttp` calls to `http://localhost:11434` and no fixture stops
them. Nothing reaches them in the default suite — the streaming tests drive `main._ndjson` with
fake generators — and the destination is the developer's own machine, so this is a note, not a
finding.)*

### 🔵 Cross-sectional normalization needs a universe, not a `scoring.py` change

Quant review §6 item 2 (score against the peer *distribution*, not absolute
thresholds) is the right diagnosis and is **blocked on data, not effort**. A
sector z-score or percentile needs a universe to rank within; this app has ~~21~~ **23**
(re-counted 2026-08-30; the conclusion is unchanged — 23 is not a universe either)
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

### ⚪ ~~Two tests in the "offline" suite reach live yfinance~~ — closed 2026-08-31, and there were seventeen

**Found 2026-08-19** while proving the new peer tier does not leak, and **pre-existing** — the
same two fail identically at `bc597ff`, before any of that change.
`test_the_endpoint_prices_the_bridge_before_returning` and
`test_a_bank_gets_no_bridge_from_the_endpoint` both go through `main.comps_endpoint`. The call
that fires is the price refresh, not the bars:

```
main.py:451  comps_endpoint -> _guard(_fundamentals, ticker)
main.py:107  _fundamentals  -> with_fresh_price(f)
data_provider.py:757         -> live_price(ticker)
data_provider.py:783         -> yf.Ticker(ticker).info
```

`_market_bars` → `provider.get_history` leaks too (`data_provider.py:883`), but it is the
*second* site, not the one that fires first. `wired_endpoint` patches `get_fundamentals`,
`_peer_beta_inputs` and `get_peer_snapshot` — not the refresh.

**🟡 rather than 🔴, and the downgrade is the interesting part.** A first draft of this entry
said an outage "turns two green tests red". It does not. Both leak sites swallow ordinary
exceptions (`data_provider.py:786`, `main.py:126`), and the suite was re-run with
`yf.Ticker`/`download`/`screen` all raising a plain `Exception` — the shape a real outage takes
— and reported **467 passed**. So the cost is wasted latency and a hidden dependency on a
vendor being up, not a CI failure. Recording the wrong severity would have sent whoever picked
this up hunting a failure mode that cannot occur.

**How it was found, since the technique is reusable and the severity claim depends on it.** A
throwaway pytest plugin replacing `yfinance.screen`/`Ticker`/`download` with functions raising
a **`BaseException` subclass**. An ordinary `Exception` is swallowed at every one of these
sites, so the leak is invisible to any probe that raises one — which is exactly why the first
severity reading was wrong. Not committed; it is twenty lines and rebuilding it is cheaper than
maintaining it.

**Fix:** stub `main.with_fresh_price` (or `data_provider.live_price`) in `wired_endpoint`, **and**
`main._market_bars` — stubbing only the bars was tried and both tests still leak, one line
further up. **Trigger: next time `test_comps.py`'s endpoint tests are touched** — they assert on
the bridge and the bank path, neither of which needs a live price or real bars.

**Closed 2026-08-31 — and it was seventeen tests, not two.**

The fix is what this entry proposed: `wired_endpoint` now stubs `live_price` and serves bars from
the committed fixtures. `live_price` rather than `with_fresh_price` because returning None is
what the real function does when the vendor is unreachable, so `with_fresh_price` stays in the
call path and hands back the fixture's own price. Note the asymmetry — `_market_bars` must be
patched on `main`, while `with_fresh_price` is imported into `main`'s namespace by name, so
patching it on `data_provider` would not be seen.

**The number is the finding.** Rebuilding the probe and running it against the *whole* suite
rather than the two tests named here:

| file | leaking tests | site |
|---|---|---|
| `test_comps.py` | 2 | `live_price`, then `get_history` |
| `test_intrinsic_endpoint.py` | **14** | `live_price` — fixture stubbed the bars but not the price |
| `test_search_and_history.py` | **1** | `yf.Search`, which the original probe never patched |

All seventeen are closed. The two extra sites cost one line each; the search one was worse than
latency — `test_unrelated_text_matches_nothing` asserted `== []` and had been passing because a
live vendor happened to return nothing for `zzzzqqqq`, not because local fuzzy matching declined
to invent a result.

**The 2026-08-19 decision not to commit the probe is reversed, and its own reasoning is why.**
It read: "Not committed; it is twenty lines and rebuilding it is cheaper than maintaining it."
Nobody rebuilt it for twelve days, and in that window the count went from 2 to 17 with nothing
able to notice. `conftest.no_live_yfinance` is now autouse and makes `yf.Ticker`, `yf.Search`,
`yf.download` and `yf.screen` a hard error for any test without the `network` marker. It found
the seventeenth itself, immediately, because it patches `yf.Search` and the throwaway probe did
not.

Suite time fell from a median **16.75s** to **11.73s** (n=7 and n=5), and what remains no longer
depends on a vendor being reachable. The claim "runs entirely offline", made in `README.md:31`
and `:448`, `PROVENANCE.md:65` and both endpoint fixtures' docstrings, is now enforced rather
than asserted.

---

## Next

### 🟡 The methodology reference is truncated, not retrieved

[backend/ai_client.py](backend/ai_client.py) does `text[:16000]` on a ~~1,087~~ **1,221**-line
document, so everything past roughly the first ~~40%~~ **20.0%** never reaches the model — including

*(**Re-measured 2026-08-30: the reachable share has halved, and not because the budget moved.**
The document is now 80,011 characters, so 16,000 is 20.0% of it, and the cut lands at line 268
of 1,221 — mid-sentence inside §1.2. The whole of §1.3 Residual Income, §2 relative valuation,
§4 statement analysis, §6 endpoint mapping and §7.1 the model-priority matrix are outside it.
The entry's own examples were right and understated: it is not the tail past 40%, it is 80% of
the document. **This number will keep falling every time the reference grows**, which the
2026-08-30 additions to §1.2/§1.3/§5.2 were deliberately placed past character 16,000 to avoid
making worse.)*
§6 (endpoint mapping) and §7.1 (the model-priority matrix). "Grounded in the
methodology" is therefore only true of the opening sections.

**Fix:** chunk the document and select sections by keyword against the user's question.
**Trigger: after Ollama is installed** — worth measuring whether the 7B model even uses
the excerpt it already gets before building retrieval for it.

### 🟡 A cyclical is still valued off one year of its own cycle

*Most of this item was resolved 2026-08-13 below — the clamp is gone, the explicit stage
now matches the one-year consensus that feeds it, and the base year is shown against the
company's own history. What is left is narrower, and it is a decision rather than a bug.*

XOM's newest reported year is **0.71× its own four-year average FCF margin**, and the
model still takes that year as the headline. The band beside it shows what the average
implies (**71.75 → 102.17** on the fixture), but the platform deliberately declines to choose,
because whether a trough persists is a forecast about the world rather than a figure in
the accounts.

For genuinely cyclical sectors that reasoning is weaker than elsewhere: normalising across
a cycle is not a modelling opinion there, it is the professional standard, and energy /
materials are the textbook case. Making the normalised figure the *headline* for
classified cyclicals only — reusing the sector classification that already exists — was
put to the owner on 2026-08-13 and **declined**; the band was accepted, the headline swap
was not.

**Revisited 2026-08-14 and declined again, this time on measurement rather than
principle.** Three findings, any one of which is enough:

- **XOM's own history shows a trend, not a cycle.** Its FCF margins run 14.65% → 9.99% →
  9.05% → **7.29%**, monotonically down; MSFT, AAPL and 0700.HK all oscillate. A cycle
  average needs a window that spans a cycle, and four points moving one way is a lagged
  trend. Normalising XOM assumes reversion to a level it has moved *away from every year
  in the window* — a forecast about the world, which is the thing the platform does not do.
- **The classification to key on does not exist.** `SECTOR_MAP` sends `basic materials` to
  `industrials`, so "energy / materials" resolves to `energy` alone and materials stays
  fused with non-cyclical industrials.
- **It is not one number.** The sensitivity grid, `growth_sensitivity` and
  `price_gap_bridge` are all built on the reported base. Swapping the headline without
  rebuilding them makes the bridge either double-count its adjustment or show a
  zero-length step.
  *(Corrected 2026-08-18: this bullet also claimed the swap "puts the mid outside its own
  bar (hidden by `_clamped_mid`)". It does not. `comps._dcf_band` **unions** the normalised
  figure into the band — `low, high = min(low, normalised), max(high, normalised)` — so a
  normalised mid lands on a band edge, inside the bar, and `_clamped_mid` is a no-op. The
  paragraph below this list already says the bar spans both bases, so the bullet
  contradicted its own entry.)*

**⚠️ Corrected 2026-08-18 — this paragraph said the opposite of what is now true, and it
was the entry's reason for calling the swap cheap.**

It read: *"`dcf_upside_pct` is anchor-clipped at −40, so XOM's metric moves 0 → 9 of 100 and
the composite stays 70, tier A. The swap is a display change almost entirely."* That was
internally consistent when written — 102.17 against a 151.63 price is −32.6%, which scores
about 9.

Measured today with the risk-free rate pinned at 4.3% and the FX pin at 1.10, XOM's DCF is
**157.30 (+3.7% upside)**, not 71.75, because beta became a measured regression on
2026-08-14. So:

| | as written | today |
|---|---|---|
| reported fair value | 71.75 | **157.30** |
| normalised fair value | 102.17 | **221.14** |
| `dcf_upside_pct` raw | ≤ −40 (clipped) | **+3.7%** |
| metric score | 0 → 9 | **55 → 91** |
| composite / tier | 70 / A | **74 / A** |

The headline swap now moves that metric **55 → 91 of 100**, which flows through the
valuation pillar into the composite. **It is a substantive scoring change, not a display
change**, and the argument that made it look cheap no longer holds. Anyone revisiting this
has to re-measure the composite, not just the chart.

The cheap part of the value was taken instead — see the 2026-08-14 Done entry: the DCF
bar now spans both bases, so the chart shows the base-year uncertainty without the
platform choosing a side.

**Trigger: a cyclical whose reported-year headline proves misleading in use**, or margin
history long enough to contain a turn. Options if revisited: normalised headline for
`energy` only, a multi-year consensus average, or the 3-year revenue CAGR.

### ⚪ ~~Beta re-levering has never been audited on a net-cash company~~ — closed 2026-08-18

*Raised 2026-08-13 and never investigated. Investigated 2026-08-18: the premise is false in
three independent ways, so there is nothing to audit. Kept rather than deleted so it is not
raised a fourth time.*

It read: *"`resolve_beta` unlevers peer betas and re-levers them to the target's capital
structure… AAPL and MSFT carry more cash than debt, and it has never been checked what the
Hamada formula does with a **negative** net position."*

- **AAPL and MSFT are not net-cash.** On the committed fixtures MSFT carries 128.81bn of
  debt against 76.65bn of cash, and AAPL 84.34bn against 62.40bn. Both are net *debt*. The
  net-cash fixtures are 0700.HK and JPM.
- **The formula never sees a net position.** `resolve_beta` builds D/E from
  `financial_models._debt_to_equity`, which returns `max(debt, 0.0) * fx / market_cap` —
  gross debt over market cap, floored at zero. It is structurally incapable of going
  negative, whatever the cash balance.
- **The branch is unreachable for every fixture.** Since beta became a measured regression
  on 2026-08-14, `resolve_beta` returns `"computed"` before peers are consulted; all seven
  fixtures resolve `computed` (or produce no DCF at all, for JPM and RIVN).
  `peer_median_relevered` is a third-tier fallback that no fixture reaches.

**The one part worth keeping is already recorded elsewhere.** The closing sentence — CAPM
with a historical ERP may overstate the required return on a business with negligible
financial risk — is the same open question the beta-credibility-band item states above, in
more detail and with measurements. This entry added a false premise on top of a duplicate.

**No trigger.** Its old one read *"before treating the mega-cap DCF gaps as settled"* — a
real concern, but one the beta-credibility-band item above already owns. Closing this
removes a duplicate, not a question.

### 🟡 Associates are still carried at cost, and cost is not value

*Mostly resolved 2026-08-14 (d) — see the Done entry. Both blockers this item recorded turned
out to be measurable rather than intractable.*

**The nesting is an exact identity, so the parent is safe.** On 0700.HK, both reported
periods: `Long Term Equity Investment` 348,712 = `Investmentsin Associatesat Cost` 342,409 +
`Investmentsin Joint Venturesat Cost` 6,303. Read the parent, never sum the children.

**"At cost" applied to only a third of the portfolio.** `Investmentin Financial Assets`
635,426 = `Available For Sale Securities` 428,342 + `Financial Assets at FVTPL` 207,084 —
and both of those are *already carried at fair value*. That 635bn is now in the bridge,
because using it reads a filed mark rather than inventing one. It moves 0700.HK from ~~−11.1%~~
to ~~**+3.6%**~~ with no assumption entering the headline.

*(**Both figures re-measured 2026-08-30 and neither reproduces**: the headline is now **+12.0%**
at a fair value of 539.04. Same drift `L573`/XOM was corrected for on 2026-08-18 and this entry
never was — beta became a regression on 2026-08-14 and gained an interval-aware floor on
2026-08-20, and 0700.HK's beta is one of the ones that moved. The structural claim is untouched:
cost is not value, and the associates leg stays out of the headline.)*

**What is left is the associates leg only** — 348.7bn, ~~+45.06/share~~ **+42.61/share** on
0700.HK (re-measured 2026-08-30 with the exchange rate pinned at 1.10;
`diagnostics.equity_bridge.per_share.associates_at_cost`), shown beside
the headline and excluded from it. Cost is neither a market value nor a floor: a long-held
stake is usually worth more than it cost and an impaired one less, and the filing does not
say which.

**Trigger: a holdings-level source with marks**, or a decision to accept carrying cost with
that stated on screen. Note the platform can already show the second answer — the panel
prints it — so what a source would buy is the right to put it in the headline.

### ⚪ ~~Portfolio totals ignore FX~~ — closed 2026-08-30

~~Holdings in USD and HKD are summed at face value. The UI warns when the totals really do
span more than one currency, but the total is wrong, not merely imprecise.
**Trigger: actually holding both.** Needs a rate source; `obb.currency` is free.~~

*(**The rate source already exists — corrected 2026-08-30.** `data_provider.fx_rate` is live,
daily-cached and already used inside `financial_models` to reconcile a statement currency
against a trading one. Nothing needs sourcing; the work is wiring it into `position_values`/
`portfolio()` in `main.py` and choosing a base currency — roughly 20-30 lines and 3-5 tests.
This entry has been costed as blocked-on-data since it was written, and it is not.*
*
**And the size of it, measured 2026-08-30 on the committed fixtures:** AAPL prices at USD 311.00
and 0700.HK at HKD 481.40, so ten AAPL plus a thousand 0700.HK reports a total of **484,510** —
Hong Kong dollars added to US dollars as if they were the same unit. Converted at the HKD peg
(~7.80) the true figure is about **64,828**. The displayed total is **7.5x** the real one, and
it grows with the HK weight rather than staying a rounding error. That is not a cosmetic gap in
a portfolio tab.)*

*Narrowed 2026-08-17:* the warning used to read the currency of **every** row, so a
watchlist entry — which carries no market value and is therefore in no total — could
raise it on a portfolio that was not mixed at all. It now reads the same set the backend
uses to build `held`. That fixed when the warning fires; the summation it warns about is
still unconverted, which is why this item stays open.

**Closed 2026-08-30 — and the `7.5x` above needs a correction, because it was quoting a base
currency that was not the one chosen.** Value, cost and P&L are converted to **HKD** before any
sum; per-share price and cost stay native, and the columns say which is which. The size of the
error turns out to depend on the base:

| | shows | true (HKD) | |
|---|---|---|---|
| 10 AAPL + 1000 × 0700.HK | 484,510 | 505,658 | understated **4.2%** |
| 10 AAPL alone | 3,110 | 24,258 | understated **7.80×** |

So the `7.5x` was right for a *USD* base and is wrong for the one taken. The error scales with
how much of the portfolio sits away from the base — it is small when HK names dominate, and it
is the whole peg for a Hong Kong holder of US stocks, which is the realistic case.

**The figure that is base-independent is the one this entry never mentioned: the weights.**
AAPL's true share of that portfolio is 4.80% and it was reading **0.64%** — understated by 7.47×,
the exchange rate itself, because a ratio of two figures in different units is not a weight.
`top_weight_pct`, `top3_weight_pct` and `hhi` all inherited it, so the concentration panel was
wrong too. The entry said "the total is wrong"; four more fields were.

**Two things the change had to get right that this entry did not anticipate.** The totals'
`unrealized_pnl_pct` is *not* saved by being a ratio — the row-level one is, since numerator and
denominator share a currency, but the totals' divides one cross-currency sum by another. And the
conversion is all-or-nothing: converting the rows that have a rate and leaving the rest native
would put two units in one column, so a missing rate now withholds the totals and names the
currency instead of falling back to the face-value sum, which is the old wrong number with a
caveat beside it.

### ⚪ ~~CI proves the tests, not the install~~ — closed 2026-08-28

[.github/workflows/ci.yml](.github/workflows/ci.yml) installs `backend/requirements-test.txt`
— six entries — then runs ruff and pytest. It never installs `backend/requirements.txt`, so
the path the README actually tells a stranger to follow (107 pins, including `openbb` and its
30 subpackages) is proven on one Windows 3.14.6 machine and nowhere else. A broken runtime
pin, or a runtime dependency that stops resolving, passes CI green.

Not a suspected break, an unexercised one: `openbb`, `openbb-core` and `openbb-sec` all
declare `requires-python >=3.10,<4`, with `pandas>=3.11` and `numpy>=3.12`, so nothing in the
set excludes 3.14. The README's "CI runs the whole suite on Linux" is true of the tests and
says nothing about the install, which is the part a first-time user hits first.

**Closed 2026-08-28** by [runtime-install.yml](.github/workflows/runtime-install.yml), which
differs from the fix planned above in two ways, both deliberate.

It does not run on every push. That cost was the stated reason this was not already here, and
it turned out to be avoidable rather than payable: the set can only break by being edited,
which a `paths` filter catches at once, or by an upstream release being yanked or re-tagged,
which a Monday run catches. A normal push pays nothing.

And it does not run *nothing* after installing. `import backend.main` proves the app builds
its route table under the resolved set, and a second `from openbb import obb` proves the 31
OpenBB pins — which the first import structurally cannot reach, because every OpenBB import in
this codebase is deferred into the function that needs it to keep a slow import off the
request path. Without that second line the job would have been reassuring rather than useful.

Measured: 2.84 s and 8.35 s for the two imports locally; 63 s for the whole first green run.

### ⚪ ~~The FMP key still has to be typed into a JSON file by hand~~ — closed 2026-08-28

A sixth tab, **🔑 API Key**, beside Portfolio. It writes
`~/.openbb_platform/user_settings.json` — the file OpenBB already reads, on the user's own
machine, outside the repo — and then makes **one real call**, so the screen answers *working*
or *rejected* rather than *saved*. That verification is the feature; the text box is the easy
half, and a form that only said "saved" would have left the original complaint intact.

Three things this had to get right, each with a test that fails without it.

**Read-modify-write, never overwrite.** Measured on the development machine before a line was
written: that file also holds a `tiingo_token`, plus `preferences` and `defaults`. Only
`credentials.fmp_api_key` is touched. A file that cannot be parsed is **refused** with a 409
rather than replaced — starting fresh there would destroy what may be the only copy of another
provider's credential. Mutation-proved: making `_load_settings` return `{}` fails exactly the
three tests that check the rest of the file survives.

**No endpoint returns the key.** `/api/health` reports whether one is set, never what it is.
Nothing here is authenticated, and a GET that hands back a stored credential is how a
convenience becomes a disclosure. The input is `type="password"` and is cleared on save.

**Demo mode refuses the write at the endpoint, not in the UI.** Hiding the tab is the visible
half and is not a control — the route is reachable regardless, and on a hosted demo the
filesystem being written would be the operator's. A visitor would either overwrite the
operator's key or leave their own on a stranger's machine for the next visitor to spend.

**Corrected the same day.** The first version wrote the file and *then* verified, and that
order cost a real key within the hour: a placeholder typed to see what the tab did replaced a
working one, the probe correctly returned "failed", and the accurate report arrived after the
loss. A verdict you cannot act on is not a safeguard. It now verifies first and writes only on
success, restores the in-memory credential and the previous verdict on a rejection, and keeps
one generation of the whole file as `.bak` — which is what would have made the original
incident recoverable and did not exist. Mutation-proved both ways: writing regardless of the
verdict fails the two rejection tests, and dropping the in-memory restore fails exactly one.

Still open, and unchanged by this: hosting. The tab is the right shape for a local
single-user install, which is what this is. A hosted instance would need a different answer to
"whose key is this", and the 403 above is what stands in for that answer until there is one.

### 🟡 EMA overlay — near-free, and not obviously worth it

Raised 2026-08-17 (f). `emaArray` already exists as MACD's helper, so exposing an EMA
overlay is an `export` and a toggle. It asserts nothing, so there is no harm case. The
question is whether it is a feature or a checkbox.

Measured against the SMA20 already drawn: level correlation **0.9991**, first-difference
correlation 0.854, and **14% more price crossings** (higher on 9 of 10 names, tied on one).
Derived exactly: EMA(N) and SMA(N) share an identical mean lag of (N−1)/2 and identical
iid-noise suppression of 1/N, differing only in weight shape — 3× lag variance and ~1.9×
weight on the newest bar. So it is not "faster"; it is the same average with a different
memory profile, producing more whipsaw for the same information.

**Trigger: a user asking for it by name, or a second EMA-based indicator that would make
the helper worth exposing anyway.** If added, the tooltip should state the lag and noise
equivalence — that sentence is the only thing that makes it worth having over the SMA, and
no commercial charting package tells its users.

### ⚪ CSS Modules — the structural concern is real, the present problem is 0.4%

*Migrated here 2026-08-18 from a local architecture audit being retired; recorded because the
measurement would otherwise be lost with the untracked file.*

`index.css` is a single ~~2,033~~ **2,287**-line (re-counted 2026-08-30, +12.5%; the 0.44% dead-selector figure was not re-derived and is due for it, since the stylesheet moved materially) global stylesheet, so nothing *could* detect dead CSS and
deleting a component would silently strand its rules. That much is structurally true. But it
was measured rather than assumed — every class selector diffed against every string literal in
the JS/JSX sources:

- **227 classes defined** — re-counted 2026-08-18, unchanged
- **8 with no literal match** under substring matching, **9** under strict-token matching:
  `disp-tight`, `disp-moderate`, `disp-wide`, `ff-recon-input_substituted`,
  `ff-recon-reconcilable`, `medium`, `peer_median_relevered`, `ticker-box`, plus `peer_median`
  on the strict reading only
- **All but one are dynamically composed or compound** — `` `ff-tag disp-${r.dispersion_band}` ``
  ([ScorecardTab.jsx:312](frontend/src/components/ScorecardTab.jsx#L312)),
  `` `chart-note ff-divergence ff-recon-${...}` `` ([:451](frontend/src/components/ScorecardTab.jsx#L451)),
  `` `src-tag ${a.beta_source}` `` ([ModelsTab.jsx:204](frontend/src/components/ModelsTab.jsx#L204))
  feeding `.src-tag.peer_median` / `.src-tag.peer_median_relevered`, and
  `` `ff-conviction ${t.conviction.toLowerCase()}` `` ([:424](frontend/src/components/ScorecardTab.jsx#L424))
  feeding `.ff-conviction.medium`
- **Exactly one genuinely dead rule:** `.ticker-box`
  ([index.css:107](frontend/src/index.css#L107)) — zero occurrences anywhere in
  `frontend/src/**/*.{js,jsx}`. 1 of 227 is **0.44%**

*(Two corrections. The retired audit said "12 unmatched, 11 dynamic" — miscounted, not drifted:
re-running the whole analysis at `8c5d467` also gives 227/8/9. But the reason a 2026-08-18 draft
gave for that — "`index.css` is byte-unchanged" — was a non-sequitur, since the unmatched count
depends on the **JS side too**, and `frontend/src/` changed materially in between. And the
method matters: matching against the whole file text gives 9, while matching against string
literals only gives **10**, the extra being `computed`, which appears in this repo solely inside
prose comments. `.src-tag.computed` was cited as an example of the unmatched set and is the one
example that does not belong there.)*

**0.4% dead is not a present problem**, and converting to CSS Modules would touch every
component to fix it.

**Trigger:** the stylesheet passing ~3,000 lines, or the first component deletion — whichever
comes first, since either turns the structural risk into a live one.

### ⚪ ~~Two remaining `or 0` coercions from the 2026-08-27 audit~~ — both closed 2026-08-30

The audit found six `.get(...) or 0` sites on model inputs. Three were benign (a missing
analyst count and a missing dividend yield mean the same thing as zero), one was the
market-cap defect fixed on 2026-08-27, and one — `financial_models`' `totalDebt or 0` — is
covered by the `net_debt_assumed_zero` flag that already fires beside it. These two are not.

- ~~**`comps.py`'s `net_debt = (totalDebt or 0) - (totalCash or 0)`.** A missing cash balance
  overstates net debt and understates the peer-implied value. Measured on AAPL: net debt
  21.9bn against 84.3bn, an overstatement of **1.37% of market cap**. It feeds the
  peer-implied bar of the football field, not the DCF headline, which is why it ranks below
  the three fixed that day. The fix is the same one-word change (`is not None`) plus a
  decision about what to do when it *is* missing — the bar should probably not be drawn at
  all, which is a different change from scoring it.~~

  **Closed 2026-08-30, and the ranking argument above was built on the mildest of eight
  readings.** Measured across every fixture, the error runs 0.68% of market cap on O to 190%
  on JPM; AAPL, the one number this entry carries, is **seventh of eight**. The two largest
  are inert — JPM reports no EBITDA so `ev_implied` rejects it regardless, and RIVN's
  multiples all fall to the positive-only filter — which leaves **0700.HK at 10.61%**, 56.18
  per share against an implied low of 382.12, as the largest that reaches the chart. It is the
  one fixture in a net *cash* position, which is exactly why the cash term going missing costs
  it the most.

  Both legs are guarded, not the cash one alone: the mirror case understates net debt and
  overstates the value, and treating two identically-shaped absences differently inside one
  expression is not defensible. The refused multiples are recorded in `suppressed_multiples`
  and — for the first time — **rendered**; a fully-suppressed peer row now says it was refused
  instead of vanishing.
- ~~**`format.js`'s `num` / `big` / `pct` guard `null` and `undefined` but not `NaN`.**~~
  **Closed 2026-08-30.** All four formatters — `scoreColor` included, which this bullet did
  not name — now share one `missing()` predicate. Two things this entry had wrong are worth
  keeping rather than overwriting.

  **It was not latent.** The trigger below says neither of these produces a *plausible* wrong
  number, and that "the second renders visibly broken text" as though nothing were rendering
  it. `FootballField`'s axis row is a sibling of its `.map`, gated only by `ranges` being
  non-empty, and its three ticks read `min`/`max` directly rather than through the guarded
  `x()`. With every row `not_applicable` and no price, `lows` is empty, `Math.min(...[])` is
  Infinity — so the axis rendered **`∞`**, **`非數值`** and **`-∞`** as its labels. The
  fixture that produces this has been in `ScorecardTab.test.jsx` since it was written; the
  test's own comment enumerates three guards on `x()` and misses that the axis is a fourth
  consumer reading around it. Confirmed by writing the assertion and reading the failure's
  DOM dump, not by argument.

  **And `scoreColor(NaN)` did produce a plausible wrong output.** `NaN >= 65` and `NaN >= 50`
  are both false, so a score that could not be computed fell through to `var(--down)` and
  rendered identically to one that scored terribly — across 7 call sites, and against the
  stated contract in `format.test.js`'s own header.

  **Left open deliberately:** `num("")` returns `"0"`, because `Number("")` is `0` and the
  empty string fails the null/undefined arm. That *is* a plausible wrong number, and it is the
  one thing here nobody has shown a path to — no call site was found that passes an empty
  string. Changing behaviour for an input never observed is speculative; recorded instead.
  *Trigger: a backend field that can arrive as `""`.*

**No trigger — both are closed.** What is left is the one thing declined on each, recorded in
place above: `num("")` rendering as `"0"`, and the note below.

**One finding from the review of the second fix, declined with a reason.** A peer median that
rounds to `0.00` produces no implied value and records no reason, because both
`ev_implied`'s `if mult and ...` and the suppression check test it for truthiness. That looks
like the same defect this entry is about, and measuring it says otherwise: it behaves
identically whether net debt is known or not, so it is a property of the truthiness idiom
rather than of the coercion. Recording "refused because net debt is unknown" there would
attach a false reason to a multiple that was never going to compute. *Trigger: a real peer
median below 0.005×, which no fixture approaches — or a decision to make every zero-valued
median state itself, which is a different and larger change than one word.*

### ⚪ ~~The crosshair magnet snaps to whichever series is nearer, not to the bar~~ — closed 2026-08-31

Reported from a browser: with a moving average drawn, the crosshair's horizontal line sticks to
the MA rather than to the candle, depending on which is closer to the pointer.

**Half of this was a different defect and is closed.** The chart was built with
`CrosshairMode.Magnet`, which the library documents as sticking to "the close price of OHLC-based
series", while the toolbar button beside it has always said the crosshair "sticks to
open/high/low/close" — which is `MagnetOHLC`. Both call sites now pass the named enum instead of a
bare `1`; the magic number is how a tooltip and a mode drifted apart with neither looking wrong.

**The reported half is not fixed and has no option behind it.** lightweight-charts 5.2.0 exposes no
per-series magnet exclusion — checked in its own typings, where the only related knob is
`defaultVisiblePriceScaleId`, which picks a price scale rather than a series — and *both* magnet
modes are documented as snapping to "the price value of a single-value series", which is what an
MA overlay is. So there is no configuration that says "magnet to the candles only".

**It is a line in the wrong place, not a wrong number.** `onMove` reads
`param.seriesData.get(series)` where `series` is the candlestick series, so the OHLC readout has
always shown the bar regardless of where the crosshair line settled. What the reader sees is the
horizontal line sitting on the MA while the numbers below it describe the candle.

**What the fix would be, and why it was not taken now:** set `crosshair.mode` to `Normal` and draw
the snapped line and readout from `snapToBar()` — which this file already has, at
`PriceChart.jsx:776`, and already uses to land drawn lines on bars. That means owning the crosshair
rendering rather than configuring it, and it was out of proportion to a cosmetic mismatch on the
day it was found.

*Trigger: the next substantial change to `PriceChart`'s crosshair or drawing layer — `snapToBar`
would then be serving both paths, which is the point at which owning it costs least.*

**Mitigated 2026-08-31: the wrong line is gone, the right line is not drawn.** With the magnet on,
`crosshair.horzLine.visible` and `labelVisible` are both false. Nothing now points at a moving
average while the readout reports the bar — which was the actual harm — and the hover readout,
which reads the candlestick series directly and always has, is what carries the price.

`labelVisible` is half of that fix rather than a detail. The price-axis label is drawn at the same
snapped price as the line, so hiding only the line would have moved the defect from the pane onto
the axis instead of removing it.

The mode stays `MagnetOHLC` rather than `Normal`, for a line that is currently invisible. That is
deliberate: it keeps the option correct for the day the line comes back, so restoring it is a
change to one boolean rather than a re-derivation of which mode was right.

**What is still not done is drawing the correct line**, and the cost of that is the paragraph
above this one. The trade taken here was 3 lines to remove a line that lies, against roughly 150
to 250 across three files to draw one that does not — for a chart whose numbers were never wrong.

*Trigger: unchanged. Also worth revisiting if the missing price line turns out to be missed in
use, which is the one thing the argument above cannot settle from here.*

**Closed 2026-08-31: the correct line is drawn, by this repository rather than by the library.**

The mitigation above lasted one afternoon. Hiding the line removed one that lied, and the reader
reported missing it — which is exactly the thing the argument for hiding it said it could not
settle from a desk. So the option that was costed and declined got built.

`DrawingsPrimitive` gained a fourth callback and `crosshairShape()`; `PriceChart` snaps the
pointer's price with `snapToBar` — **the same function the drawing tools use** — and hands it
over. That is the part worth keeping: the crosshair and a line drawn by hand now land on one
price because they share one rule, where before they had two rules that agreed only by accident.
`CrosshairAxisView` puts the price back on the axis.

**Three library contracts were traced rather than assumed, and one of them decided the design.**
`CrosshairMode` governs only the *price* snap and never the *time* snap — the vertical line lands
on the bar in every mode — so the mode is now `Normal` in both states instead of a magnet mode
governing a hidden line. `requestUpdate` schedules through `requestAnimationFrame` and dedupes
within a frame, so calling it on every pointer move is safe. And `fixedCoordinate` is left
unimplemented on purpose: implementing it would opt the label out of the pass that keeps it clear
of the series' own last-value label.

**What the estimate got wrong, recorded because it was wrong in a useful direction.** This entry
costed the work at 150–250 lines and said jsdom could not verify it. The second half was too
pessimistic: `drawingPrimitive.test.js` builds a primitive whose pixel space is the identity, so
the geometry is asserted exactly. Thirteen tests, four mutations landed, and one placebo caught
before it shipped — the pointer was stubbed at 100 against a bar opening at exactly 100, making
the snap a fixed point that deleting `snapToBar` would have passed.

*What is still not verifiable here is the picture: the chart is mocked wholesale, so nothing
asserts that the line appears where the eye expects. That is a browser check, not a test.*

### 🟡 `FootballField`'s scale is safe by coincidence, not by construction *(found 2026-08-30)*

Raised by the independent review of the axis fix above, and narrower than that bug. `x()` is
`(v) => ((v - min) / (max - min)) * 100`, and `min`/`max` are non-finite exactly when the
domain is empty. Three callers survive that state without a `Number.isFinite` check of their
own: the overlap band behind `t?.overlap`, the price rule behind `currentPrice`, and `geom`
plus the mid-tick inside `drawn.map`.

Two of the three are safe **by construction** — `drawn.map` contributes nothing when `drawn`
is empty, and a truthy `currentPrice` is concatenated into `lows`/`highs` before the reduction,
so it makes the domain finite by its own presence. The third is safe only **by assumption**:
nothing in this component stops the backend sending a `triangulation.overlap` while every
football-field row is `not_applicable`. If those ever coexist, `x(t.overlap.low)` feeds a
non-finite number into `style.left` — silently invalid CSS rather than visible text, which is
why it ranks below the axis bug rather than beside it.

**Trigger: the first backend change that can emit an overlap without a drawable row**, or the
next structural pass over `FootballField`. Not worth a guard at each call site today — the
honest fix is one early return once there is a reason to write it.

### 🟡 Three specification items that never reached code *(found 2026-08-26)*

Found by auditing `docs/financial-models-reference.md` and
`docs/scoring-system-design.md` against the engine. None is a defect in what the code
computes; each is a rule the documents state and the code does not implement. Recorded
here because the alternative is finding them a second time.

- **No size premium.** `financial-models-reference.md` §1.1.2 gives cost of equity as
  `Rf + Beta*ERP [+ size premium + country risk premium if applicable]`. The country half
  is implemented, through Damodaran's additive total ERP. The size half does not exist —
  `grep size_premium backend/` returns nothing — so every micro- and small-cap is
  discounted at a premium calibrated on mature-market equity. The spec marks it
  conditional and judgmental, which is why this is a gap rather than a bug, and why
  closing it needs a rule for *when* it applies before it needs an arithmetic change.
- **`MAX_AUTO_PEERS = 4` against a documented target of 5-10.** `financial-models-reference.md`
  §5 says *"Target 5–10 peers. Fewer than 4 → widen criteria and flag low confidence."*
  The automatic cap is 4 — the spec's floor, never its target — and no low-confidence flag
  fires below it; only the raw `peers_used` count reaches the screen. A user can widen the
  set by hand, so the number shown is never wrong, only thinner than the document asks for.
- **Five sector rules in `scoring-system-design.md`'s notes column are unimplemented**:
  asset turnover added to Q for industrials, asset turnover and FCF conversion weighted up
  for logistics, a telecom/internet split inside `communication_svcs`, and payout gates for
  utilities and REITs. The second of those cannot be implemented as written at all — a
  pillar score is `sum(scores)/len(scores)`, with no per-metric weighting mechanism
  anywhere, while the document's own §4.1 formula assumes one exists.

  **Recorded in the specification 2026-08-30, and it reaches further than "the second of
  those".** §4.1's first formula line names a `metric_weight_i` that exists nowhere in the
  engine: `grep metric_weight backend/` returns nothing, and `SECTOR_PROFILES` carries only
  per-pillar `weights`, a `metrics` membership list and `anchor_overrides` — no structure
  that could make one metric outrank another inside a pillar. So **four** of the notes-column
  rules are blocked on the same absent mechanism, not one: `energy`'s FCF yield, `industrials`'
  interest coverage, `logistics`' asset turnover and FCF conversion, and `utilities`' dividend
  yield are all "weighted up" on paper and unweighted in fact. The second formula line — the
  composite's weighting *between* pillars — is fully implemented, which is why this reads as a
  working system on a first pass.

  *(A first draft of this named the REIT row as the fourth. It is not one: `real_estate_reit`
  drops metrics and lists which ones make up V, which is membership rather than weighting, and
  membership is implemented. The real fourth is `logistics`, whose weighting is in Q rather
  than V. Caught by review, after the wrong list had been copied into three files.)*

  A first draft of this repair edited the document to match the code. That is precisely what
  its own banner forbids: it is a specification, and restating the engine's arithmetic as the
  design would erase the gap rather than name it. An `As implemented` note was added beside
  §4.1 instead, following the convention `financial-models-reference.md` already uses.

**Trigger:** none of these changes a number that is currently wrong, so none is urgent.
The peer cap is the cheapest and the only one whose fix is unambiguous. The metric-weight
mechanism is the most expensive: a weight per metric per profile, a renormalisation rule for
the missing-data case §4.1 already specifies, and a re-bake of `golden_scores.json`.

### ⚪ Stock compensation is not netted where free cash flow came from `info` *(recorded 2026-08-26)*

Not a defect — recorded so the next reader does not rediscover it. `sbc_expense` is called
with the period `statement_fcf` resolved, and returns `0.0` with the basis
`no_statement_fcf` when there is none. That happens whenever the cash-flow statement is
missing a leg and the valuation falls back to `info["freeCashflow"]`, whose period the
vendor does not state. Subtracting a named period's charge from an unnamed period's cash
flow would be exactly the period-mixing `statement_fcf` refuses to do elsewhere, so the
adjustment is skipped and the basis says so on screen.

In the fixture set this is `O` alone: it reports stock compensation in all five periods but
carries no `Capital Expenditure` row, so its free cash flow comes from `info`. The charge is
**1.7% of the base figure**, and `dcf_applies` is `False` for a REIT — the model already
refuses to present that valuation as an answer — so the reachable error is small and sits
on the one classification where nothing reads it.

**Trigger:** an issuer where `dcf_applies` is true, `info["freeCashflow"]` is the source,
and the charge is material. None exists in the fixtures. Closing it needs a period for the
`info` figure, which the vendor does not publish — the honest fix is a fixture that proves
the case exists before code is written for it.


### 🟡 The chart panel overflows horizontally on a phone *(found 2026-08-26)*

Measured at 390×844: `document.documentElement.scrollWidth` is **489px** against a 390px
client width. Nothing in the caveat layer causes it — all 22 visible note elements were
checked for self-overflow and none contributes. Two things do: the tab `<nav>` (469px, an
unwrapped button row) and the two `.sens-table` grids (373px and 385px, whose 61-66px
columns do not compress).

**Worse since 2026-08-28, by an amount not measured.** The 469px `<nav>` was five buttons; the
🔑 API Key tab makes it six. No browser was available to re-measure, so no new number is
recorded here rather than an estimated one — but the direction is certain, and the nav was
already the largest of the two contributors.

Separately the page runs **2125px at 1440px wide against 4127px at 390px**, 1.94×, because
every prose caveat rewraps from one line into six to nine.

**Fix:** let the nav wrap or scroll, and give the sensitivity tables their own
`overflow-x: auto` container. Neither touches the caveat layer, which is why the
2026-08-26 typography pass deliberately left this alone rather than bundling it.

### 🟡 "Inputs used" is a 327-character run-on *(found 2026-08-26)*

The `INPUTS USED` row of the DCF panel is a single sentence of **327 characters carrying
eight middle-dot separators**, wrapping to two lines at 1440px and measuring **127
characters per line** — the longest line left in the app after the 2026-08-26 typography
pass, which could not reach it: the row's content is an inline `<span>`, and `max-width` is
inert on an inline element. The house rule allows one middle dot per line.

**Fix:** a small label/value grid — beta, WACC, risk-free, ERP, credit spread, tax, FCF,
forecast horizon, price-as-of, each in its own cell. That is a structural change to
`DcfAudit`, not a restyle, which is why it was scoped out rather than attempted.

### 🟡 Cosmetic

Line references re-verified 2026-08-09.

- A non-existent ticker in the screener returns a row with 0% coverage rather than
  landing in `failed`, because yfinance returns an empty payload instead of raising.
  The row is greyed and unranked, so it is honest, just not obvious. *(Not re-verified
  2026-08-09.)*
- ~~Twelve distinct corner radii, with no rule~~ — **done 2026-08-14**, see the Done entry
  below. The 2026-08-13 audit undercounted: it read ten of the declarations as radius
  choices when they were `height / 2` pills written as numbers.
- The footer metadata strip uses two middle dots on one line where the house rule allows
  one. Same category as above: real, cosmetic, unactioned.
- ~~`ScorecardTab.jsx` carries an unsuppressed `exhaustive-deps` lint warning on
  `loadComps`~~ — **done 2026-08-17**, see the Done entry below. `loadComps` is now
  `useCallback` keyed on `ticker`, so the effect can list it honestly; `npm run lint` is
  clean. The line number this item carried (`:225`) had drifted and pointed at chart
  scaling. Separately,
  [PriceChart.jsx:716](frontend/src/components/PriceChart.jsx#L716) *disables* the same
  rule on `visibleGroups` deliberately, and that remains the right call — the **pinned-panel**
  effect reads `pinned` and calls `setPinned`, so it sets the very state it would have to
  depend on. **The justification this entry used to give — "rebuilding the chart on a
  marker-filter change would discard the user's zoom" — belongs to a different effect**: that
  is the *markers* effect at `:695`, whose own comment at `:693-694` says exactly that, and
  which carries no disable at all. Right rule, right verdict, wrong effect. (An earlier revision of this list
  called the ScorecardTab warning miscatalogued; the linter did emit it — that claim was
  wrong. It also cited `PriceChart.jsx:398`, then corrected that to `:344`. **Re-verified
  2026-08-18: the disable is now at `:366`**, and line 344 is a comment about discarding zoom.
  Tracked through git, `:398` and `:344` were each *correct when written* — `7cdb32a` had it at
  398, `09ee627` at 344, `8c5d467` at 366 — so this is pure drift, not miscounting, and calling
  the earlier values "wrong" would misdescribe it. Third statement of the same fact in one
  file, which is the argument for referencing by symbol rather than by line.)

  *And the suppression is doing real work. A 2026-08-18 draft of this entry claimed
  `exhaustive-deps` was "not a rule this toolchain runs", reasoning from `.oxlintrc.json`,
  which names only `react/rules-of-hooks` and `react/only-export-components`. **That was
  wrong**, and it was checked rather than argued: a probe file with a deliberate missing
  dependency draws `warning react-hooks(exhaustive-deps)` from `npx oxlint`. The rule arrives
  with the `react` plugin's defaults, not the explicit `rules` block — which is also why the
  line above is right that the linter did emit the ScorecardTab warning.*

**Done since:** `assumptions.fcf_source` and `assumptions.risk_free_rate` are now
surfaced in the DCF panel alongside `beta_source`
([ModelsTab.jsx:204-296](frontend/src/components/ModelsTab.jsx#L204-L296)). The
null-renders-green upside chip and the dead `equity_multiplier = None` line were fixed
2026-08-09 (c).

---

## Decisions needed (not bugs — your call)

### 🔵 yfinance is personal-use-only, and it carries the whole app

Raised 2026-08-14 during the data-layer audit. yfinance supplies quotes, history, news,
statements, peer snapshots, FX *and* search — every number that decides a valuation. It is
an unofficial scraper of Yahoo's internal endpoints, documented **personal-use-only**, and
Yahoo's terms prohibit automated access and redistribution.

- Running locally, for yourself: fine, and that is what the platform does today.
- **Shared, hosted or public: this is a blocker**, not a bug. Redistributing scraped Yahoo
  data through a web app is the case those terms target.

**Decided 2026-08-14: record it, keep yfinance.** There is no free, redistribution-clean,
HK-covering fundamentals API. Removing yfinance now would cost exactly the Hong Kong coverage
the platform is meant to have.

**Re-checked 2026-08-18. The decision stands; two of the three reasons given for it did not.**

- ~~"FMP's free plan is US-only"~~ — **false.** `equity.compare.peers` is a free-tier endpoint
  and covers HK: measured † 2026-08-18, `1177.HK → 2269.HK, 1801.HK, 1093.HK, 3759.HK` and
  `0700.HK → 9888.HK, 1024.HK, 1698.HK, 2518.HK`. `README.md:447` already said so. The correct
  reason is **stronger**: FMP free refuses `fundamental.income/balance/cash` with `402`, which
  is a **plan-entitlement refusal rather than a coverage one**. Said as inference, not
  measurement — the `402` was seen on a US symbol, and no FMP fundamentals call against a `.HK`
  symbol is recorded anywhere here, so this reads off the error class rather than off a test.
  Replacing one unmeasured assertion with another without saying so would repeat the original
  mistake. The only measured
  "US-only" in this repo is FMP **Starter** (paid) for **news** — `README.md:455`, and the
  option table under *"Historical news — pay, work around, or drop"* below, whose own Depth
  column reads "unknown, untested". A different plan and a different endpoint.
  *(Referenced by section rather than by line, and the reason is instructive: the first draft
  said "the table at line 539"; the edit that added this entry pushed it to 657; a later edit
  in the same session pushed it to 700. A line number naming a target in the same file it lives
  in is wrong the moment anything above it changes.)*
- ~~"the README's own 2026-08-02 measurements found the same"~~ — **overstated.** The README
  measured `402`/`403`, which are **plan-entitlement refusals, not coverage ones**. No FMP
  fundamentals call against a `.HK` symbol is recorded anywhere in this repo, so nothing here
  ever tested a geographic restriction.
- "Finnhub's international coverage is paid" — **holds**, and now corroborated externally †
  (2026-08-18): the free tier is US real-time only; HKEX sits behind a paid plan. Sourced from
  Finnhub's own pricing and rate-limit documentation, not from a call against their API — this
  repo holds no Finnhub credential, so it is the weakest-provenance claim in this entry.

*Recorded rather than silently rewritten: the wrong reason was copied into this entry from
`docs/data-sources-review.md` §5, which has been corrected at source. A decision that survives
having its reasons checked is worth more than one that was never checked.*

**Trigger: any decision to host or share this.** That decision has a data-licensing
prerequisite, not just a deployment one, and the realistic answers are pay for HK coverage
or let HK degrade to price-and-quote. The six-method `YFinanceProvider` interface is what
keeps the eventual swap bounded — worth keeping clean. Full reasoning in
`docs/data-sources-review.md` §3.

**Split 2026-08-31, because this entry was answering two different questions with one answer.**

The blocker above is about **live mode** — the app calling Yahoo on a visitor's behalf. That
still stands, unchanged. **Demo mode is a different program.** `provider = FixtureProvider() if
DEMO_MODE else YFinanceProvider()` (`data_provider.py:1355`), and an independent trace of every
subsystem under `DEMO_MODE=1` found no path from any HTTP endpoint to any external provider.
Three mechanisms do it, and they are not the same mechanism: the three risk-free rates,
`fx_rate` and `live_price` are **rebound** to demo functions during the module's own init
(`data_provider.py:1366-1370`); the ticker search skips its Yahoo fallback on a **runtime
check** (`search.py:270`), as does peer discovery before it can reach FMP or the yfinance
screener (`comps.py:498`); and the key-verification probe is **refused with a 403**
(`main.py:288`). The one outbound call demo mode does *not* suppress is `/api/ai/*` to
`http://localhost:11434` — the visitor's own Ollama, which carries no vendor data outward and
simply fails where no daemon is running.

So a hosted demo does not scrape Yahoo for anybody. What it serves is the committed fixtures:
**18 files, 421 KiB, every one tracked in git and committed since 2026-08-06, in a public
repository** — and whose own `PROVENANCE.md` states, near the top, that they are captured
third-party data outside this repository's AGPL grant.

**Which is the finding: hosting demo mode distributes nothing that is not already distributed.**
Anyone can clone the repo today and get the same 421 KiB. Hosting changes the *interface* to
that data — an API and a UI instead of a JSON file — not its availability. The decision that
carries the risk was taken on 2026-08-14, when this exact question was reviewed and the
fixtures — committed eight days earlier — were kept rather than removed: *"record it, do not
act on it yet"* (`docs/data-sources-review.md` §3). A hosted demo does not add to it.

That leaves exactly two self-consistent positions, and the state as of today is neither:

- **Accept the repository as it stands** — then hosting demo mode adds no exposure, and the
  hosting question has no data-licensing prerequisite left to clear. Only a deployment one.
- **Do not accept it** — then the thing to change is the fixtures' presence in a public repo,
  not the hosting decision. Declining to host while continuing to publish them changes nothing.

**Today the repository carries the distribution and collects none of what it could buy.** That
is the argument for resolving this either way rather than leaving it open.

What this does *not* say: that the exposure is zero, or anything about the law. It is a
statement about what hosting changes and what it leaves untouched, and it is not legal advice.
Two things are unchanged by it — **live-mode hosting is still a blocker** on the terms above,
and the fixtures are still eight companies captured on stated dates, not a data product.

*Trigger for the remaining half: any decision to host **live** mode.*

### ⚪ ~~A wrong CGB tenor would be invisible to every test~~ — closed 2026-08-20

*Raised 2026-08-19 and closed the next day by removing the possibility rather than by
detecting it. Kept because the reason the obvious fix was rejected is worth having.*

It read: `_cgb_10y` selects the ten-year with `gjqx=10` **in the URL**, so changing one
character returns a different tenor, well-formed and plausible, and **nothing fails** — the
offline tests supply their own HTML so the URL is not under test at all, and a live test can
only check a band. A band cannot close it: the whole curve sat inside **3M 1.1858 · 7Y 1.5121 ·
10Y 1.6864 · 30Y 2.1509** on 2026-08-18, and a floor above the 7Y would sit above the 10Y's own
record low of 1.59% (Feb 2025).

**The recorded fix was a live shape assertion. That was the weaker answer.** It would have
*detected* a wrong tenor on the days someone ran `-m network`. `gjqx=0` returns every tenor
**with a header row naming the columns**, so the ten-year can be selected by its own label and
the wrong tenor becomes unrepresentable instead — and the choice moves into the parser, where
an offline test can pin it. Measured: **+1,680 bytes, +8.9%**, once per calendar day, with no
latency difference over ten paired requests.

**The trade this makes, since it is not free.** A relabelled header now degrades to `usd_proxy`
where the old code would have gone on serving whatever came back. A labelled degrade beats an
unlabelled wrong number, and it has its own test.

### ⚪ ~~ChinaBond's availability~~ — the trade was taken 2026-08-20

*The record stays because the failure rate is the evidence for what was built.*

**Nine failures observed across two days**: one live-test failure inside a full `-m network`
run, one `ssl.SSLEOFError`, a sustained outage where every `gjqx` value timed out after ~12 s —
and on 2026-08-20 the same working-to-dead transition **five more times in a single session**,
twice within fifteen minutes of the endpoint answering in 3.9 s.

The open question was whether serving the last good CNY rate beats falling to a US one. **It
was taken: yes, bounded.** The gap is not a slightly worse number, it is a **US rate on CNY
cash flows** worth 30% of Tencent's fair value, against a CGB 12-month range of ~22bp.

Two things about the shape it took, because both were decisions:

- **The in-process cache was never the answer.** It already hides an outage that begins after
  one success, so it covers nothing that was broken. The two cases that bite — a process
  starting while ChinaBond is down, and the first request of a new calendar day — both need the
  reading to outlive the run, which is why it is on disk.
- **No new constant.** `CGB_MAX_STALE_DAYS` is applied to the row's **published** date in both
  paths, so "published within a fortnight" means the same thing however long ago it was
  fetched. Storing the fetch date would have let the two ages compound to 24 days with nobody
  choosing that.

**What is still open is the reachability itself**, and nothing here fixes it — the store buys a
bounded number of days, not availability. See CHANGELOG 2026-08-20.

### 🟡 A degenerate regression can still bypass the beta floor *(found 2026-08-20)*

Raised by an independent review of the change that made `BETA_MIN` interval-aware, and **it is a
gap that change created**: while the floor applied unconditionally, a nonsense regression was
clamped like any other. Now the floor is skipped when the 95% interval excludes it — and a fit
with no residual reports a standard error of zero, so its interval collapses to a point and
rejects the floor *more* confidently than any real measurement can. The guard written to catch
fabricated betas is bypassed by exactly the fabricated data it was written for.

**Half of it is closed.** A motionless series — a halted or delisted stock forward-filled to one
price — has an exactly zero residual and is refused by `market_series.beta_fit`, beside the
existing motionless-*index* guard. That is the one degenerate shape that occurs in real data, and
`test_a_motionless_stock_yields_no_beta` pins it end to end.

**What is left needs a number nobody has evidence for.** Measured 2026-08-20:

| construction | standard error | R² | refused? |
|---|---|---|---|
| motionless stock | 0 exactly | — | ✅ |
| returns exactly 0.05x the index | 2.9e-16 | **1.0 exactly** | ❌ used as 0.05 |
| constant non-zero returns | 5.2e-16 | −0.0006 | ❌ used as −0.0 |

Floating point rarely obliges with an exact zero, so `sse == 0` does not reach the second and
third. `r_squared == 1.0` would catch the second — it is exactly 1.0, and all eight fixtures are
between 0.028 and 0.691 — but not the third, and a guard that closes two of three while looking
complete is worse than one that draws its line honestly.

**Both remaining shapes require synthetic input**: real weekly closes are not an exact affine
function of an index's. So this is a latent hazard on fabricated or badly joined data, not a
defect reachable from yfinance.

**Trigger: a bars source that can produce placeholder or forward-filled series**, or evidence for
where a precision cutoff belongs. The fixtures say where real data sits (R² 0.028–0.691) and
nothing about where a threshold should be, which is why one was not invented.

**The band is now measured, 2026-08-30, and it is narrower and worse than the entry suggests.**
The skipping branch has no lower clamp at all — `min(floored, BETA_MAX)` bounds the top and
nothing bounds the bottom — so the question is not "how low can a beta go" but "how low can it
go *and still be published*". Downstream, `WACC ≤ terminal growth` refuses. Between those two
lies the band where the floor is absent and a valuation is still printed. Measured on AAPL by
substituting the beta directly:

| beta | WACC | fair value | vs price |
|---|---|---|---|
| **0.30** — the floor, i.e. the right answer | 5.61% | 271.20 | −12.8% |
| 0.20 | 5.17% | 316.25 | **+1.7% — the verdict flips from expensive to cheap** |
| 0.05 | 4.51% | 420.87 | +35.3% |
| 0.00 | 4.29% | 472.91 | +52.1% |
| −0.20 | 3.42% | 922.68 | +196.7% |
| **−0.40** | 2.54% | **21,288.07** | **+6,745%** |
| −0.45 | — | refused (WACC below terminal growth) | — |

**So the dangerous band is `beta ∈ [−0.40, 0.30)`**, and its failure mode is not a slightly low
beta: at the bottom edge AAPL is valued at 68× its own price, one hundredth of a beta before the
refusal catches it. Negative betas do *not* escape into the output the way an earlier reading of
this entry assumed — −1.5 is refused — which is exactly why the interesting cases are the
near-zero positive ones that look unremarkable.

**This is the evidence the entry said it did not have.** It does not name a threshold on
`standard_error`, and inventing one is still declined. What it does say is that a guard placed
anywhere inside `[−0.40, 0.30)` is defensible on measurement rather than taste, and that the
cheapest correct guard may not be a precision threshold at all: **restoring the lower clamp in
the skipping branch** costs one `max()` and makes the whole band unreachable, at the price of
overriding a measurement the interval says is precise. That trade is a decision; the band is not.

**The clamp was taken 2026-08-31, and the band is now `[0.00, 0.30)`.** `resolve_beta`'s
skipping branch ends at `max(fit["beta"], 0.0)`, so nothing below zero is published. Verified
zero-movement rather than assumed: `golden_scores.json` is byte-identical, none of the eight
fixtures regresses negative, and 0002_HK is the only one reaching that branch at all, at
+0.1518. Reverting the `max()` turns exactly the two new tests red.

The refusal boundary was measured more precisely on the way: `-0.40` publishes 21,288.07 and
`-0.41` is the first value refused, so the old comment citing `WACC ≤ terminal growth` as the
lower guard was describing something that fires one hundredth of a beta below the worst figure
it admits.

**An independent review corrected the reasoning, and the correction is the part worth keeping.**
The first draft argued 0.0 was a mathematical line — that below it CAPM "stops measuring". It
does not: `rf + beta × ERP` under `rf` is the *correct* CAPM price for an asset that genuinely
hedges the market, and a negative-beta gold miner or tail hedge is now discounted conservatively
at the risk-free rate. So the clamp is a **publication policy**, not a fix: a 261-week OLS slope
is not trusted far enough to print a discount rate below the sovereign. That is defensible and
it is not the same claim, and stating the stronger one would have been exactly the sort of
unexamined assertion this list exists to catch.

**Still open, and it is the interesting half.** `[0.00, 0.30)` is untouched — a beta of 0.05
values AAPL at 420.87, +35% on a figure that looks unremarkable in the audit row. Closing it
needs a precision threshold, and the position below is unchanged: the fixtures say where real
data sits and nothing about where a cutoff belongs, so one is still not being invented.
*Trigger: unchanged — a bars source that can produce placeholder or forward-filled series, or
evidence for where a precision cutoff belongs.*

### 🟡 `_us_treasury_10y`'s internals have never been tested *(found 2026-08-19)*

Three mutations inside it survive the whole suite: **removing the day-cache read**, **never
populating the cache**, and **dropping the `0 < rate < 0.25` sanity band** — the band that
exists so a provider switching to percent units cannot wreck every WACC at once.

**Not a regression.** The same three survive at `0349b1b`, verified by running them there; the
logic simply moved from `risk_free_rate` into `_us_treasury_10y` on 2026-08-19. The cause is
structural and older than either: `conftest.pinned_risk_free_rate` has always replaced whatever
function holds the fetch, so its body cannot run offline.

Testing it needs the `openbb` import stubbed rather than the function replaced — the same shape
`test_comps.py` already uses for the FMP and screener calls. Worth doing when something else
touches this function; not worth a commit of its own, since the untested code is a cache and a
guard whose failure modes are a slow request and a rejected absurd rate.

### ⚪ ~~HK stocks still use the USD risk-free rate~~ — closed 2026-08-26 *(CNY 2026-08-19, HKD 2026-08-26)*

**The ERP leg is done.** `EQUITY_RISK_PREMIUM = 0.05` is replaced by Damodaran's published
country table, vendored dated at `backend/market_risk_premiums.json` and keyed on
`financialCurrency` — US 4.46%, HK 5.01%, China 5.14%. It moves US fair values **up** ~9%
and 0700.HK **down** 1.8%, so it is two-directional and cannot be read as tuning. See the
2026-08-14 Done entry and `docs/data-sources-review.md` §4.

**The risk-free leg is now half done.** `_wacc()` applies the US 10Y to every issuer
*except* a CNY-reporting one, which since 2026-08-19 is priced off ChinaBond's CGB 10-year net
of the vendored CNY default spread and reported as `cgb_10y_less_spread`. Measured on the
`0700_HK` fixture: **469.48 → 611.62, +30.3%**, golden composite 71 → 73, no other fixture
touched. Against the 481.40 price the model moves from −2.5% to +27.1% — *away* from agreement
with the quote, which is what makes it a correction rather than tuning.

**HKD closed 2026-08-26, and the blocker recorded here was wrong in both halves.**

This paragraph read: *"an HKD-reporting issuer such as `0002_HK` still gets `usd_proxy`, because
HKMA has not responded on three attempts across six days."* Measured 2026-08-26:

- **HKMA answers.** `daily-figures-interbank-liquidity` returned HTTP 200 in 2.6 s, data dated
  2026-08-25. The three failures were real observations; treating them as a property of the
  endpoint rather than of those attempts is what turned them into a blocker.
- **And HKMA was never the right source.** Its bond-yield endpoint returns `success: true` with
  **12 of 13 fields null at every date sampled** — alive and empty, so retrying could not have
  helped however many times it was tried.

The ten-year is published by the HKSAR Government at `hkgb.gov.hk` as a daily `.xls` with an
explicit 10-year benchmark column. **3.495% on 2026-08-25** against the US 4.70%. `0002_HK` moves
97.27 → 234.83 on the fixture, composite 67 → 68, 3 of 260 golden leaves. See CHANGELOG 2026-08-26.

**The peg argument below is superseded rather than merely weakened.** It held that an HKD issuer
may take the US rate because the currency is pegged. A peg fixes an exchange rate, not a term
structure, and the two curves differ by 120bp — which is 164bp of WACC on a low-beta name.

**What this opened instead** is the more interesting half: at Hong Kong's own rate `0002_HK`'s cost
of equity (3.76%) lands **below its pre-tax cost of debt** (3.84%), which cannot be true of one
company. That is `beta x ERP` = 77bp against an 85bp credit spread — pre-existing, identical at
either rate, and now flagged rather than corrected. It fires on `O` as well, so it is a low-beta
property and not a Hong Kong one, and it belongs to the beta-credibility item above.

**How it got here, in two steps on the same day.** `risk_free_rate(fallback, currency)`
first returned `(rate, source)` with every currency still resolving to the US 10-year — no number
moved, and the point was only that the substitution became visible as `usd_proxy` beside the
`equity_risk_premium_market` naming Hong Kong or China. That made the seam; the CNY source then
attached to it. The HKD source still has nowhere to attach *from*, which is the remaining gap.

**The peg argument is weaker than this item used to claim (found 2026-08-13).** The code
justifies the USD risk-free rate by the HKD peg, and for an HKD-reporting issuer that
holds. But 0700.HK's *statements are in CNY*, and CNY is not pegged — so the largest HK
name in the fixture set discounts CNY cash flows at a rate built on the US ten-year, then
converts at spot. Rate and cash flow are in different currencies, which is the one
consistency rule a DCF cannot bend.

**The country premium has now been sized, and it does not rescue this (2026-08-14).**
This item used to hope the two legs would cancel. They do not. China's ten-year runs
~1.70% against the US 4.30%, a **−260bp** cut, while China's country risk premium is
**0.91pp** — which reaches cost of equity multiplied by beta, so roughly +0.7pp on
0700.HK. The rate cut dominates by a factor of three or so, and a −250bp move was already
measured at **624.90 → 1,225.93**. Sourcing the rate would therefore roughly *double*
Tencent's valuation.

**And a second problem surfaced that this item never named.** Discounting CNY cash flows
at a CNY rate and then converting at **spot** is not obviously right either: interest-rate
parity implies a low-rate currency trades at a forward premium, so the conversion arguably
needs a forward rate rather than spot. Today's treatment is wrong in a *named* way; the
naive fix would be wrong in an *unnamed* way, which is worse.

**Trigger discharged 2026-08-17** — the analysis is
[docs/currency-consistent-discounting.md](docs/currency-consistent-discounting.md). Spot is
correct; the worry recorded above was inverted. Discounting in the cash-flow currency and
translating the *result* at spot is algebraically identical to translating each cash flow at
its forward rate and discounting at the target-currency rate, so the interest differential
enters exactly once. Applying a forward rate on top of a local-currency discount rate would
count it twice. Method A is already the shape the code uses.

**Two numbers in this entry are wrong, corrected by measurement.** The baseline is not 624.90
— the base-year and ERP work moved it. And the effect is not "roughly double":
`terminal_growth = min(TERMINAL_GROWTH, rf)`, so lowering the rate lowers the growth cap with
it, and the recorded figure came from moving the WACC alone. Netting off the sovereign default
spread is worth only ~1.66% of the change (601.62 → 611.62) — the contestable half is the cheap half.

**Re-measured 2026-08-19, and the replacement numbers were wrong too.** This entry then said
baseline **680.99** and effect **+50.5%**. Both reproduce exactly — but only *without*
`market_bars`, i.e. on the vendor's reported beta of 0.745 rather than the **1.3192** this
fixture has regressed to since 2026-08-14. Every `main.py` endpoint passes market bars, so
those were never the app's figures. With them:

| risk-free | WACC | terminal g | fair value | vs the 481.40 price |
|---|---|---|---|---|
| 4.30% (today) | 10.43% | 2.50% | **469.48** | **−2.5%** |
| 1.70% (China 10Y raw) | 7.87% | 1.70% | 601.62 | +25.0% |
| 1.10% (10Y − spread) | 7.28% | 1.10% | **611.62** | +27.1% |

**The effect is +30.3%, not +53.2%** — and the baseline now sits *within 2.5% of the market
price*, where the old figure claimed +41.5% undervalued. A correction that takes the model from
agreeing with the quote to disagreeing by 27% passes direction-blindness more clearly than
before, not less.

**A third number is wrong too, found 2026-08-18.** The **−260bp** above is the raw 10Y gap
(1.70% vs 4.30%). The *applicable* move is **−320bp**, because the CNY risk-free is the 10Y net
of the CNY default spread — `1.70% − 0.60% = 1.10%` against 4.30%.
[docs/currency-consistent-discounting.md §3](docs/currency-consistent-discounting.md) had
already said so in as many words — *"that is −320bp against the current 4.30%, not the −260bp
TODOLIST recorded"* — and this entry never picked it up. Note the two figures answer different
questions and the paragraph above needs the second one, since it is reasoning about what
sourcing the rate would actually do.

**New trigger: what the terminal-growth ceiling means in a low-nominal-rate currency.**
Adopting a 1.1–1.7% CNY risk-free rate does not only change a discount rate — through the
cap it asserts that Tencent's cash flows grow at 1.1–1.7% in perpetuity, which is a macro
forecast arriving through the back door. The terminal share rises 62.96% → 73.4% with it, so
more of the answer rests on the assumption that just became questionable. The analysis lists
three candidate resolutions and picks none.

**"Data is not the blocker" was too confident — corrected 2026-08-18.** This paragraph used to
end: *"China's ten-year is widely published and HKMA publishes Exchange Fund yields free
(unverified from this machine, 502 on 2026-08-14)."* Three things are wrong with that sentence,
and they matter because it is the line that makes this item look ready to start.

1. **It pairs two currencies as if they served the same need.** HKMA publishes **HKD**. The
   problem in this paragraph is **CNY** — 0700.HK reports CNY, and CNY is not pegged. HKMA
   cannot address the 0700.HK case at all. It *can* convert the peg assumption into a
   measurement for an HKD-**reporting** issuer, which is worth having — but that is the half of
   this item that is already defensible. `docs/data-sources-review.md` §4 makes this distinction
   with a ⚠️; this entry lost it. *(A 2026-08-18 draft of this sentence offered "0005.HK,
   0941.HK" as the HKD-reporting example. Both are wrong — see point 4 — and the error survived
   into a revision that already contained its own refutation four points below.)*
2. **It names an endpoint that cannot supply a ten-year †.** HKMA's Exchange Fund Bills & Notes
   yields run **7-day to 2-year only** — issuance of Notes at three years and above **ceased in
   2015**. Longer tenors live in the separate Government Bond Programme series
   (`gov-bond/instit-bond-price-yield-daily?segment=Benchmark`). Read off HKMA's published API
   documentation, not off a response — the endpoint has never answered from here.
3. **The endpoint is still unreachable, and now twice †.** On 2026-08-18 it returned
   `http_code=000` after 25 s, while `api.hkma.gov.hk/` itself answered `404` in 1.2 s and
   `data.gov.hk/` answered `302` in 0.8 s — the host resolves and completes TLS, the API path
   does not answer. With the `502` on 2026-08-14 that is two failures **four days apart**.
   Both are single observations from one machine on one network; neither distinguishes a broken
   endpoint from a filtered route.
   *(A draft of this bullet said "twelve days apart" — 2026-08-14 to 2026-08-18 is four. Two
   failures four days apart is thinner evidence of a pattern than twelve would have been, and
   the correct number is the one that has to carry the argument.)*
4. **And it serves nothing this list curates, though more than that in the wild †.** Measured
   2026-08-18 off `financialCurrency`: of the six HK names in `PEER_SUGGESTIONS`, **none reports
   in HKD** — `0700.HK`, `9988.HK`, `3690.HK` and `0941.HK` report CNY, `0005.HK` and `1299.HK`
   report **USD**. Across a wider sample the split is **30 CNY / 14 HKD / 4 USD**, so the HKD
   segment is real (`0001`, `0002`, `0066`, `0388`, `0823`, `2388` …) — the curated six are
   simply an unrepresentative sample of it. *Counts rather than percentages, because they have
   to reconcile: 49 tickers were queried and **48 resolved**; `0011.HK` returned
   `404 Quote not found` and is excluded. Quoting "61/29/8%" summed to 98% and left the 49th
   unexplained.* † Both figures were live `info` reads with no HKD-reporting fixture to check
   them against. **Captured 2026-08-19**: `0002.HK` (CLP Holdings) is now in the set,
   HKD-reporting and DCF-eligible. The obvious candidates were not usable — `classify` sends
   `0016.HK` to `real_estate_reit` and `2388.HK` to `financials_bank`, and `dcf_applies` is
   `False` for both, so neither can exercise a discount rate at all.

**So data *is* a blocker, on both halves.** For CNY, HKMA is the wrong source. For HKD, the
right source has not responded on either attempt — and the HKD case barely arises in this
platform's actual coverage. **Reachability is a prerequisite to discharge before this item is
scoped**, not a caveat to carry into it.

> **Correction (2026-08-26).** The prerequisite was discharged and the conclusion did not survive
> it. HKMA is reachable; its yield series is empty; and the source that has the ten-year is
> `hkgb.gov.hk`, which was never checked because every attempt went to HKMA. "The right source has
> not responded" was a statement about the source being *looked at*, not about the one holding the
> number. The lesson worth keeping is narrow: three failed attempts at one host is evidence about
> that host, not about the availability of the figure.

*(Distinct from the reporting-currency mismatch fixed 2026-08-10. That was a units bug —
CNY cash flows compared against an HKD price. This is a choice of discount-rate inputs,
and it is still open.)*

### 🔵 HK charts still have almost no event markers

SEC filings gave US tickers ~5 years of dated events (AAPL: 278 events, 140 dates),
but EDGAR has no CIK for HK listings, so `0700.HK` falls back to the ~10 news dates
yfinance provides. The chart states this rather than looking broken.

**Options:** accept the asymmetry; scrape HKEX news/announcements (they publish a
filings feed, but it is not in OpenBB and would need its own adapter); or drop event
markers for HK entirely so the gap is not implied to be a bug.

### ⚪ ~~Volume pane shows no intermediate axis ticks~~ — closed 2026-08-26

Filed as cosmetic, with *"a taller volume pane"* offered as the fix if it ever mattered.
The first half was right. The second was already in the code and had never worked: the
pane asked for 110px via `chart.panes()[i].setHeight(110)` and rendered at **27px**,
because lightweight-charts converts `setHeight` into a stretch factor against the panes
existing at that moment, so a call made while later panes are still being added is diluted
by every one of them. It was never a short pane by choice, and nothing failed to say so.
RSI carried the same fault and fell to 27px whenever MACD was switched on.

Replaced with `setStretchFactor`, applied once after the last pane exists. Volume renders
at 110px (**+307%**) and the axis now draws 150M/200M/250M/300M rather than a lone badge —
exactly the ticks this item recorded as unobtainable. The custom price formatter tried and
reverted here was treating the symptom.

*(Lesson worth keeping: "the library will not do this" was really "the call we make is
silently ignored". Neither the code nor a test observed the rendered height.)*
See CHANGELOG 2026-08-26.

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

**The SEC-filings row is no longer a proposal — it shipped.** This paragraph used to end
*"Decide whether you want that before it gets built."* It was built: `get_filings` in
`data_provider.py` (`provider="sec"`, `FILINGS_LIMIT = 400`), merged with news at
`/api/stock/{ticker}/events`, and rendered as markers by `PriceChart.jsx`. It needed **three**
new categories rather than the one this entry predicted — `earnings`, `material` and
`insider` — which now sit alongside `company` and `macro`, with insider filings defaulted off
because they are the bulk of the feed.

*Its measured depth also disagrees with the table above, which was a pre-implementation
survey (2026-08-02) rather than a measurement of what was built.* Post-implementation the
repo records **~5 years and 278 events for AAPL**, against the table's **2.5 y and 200
filings**. One conflict is unresolved: `data_provider.py` says **209 distinct dates** while
two other places say **140**. The likely reconciliation is that 209 counts the raw fetch and
140 the set surviving the category filter, but that needs a live EDGAR call to confirm and is
recorded here unresolved rather than guessed at.

**What remains open is the part the table is actually about: paid historical *news*, and HK
in particular.** No option listed solves HK, and SEC filings did not either — they are US-only
by construction (`if "." in ticker: return []`).

---

## Done

### ✅ 2026-08-19 — peer discovery gets a tier that needs no key

**Was:** `suggest_peers` was two tiers — `PEER_SUGGESTIONS.get(t) or _fmp_peers(t)` — so a
ticker outside the 23 curated names with no FMP key, or an FMP call that failed, got **no peers
at all**. For a company type whose DCF is refused (REIT, bank, pre-profit) that meant **no
model-based valuation whatsoever**: measured on `O`, the football field dropped to
`methods_scored: []` and only the analyst-target row remained, which `triangulate` deliberately
excludes from scoring.

**Now:** `PEER_SUGGESTIONS.get(t) or _fmp_peers(t) or _screener_peers(t)`
([comps.py](backend/comps.py)) — a third tier on yfinance's keyless screener. Ordered *below*
FMP deliberately, which makes it purely additive: it can only fill a gap that is currently
empty, so no existing answer changes for anyone holding a key.

**Measured 2026-08-19 †, 18 non-curated names across both regions: peers for 18 of 18, a full
four for 16.** The two thin ones are genuinely thin industries, not failures — `0388.HK` (HKEX)
returns one HK peer and `0823.HK` (Link REIT) two. Product-level effect on a keyless install,
through the real pipeline on the `O` fixture: `peers_used` 0 → 4, implied values 0 → 5, and the
"Peer multiples" bar appears on the football field where there had been none.

**The five predicted obstacles, against what implementing them actually cost.** All five were
real. Three turned out cheaper than written, and one was wrong in a way only running it caught.

1. **Industry em-dash — real, and cheaper.** The entry said it "needs a mapping, not a naive
   character replace". The mapping is right but the reason given was not: measured 2026-08-19, a
   plain replace round-trips **all 145** industries, and no screener label contains a spaced
   hyphen of its own. `comps._SCREENER_INDUSTRY` is derived from `yfinance/const.py` in two
   lines and is used for a different reason — an industry the pinned build does not know misses
   the lookup and yields no peers, where a replace would emit a rejected spelling that looks
   identical to an empty screen. `backend/data_provider.py`'s comment carried the same
   overstatement and was corrected with this change.
2. **Self-inclusion — real, one condition.**
3. **Duplicates — real, and the stated tell was wrong.** The entry said `marketCap == 0` is the
   only signal for `SPG-PJ`. Live it is `marketCap: None`, not `0`; a truthiness test covers
   both, but an equality test against `0` would have passed it straight through.
4. **Foreign names — real, and it collapsed into 3.** One filter handles both: OTC listings are
   where every cross-listing sits, so dropping them removes `TOYOF`, `BYDDF` and `UNBLF` *and*
   the genuinely foreign `STGPF` in one rule. That a peer should trade where the target trades
   is the answer to obstacle 4, not a side effect of fixing 3.
5. **Region from suffix — real, one line.**

**The obstacle nobody predicted, and it was found only after the first implementation passed.**
OTC arrives under **four** exchange codes, not one. A filter written against the obvious
`exchange == "PNK"` passed `WMMVF` (OTCID) and `WMMVY` (OTCQX) — both Walmart de México — as
**two of Costco's four peers**, and `CMPGY`+`CMPGF` as two of Starbucks'. Measured over 36
screens — 18 industries x 2 regions, 1,162 rows †: PNK 412, OQX 23, OID 9, OQB 3 — 35 rows the
first filter would have leaked, on 447 OTC rows total. All four share a `fullExchangeName`
prefix (`"OTC Markets ..."`) and nothing else, and that field was present on all 1,162 rows, so
the tier matches the name rather than the code. After the fix Costco screens to WMT, TGT, DG,
DLTR and Starbucks to MCD, CMG, YUM, QSR.

**The trap was handled in the same commit,** as the entry demanded: `conftest.no_live_screener`
is an `autouse` fixture stubbing `_screener_peers`, the same shape as `pinned_risk_free_rate`.
It stubs the whole function rather than `yf.screen`, because the target's own snapshot is
fetched *first* — patching only the screen call would still leak.

**Every guard is mutation-tested: 13 mutations, 13 caught.** Two needed a unique anchor first —
`[:MAX_AUTO_PEERS]` also appears in `_fmp_peers`, which is the same wrong-function landing
recorded on 2026-08-18. **Three of the thirteen were added because a first pass of eight left
them alive**, and one of those three was the worst survivor available: flipping `sortAsc=False`
to `True` turns "the four largest names in the industry" into "the four smallest micro-caps",
a total inversion of peer quality, and it passed all 467 tests. The fixture was capturing
`yf.screen`'s kwargs and discarding them. **A mutation set that only mutates what you thought
to test is a measure of the test suite's self-consistency, not its coverage.**

**The cache is keyed on `(region, industry)`, not on the ticker** — see `_screened_industry`.
An earlier revision keyed it per ticker while its own docstring claimed it kept the platform to
"one screen per industry rather than one per name". It did the opposite: `score_batch` fans a
watchlist across a thread pool, so fifty REITs would have issued fifty concurrent
unauthenticated screens. The self-exclusion moved to read time, which is the only part of the
answer that varies within an industry — and it made the returned list a fresh slice, so a cached
ranking shared across threads can no longer be mutated by whoever received it.

**Left open, deliberately: the ordering.** FMP sits above a tier that beat it on every name
where the two disagreed and a human can judge — `RIVN` (TSLA, TM, GM, RACE vs Honda, Magna,
**Best Buy**, Genuine Parts), `SBUX` (MCD, CMG, YUM, QSR vs Airbnb, Marriott, MercadoLibre,
Royal Caribbean), `ABNB`, `CAT`, `LMT` †. They agreed exactly on `O` and differed on 17 of 18.
That is suggestive, not sufficient: judging peer quality by eye across 18 names is not a
measurement, and reversing the order would change the answer for key-holders, which is precisely
what ordering it below avoided. **Reopening condition: a scored peer-quality metric.** Until one
exists there is nothing to decide on.

### ✅ 2026-08-17 (f) — a dispersion band, and two indicators tested rather than argued

Full detail in `CHANGELOG.md` under 2026-08-17 (f). Frontend **46 → 54 passing**; no
backend code touched. Three of the six candidate indicators were decided by running a test
on real data, and two of those tests killed the candidate.

- **Added a ±2 SD band**, off by default, centred on the MA20 already drawn — deliberately
  not called Bollinger Bands, because `%B` is an exact affine transform of a z-score
  (`0.5 + z/2k`, pinned to ten decimal places) and the eponymous name would import a
  trading claim. It fills the chart's only real gap: nothing else displayed dispersion.
  Not sent to the AI, structurally — it is computed in the browser and never reaches the
  backend.
- **Fibonacci and the Stochastic were rejected by measurement**, and moved to
  *Deliberately not doing* with the figures, so neither gets re-argued.
- **Fixed a README claim** that described indicator windows as measured in trading days,
  which `09ee627` changed to bars on 2026-08-13.

Two things worth carrying forward:

- **A test caught an error that review did not.** The z-score ceiling for a window of *n*
  points is `sqrt(n-1)` under the population divisor and `(n-1)/sqrt(n)` under the sample
  one. Both this list's author and the analysis it was built on had them swapped. It
  survived because the largest deviation ever observed in the measured data was 4.00,
  which sits below both candidate ceilings — **the empirical check could not have
  distinguished them.** Only a test deriving the bound from the most extreme possible
  window did. Where a measurement cannot separate two hypotheses, derive.
- **Two of these decisions cost an afternoon of measurement and are now permanent.**
  Arguing about Fibonacci is unbounded; a permutation test on 12,461 bars is not. The same
  shape as the plausibility tests: replace an opinion with a number and the question stops
  coming back.

### ✅ 2026-08-17 (e) — three things the model said that the world does not

Full detail in `CHANGELOG.md` under 2026-08-17 (e). A review of the valuation engine run by
*executing* it over every fixture and reading the output, rather than by reading the code.
Backend **409 → 423 passing**, frontend 46. One golden metric moved, predicted before the
change was made.

- **Yahoo's EV multiples divided an HKD enterprise value by CNY financials.** 0700.HK read
  15.705× where the like-for-like figure is 14.277×. Everything the app computes itself was
  already converted; a pre-divided vendor ratio was the one place the mismatch arrived baked
  in. Also fixed a compounding double-conversion in `comps.ev_implied`.
- **A REIT was charged 21% corporation tax** where its own statements show 7.4% and its
  marginal rate is approximately zero. WACC 6.05% → 6.58%, fair value 36.00 → 27.04.
- **A regressed beta now reports its own precision.** XOM's R² is 0.028 and its 95% interval
  [0.08, 0.49] spans a fair value of 123 to 228, against one published figure of 157.30.

Three things worth carrying forward rather than filing as achievements:

- **A credibility band on a value is not a test of a measurement.** `BETA_MIN/MAX` had been
  doing duty as both since the regression landed, and nothing anywhere asked whether the
  regression explained anything. The same shape as the `__init__.py` and README warnings
  below: a check that looks like it covers something it does not.
- **The fixtures already held the answer to the tax question.** `Tax Rate For Calcs` sits in
  the same dict the model reads, showing O at 7.4%, AAPL 15.6%, XOM 31%, JPM 21.4%. The
  statutory default is still right for the other three — but it was never checked against the
  statements sitting beside it.
- **Reading the code would not have found any of these.** All three surfaced only by running
  the model over real payloads and asking whether the output described a real company. A
  5.64% cost of equity for an oil major is obvious on screen and invisible in a diff.

### ✅ 2026-08-17 (d) — the README's instructions, followed literally

Full detail in `CHANGELOG.md` under 2026-08-17 (d). Summarised here because it changed no
application code and because one open item came out of it.

An audit of every command the README gives a first-time user, checked against what the repo
actually ships. **No application code changed** — 409 backend, 46 frontend, ruff and oxlint
clean, `vite build` green, identical before and after.

One instruction was broken outright: **`pytest` was installed by no documented step**, while
§Tests told you to run it. It exists in exactly one place in the repo, `requirements-test.txt`,
which the README described as what *CI* installs — framing it as someone else's file. Verified
in a fresh 3.14.6 venv rather than the working one, which has had `pytest` all along and is
precisely why this survived so long.

The rest were true statements that had stopped being true. The Node floor said `>=22` while
the toolchain wants `^20.19.0 || >=22.12.0` — wrong in both directions, since 22.0–22.11
satisfied the document and failed the tools, and 20.19+ worked and was excluded. `.\start.ps1`
was offered as a peer of `start.bat` without noting that a stock Windows policy refuses to run
it. And `pip install -e .` ran *after* the 107-package install despite being the only step that
reads `requires-python`, so a wrong interpreter was rejected at the end of the download instead
of 8.8 s in. `start.bat` and `start.ps1` also gained the venv guard `start.sh` already had.

Worth carrying forward as a warning rather than an achievement:

- **Nothing in the suite reads the README.** CI gates the code four ways — ruff, pytest, oxlint,
  build — and gates the instructions not at all. Every defect above coexisted with 409 green
  tests, because no test has any opinion about what the documentation claims. The install path
  *is* documentation, and documentation is the one part of this repo with no automated reader.
  The same shape as the `backend/__init__.py` warning below: a green suite that is structurally
  incapable of seeing the thing that is broken.

The CI-never-installs-the-runtime-set gap noted in the entry below is unchanged, and is now
tracked as its own item under *Next* rather than living only inside a dated entry.

### ✅ 2026-08-17 — the project became something a stranger can clone and run

Full detail in `CHANGELOG.md` under 2026-08-17 (a), (b) and (c). Summarised here because
three entries above changed as a result.

Scope changed from *portfolio piece only* (2026-08-14) to **a runnable source project**;
Docker and binary releases stay out. `backend/` is now a real Python package installed with
`pip install -e .`, the three requirements files became one, the frontend reaches the backend
through a Vite proxy on a pinned port, `start.sh` covers macOS/Linux, and the README leads
with install and shows five screenshots. Backend **408 → 409 passing**, frontend 46,
`npm run lint` clean for the first time.

Two things worth carrying forward as warnings rather than achievements:

- **The suite does not protect `backend/__init__.py`.** Deleting that empty file keeps all
  409 tests green — pytest puts the repo root on `sys.path`, so `backend` still resolves as a
  namespace package — while silently breaking `pip install -e .`. Anyone tidying 0-byte files
  gets an all-green signal on a broken install.
- **CI never installs the runtime requirements set.** It installs `requirements-test.txt`. A
  broken runtime pin, or a missing runtime dependency such as `openbb`, passes CI green.

Also: 38 `.claude/agents/*.md` files were removed from the whole git history with
`git filter-repo` (tree hash byte-identical before and after). Measured afterwards and worth
knowing generally — **GitHub still serves removed files to a direct request for the old SHA**
after a force-push, because that does not trigger garbage collection. Recorded, not chased;
the content held no credentials and no personal data.

### ✅ 2026-08-14 (f) — the price is as fresh as the feed allows, and says how fresh

Backend **402 → 408 passing**, frontend 46.

The price rode inside `get_fundamentals`'s 15-minute cache, on top of Yahoo's own 15-minute
delay, so the valuation screen ran up to **~30 minutes** behind the market — `/analysis`
returned 441.0 twice seconds apart while the uncached `/quote` said 441.2. Now refetched on a
60-second cache, so it is ~15 minutes: the vendor's floor, which no free feed clears.

Five consumers read the price and **all five read the same two `info` fields**, so one refresh
point covered the DCF upside, the football-field price rule, the gap bridge, the momentum
metrics and the score history without touching a single call site.

`price_as_of` and `price_delayed_by_minutes` now appear in the audit row. Both are the
vendor's own numbers (`regularMarketTime`, `exchangeDataDelayedBy`), forwarded rather than
estimated — the price was the denominator of the headline upside and the only input on that
screen with no provenance at all.

**Market cap is deliberately not refreshed**, because it feeds the WACC weights and refreshing
it would make fair value drift intraday with no filing having changed. A test pins it: two
different prices must leave `fair_value_per_share` and `wacc` identical while `upside_pct`
moves. The cost is that recomputing P/E from the displayed price gives a marginally different
answer, which is why the row says which figures are live and which are as of the snapshot.

**The batch screener keeps the snapshot price** — a stale quote cannot reorder a ranking, and a
fetch per ticker would roughly double a fifty-name run.

Worth recording: the staleness guard from (e) caught its own author. After editing these files
the health endpoint reported `source_changed_since_start: true` before anything was tested by
hand, which is exactly the loop it was built to close.

### ✅ 2026-08-14 (e) — the app notices when the backend is running old code

Backend **399 → 402 passing**, frontend 46.

`GET /api/health` now returns `source_changed_since_start` — a digest of `backend/*.py` taken
at import, re-checked per call — and the page shows a banner when it flips. `/health` also
replaces `/ai/status` as the frontend's 30-second poll, since it already carried the same AI
block.

Built after the equity-bridge panel appeared to be missing: it shipped at 14:17 against a
backend started at 13:28, so the API never returned `diagnostics.equity_bridge`, the panel
correctly rendered nothing, and that was indistinguishable from a feature never built. Third
hand diagnosis of the same failure in one day.

**The digest reads text rather than bytes**, and that detail is the whole difference between a
useful signal and one people switch off. A byte hash false-positived immediately: `git
checkout` restored `sector_weights.py` with 252 CRLF where the process had loaded LF, so the
guard called a git-clean file stale. Pinned, and mutation-checked against `read_bytes()`.

**`--reload` was tried first and rejected**, which is recorded in
[docs/development.md](docs/development.md) (in the README until 2026-08-28) because the
failure is not obvious: WatchFiles logged `detected changes in 'backend\main.py'.
Reloading...`, the replacement worker never started, and the old process kept serving while
the log claimed a reload had happened. It also orphaned a child holding port 8000 after the
parent died, so the next start failed `WinError 10048` and the socket needed freeing by hand.
A reload that lies is worse than no reload.

### ✅ 2026-08-14 (d) — the equity bridge carries four of its five terms

Backend **389 → 399 passing**, frontend 46.

`financial-models-reference.md:38` states the bridge as
`EV − Net Debt − Minority Interest − Preferred + Non-operating Assets`. The model
implemented **one** term — `dcf_valuation` never read the balance sheet at all — and said so
nowhere: a grep of `frontend/src/` for `totalDebt`, `balance_sheet`, `minority`, `associate`
or `invest` returned **zero hits**, and none of the 27 caveat strings the UI already shows
mentioned it. The omission was deliberate (`comps.py:545` at the time) and completely silent.
*(Line reference needs re-verification: `comps.py:545` no longer holds this comment, and
`dcf_valuation` now lives in `financial_models.py`, not `comps.py`. The nearest surviving
"deliberately absent" comment, `financial_models.py:819`, documents only the narrower
associates-at-cost omission recorded below and is not a faithful stand-in for the original
citation, so no replacement line number is given here.)*

Three terms are now read from the newest balance sheet; the fourth is reported and excluded.

| | now | was | of which MI | of which marked securities |
|---|---|---|---|---|
| 0700.HK | 498.67 (**+3.6%**) | 427.75 (−11.1%) | −11.23 | +82.11 |
| AAPL | 140.00 (−55.0%) | 134.67 (−56.7%) | 0 | +5.33 |
| MSFT | 269.64 (−44.7%) | (−45.7%) | 0 | +4.89 |
| XOM | 157.30 (+3.7%) | 158.98 (+4.8%) | −1.75 | +0.07 |
| O | 36.00 (−42.6%) | (−42.8%) | −0.73 | +0.86 |

Goldens: 0700.HK `dcf_upside_pct` 28 → 47 (composite 70 → **71**), XOM 57 → 55. Two
directions, no tier moved. AAPL and MSFT moved in fair value but are anchor-clipped, so no
score changed.

**Both blockers this had been parked on turned out to be measurable.** The lines nest as an
*exact identity* — 342,409 + 6,303 = 348,712 on both of 0700.HK's periods — so reading the
parent avoids the double count entirely. And "held at cost" applied to only a third of the
portfolio: `Investmentin Financial Assets` is exactly available-for-sale plus FVTPL, both
already carried at fair value. Using them reads a filed mark rather than making one, which
is why the verdict can flip with no assumption entering the headline. Associates stay out.

**One figure, four subtraction sites.** `net_debt` was subtracted in four places — headline,
WACC × terminal-growth grid, growth sweep, normalised base year. A bridge applied to some of
them would print a sensitivity table whose centre cell disagreed with the fair value above
it. Both grids now assert their centre cell *is* the headline; mutation-checked by reverting
one site, which fails that test and nothing else.

**No cross-year fallback.** The bridge uses `_value_at`, not `_latest`. MSFT is the live
case: it reports `Long Term Equity Investment` at 2025-06-30 and nothing at 2026-06-30, and
`_latest` would have imported a year-old balance into today's valuation — the period-drift
defect this codebase has already fought twice. A vanished row reads nil and is *named*; a
row never reported is silently nil, because flagging that would have warned on all seven
fixtures and taught the reader to ignore warnings.

Left open, both above: associates at cost, and `comps.ev_implied` still on the one-term
bridge — a ~71/share basis difference on 0700.HK between the DCF bar and the peer bars
beside it.

### ✅ 2026-08-14 (c) — beta and relative strength are measured, not read

Backend **373 → 389 passing**, frontend 46. Both defects had one root cause: the platform
trusted vendor *scalars* where the honest answer needs a *series*.

**Beta is regressed.** `market_series.beta` runs cov/var over five years of weekly returns
against the home index (`^HSI` for `.HK`, `^GSPC` otherwise), cross-checked to 1e-9 against
numpy's covariance and a least-squares slope. It sits above the existing ladder; everything
below it keeps its old order, so a history outage restores exactly the previous behaviour.

**Relative strength is measured against the index the company trades on.** Both legs come
from closes. The obvious fix — read `^HSI`'s own `52WeekChange` — turned out to be a trap:
measured live, `^GSPC` reports that field in **percent** (20.918) and `^HSI` in **decimal**
(0.500), and the Hang Seng value matches neither its own history (−1.41%) nor any unit
reading of it. Using it would have scored 0700.HK at ≈−63.7% instead of −23.79%.

Measured on the committed fixtures:

| | beta was | beta now | composite | note |
|---|---|---|---|---|
| XOM | 1.0 *(default)* | **0.2888** → 0.30 | 70 → **74** | fair value +103% |
| 0700.HK | 0.745 *(vendor)* | **1.3192** | 73 → **70** | fair value −34% |
| AAPL | 1.086 | 1.1546 | 65 → 65 | −4.6% fair value |
| MSFT | 1.099 | 1.1412 | 71 → 71 | −3.0% fair value |

Two directions again, and **no tier moved**. XOM's +103% is the size of the error that was
already there: a neutral 1.0 standing in for a company whose measured beta is 0.29.

New fixture type: `tests/fixtures/bars/`, weekly closes for the seven tickers plus both
indices, 144 KB. `capture_fixtures.py` grew `--bars-only` / `--fundamentals-only`, because
regenerating the statements refetches live data and moves every pinned figure with it.

**Three things found while building it, all fixed here:**

- `_ttl_cached` keyed only on ticker, ignoring other arguments. Caching `get_history` on
  that key would have served the chart's 1y hourly bars to the 5y weekly beta request, or
  the reverse. Now keyed on the full argument list.
- `ModelsTab` printed "(reported X, **not credible**)" whenever beta came from anywhere but
  the vendor. With a measured beta on top that became an accusation against perfectly good
  data, so the backend now reports `beta_reported_credible` and the UI says "vendor X" and
  only adds "not credible" when the band actually rejected it.
- `.src-tag.peer_median_relevered` had no style at all — the class is the whole source
  string, so `.peer_median` never matched it. Unstyled since the re-levering tier was added.

### ✅ 2026-08-14 (b) — the equity risk premium is sourced, and the data layer is audited

Backend **366 → 373 passing**, frontend 46. Two outputs: the ERP stops being invented, and
the whole data layer gets a written review at `docs/data-sources-review.md`.

**The ERP is per market, dated and sourced.** `EQUITY_RISK_PREMIUM = 0.05` — one number for
every market and every year, no source, no date — is replaced by Damodaran's published
country table, vendored at `backend/market_risk_premiums.json` and keyed on
`financialCurrency`, the currency the discounted cash flows are actually in.

| Market | was | now | effect |
|---|---|---|---|
| United States | 5.00% | **4.46%** | AAPL +9.2%, MSFT +9.8%, XOM +9.2% |
| Hong Kong | 5.00% | **5.01%** | ~nil |
| China (0700.HK reports CNY) | 5.00% | **5.14%** | 0700.HK **−1.8%** |

It moves US valuations up and Tencent's down, so it cannot be read as tuning — and a test
pins that two-directionality so a future snapshot update cannot quietly make it one-way.
The only golden score that moved is 0700.HK's `dcf_upside_pct`, 82 → 80; every other name
is anchor-clipped and unchanged, and no composite or tier moved.

Two traps encoded rather than discovered later. Damodaran's country figure is **additive**
(total = mature market + CRP), so consuming the total *and* adding the CRP would count the
country twice — only the total is used, and a test asserts the snapshot's own arithmetic
across all three markets (each implies the same 4.23% mature premium, which is how the
figures were checked on retrieval). And the key is `financialCurrency`, deliberately unlike
`tax_rate_for`, which keys on the trading currency: tax follows the filing jurisdiction, a
discount rate follows the money. 0700.HK trades HKD and reports CNY, so it is priced off
China — which is also the right economic answer for a Chinese operating business.

Vendored rather than fetched because Damodaran republishes twice a year: an xlsx parser on
the request path would be fragile for no benefit and would put a network call inside the
offline suite. Updating the file is a manual, dated act, which is the point.

**One existing test needed repair, and it was a real side effect.**
`test_correcting_the_currency_also_corrects_the_wacc_weights` builds its "mixed" case by
flipping `financialCurrency` — which now also selects the ERP, so the test stopped isolating
the weighting effect it is named for. The ERP is pinned across both runs there now.

**Also found while measuring:** O moves +15.4% against a +5.8% enterprise-value change.
Not a bug — its net debt is 59% of EV, so the equity bridge gears the move 2.44×. AAPL and
XOM have near-zero gearing and move 1:1 with EV.

**The data-layer review** records what the platform actually runs on: one source (yfinance)
plus three narrow helpers, the three occasions that source has already been proven wrong in
this codebase, and — new — that yfinance is **personal-use-only**, which is fine locally and
is a blocker to resolve *before* the app is ever hosted or shared. Decision taken: record
it, keep yfinance, because no free source covers HK fundamentals and removing it today
would cost coverage. See the new 🔵 item under Decisions needed.

### ✅ 2026-08-14 — the DCF bar carries its third assumption, and radius gets a rule

Backend **357 → 366 passing** (16 network-deselected), frontend 46, `ruff` and `oxlint`
clean apart from the pre-existing `exhaustive-deps` warning.

**The football-field DCF bar now spans both bases.** The bar already unioned in the growth
sweep; both it and the sensitivity grid move a *rate* while holding fixed the level that
rate is applied to, so neither could say what an unrepresentative starting year would do —
and that error is undamped, because fair value is homogeneous of degree one in base FCF.
`_dcf_band` now unions `fair_value_normalised` in the same shape, naming `+ base year` in
the basis only when it actually moved an edge.

Measured on the fixtures (risk-free pinned at 4.3%), it fires on two of four and is *not*
one-directional, which is what makes it a band rather than a thumb on the scale:

| | reported | normalised | bar before | bar after |
|---|---|---|---|---|
| XOM | 71.75 | 102.17 | 59.25–86.35 | **59.25–102.17** |
| MSFT | 248.51 | 321.75 | 211.58–290.97 | **211.58–321.75** |
| AAPL | 129.29 | 144.27 | 109.76–151.89 | unchanged (inside) |
| 0700.HK | 663.32 | 628.00 | 561.47–781.62 | unchanged (inside) |

The tick still marks the reported-year answer, so this widens the band without touching
the headline. Conviction is computed from method *midpoints*, not bar centres, so a wider
bar moves the overlap zone and nothing else — pinned by a test, because reading the centre
instead would silently make every conviction grade a function of bar width. Nine tests
added; mutation-checked by disabling the guard, which failed three of them including the
end-to-end one.

**Corner radius has a rule.** Forty-two declarations carrying twelve distinct values, now
four tokens over thirty-one declarations and eleven documented specials. The 2026-08-13
audit had this wrong in a way worth recording: it counted ten declarations as radius
choices when they were `height / 2` — `.pillar-track` and `.pillar-fill` are 8px tall at
4px, `.ff-envelope` 6px at 3px, the scrollbar thumb 8px at 4px. Those are pills, and
collapsing them into a numeric tier as planned would have flattened real pills into
squircles. `--r-pill: 999px` says what the number hid; the conversion is pixel-identical
for the exact halves and imperceptibly rounder for `.quality-*` and the 3px swatches,
which were already over-rounded past their own half-height.

`--r-tag: 4px` / `--r-control: 6px` / `--r-surface: 10px` cover the rest. The only visible
movement is four chips 5 → 6px and five surfaces 8 → 10px. `.tier-badge` (14px) and
`.chat-msg` (12px) were **kept** as documented specials rather than normalised — radius
does not scale with a box, and `--r-surface` on a 64px square reads as a rounded rectangle
where 14px reads as the squircle the grade letter sits in. `:focus-visible` and the
concentric `.ff-track` / `.ff-bar` pair stay literal for reasons now written beside them.

Worth stating plainly: **this change has no test.** The 46 frontend tests are behavioural;
none asserts a radius, and the project has no visual regression harness. The safety net
was a per-line pre-assert during the edit plus a production build.

### ✅ 2026-08-13 — the football field triangulates, and the base year stops being free

Backend **254 → 357 passing**, 46 frontend. Two questions answered: what the chart is
really claiming when three bars disagree, and what the model assumes by taking one filed
year as the starting point.

**The chart refuses to draw what does not apply.** The DCF bar is gated on
`sector_weights.dcf_applies` — the same rule the scorer uses — so a REIT gets a struck-out
row with the reason instead of a confident number the Models tab suppresses one tab away.
`peer_ev_revenue` is suppressed when target and peer operating margins differ by more than
2×: on 0700.HK the peer set medians 5.7% operating margin against Tencent's 34.3%, so the
peer median 1.84× revenue multiple implied **189.61** a share against a 439–471 cluster
from every other multiple — one number stretching the comps bar to 2.48× wide, and the sole
reason its verdict still read "in range".
Analyst targets became context rather than a vote, with their dispersion carried as a
separate uncertainty signal.

**The growth clamp is gone.** `[0%, 25%]` was two economic judgements dressed as data
hygiene. The floor grew shrinking companies at zero and inflated XOM 15.7%; the ceiling
truncated a 42.6% consensus from 55 analysts. Replaced by a validity range of −50% to
+200% that *rejects* rather than truncates, with the provenance labelled either way. The
explicit stage went 5 years to **1**, matching the one-year horizon of the consensus that
feeds it — holding a one-year figure flat for five invented four years nobody forecast, and
for AMD that compounded free cash flow 15.1× before any fade began.

**The base year turned out to be the largest undeclared assumption.** Free cash flow enters
linearly, so a base year 22% below normal is a valuation 22% below normal, permanently.
Three of four profitable fixtures start below their own mean FCF margin (AAPL 0.90×, MSFT
0.78×, XOM 0.71×; 0700.HK 1.06×). `base_year_context` decomposes the year *exactly* —
`FCF/revenue = CFO/revenue − capex/revenue`, no residual — so the panel can separate a
business spending more (MSFT: capex 13.3% → 34.9% of revenue while operating cash rose)
from one earning less, with nothing assumed. The reported year stays the headline; the
normalised figure sits beside it and the platform declines to choose.

The direction is the whole argument, and a test pins it: normalisation moves 0700.HK
**down** while moving MSFT and XOM up. A change that narrowed every gap would be a price
tracker, not a model.

**Analyst opinion is now counted once.** `analyst_upside` divided someone's forecast of
price by price while every other valuation metric divided a reported figure or the
platform's own model; the DCF already consumes analyst consensus growth, so scoring the
target too moved two of five V metrics from one source with correlated errors of the same
sign. Removed from every pillar, kept on screen as labelled context. Composite moved −3 to
+1; no fixture changed tier.

**A grade that never varied was replaced by arithmetic.** Conviction read LOW on all eleven
names tested and the overlap zone was non-empty once, so the chart now leads with a bridge
decomposing model-value → price into named steps ending in an explicitly unexplained
residual. The residual is left unexplained on purpose: it is the market pricing a longer
advantage period, a lower discount rate or a higher terminal cash conversion than a
ten-year fade at 2.5% can express, and closing it by tuning would make the DCF an expensive
way to display the price.

**Terminal growth shows its derivation** against two ceilings (nominal GDP, and the
risk-free rate per Damodaran), both displayed whether or not they bind. The cap applies
only to the platform default — a caller who names a rate gets it, because the
reconciliation back-solves past both ceilings deliberately.

**Also fixed, found reviewing the above:** white-on-accent measured **3.68:1** against a
4.5:1 requirement on the primary button, active nav tab, period picker, segment controls
and chat bubbles — all 13-14px body text, and the hover state was *more* readable than the
resting state. Filled surfaces moved to a darker blue already in the palette (4.80:1). 71
user-visible strings had em-dash and en-dash punctuation restructured into periods, colons
and commas; the `—` no-data glyph in tables was deliberately kept, because a hyphen there
reads as a minus sign in a column of financial figures.

**Four defects in this work were caught by reviewing it afterwards** and are recorded
because the review, not the tests, found them: the panel quoted a ratio against one
baseline and its two legs against another, so the numbers on screen would not reconcile;
the driver sentence claimed "spending more, not earning less" for XOM where *both* legs
moved adversely; a first fix for that contradicted itself on 0700.HK; and rounding was
compounded across periods instead of applied once at the output.

### ✅ 2026-08-10 (b) — the two decisions the review left open

**RIVN 74/A violated §5.2; now 60/B.** Two causes fixed together.

`cash_runway_q` divided cash by *operating* burn and ignored capex — for a company
building factories, the wrong denominator. RIVN 2025: operating outflow 0.78bn against
1.71bn of capex, so runway read **27.3 quarters** (past the anchor's top rung at 20,
scoring 100) where the free-cash-flow burn gives **8.5 quarters and 63**. Overstated 3.2×.
The *trigger* deliberately stays operating-outflow-negative rather than moving to
free-cash-flow-negative: **capex is discretionary in a way that operating burn is not**, so
a company whose operations fund themselves can stop building and has no runway problem to
measure. Trigger and rate answer different questions, and a test pins it — the mutation
widening the trigger initially survived the whole suite.

The profile also weighted the pillar these companies fail at **15%** and the one they ace
at **35%**. For a pre-profit company "can this become profitable" *is* the quality
question. Rebalanced to **Q 0.25 / G 0.25**.

Measured: RIVN **74 → 60**, tier **A → B**, health 82 → 63, and every mega-cap now sits
above the cash-burner. Only RIVN moved; the other six goldens are byte-identical, because
`cash_runway_q` appears in one profile and the weights touch only that profile. The three
`xfail(strict=True)` markers came off — they reported XPASS the moment the fix landed,
which is what that mechanism is for. Mutation-tested: reverting either half fails only the
tests that own it.

Not resolved by this, and moved to Now: the anchors are still unvalidated, and
`score_history`'s pre-profit series is now **discontinuous at this date**.

**The Portfolio tab made the comparison the Screener refuses to make.** `ScreenerTab`
warns that composites from different profiles are not one measurement — citing "a bank's
70 and a pre-profit growth company's 74", which were the live JPM and RIVN values —
while `PortfolioTab` rendered those same numbers in one column with no classification and
no caveat. `store.latest_scores` already returned `classification`; the endpoint dropped
it. Each score now shows its profile, and the table carries the Screener's caveat **in the
Screener's own wording**. Not grouped: weights, P&L and concentration are portfolio-level
figures needing one list, and the portfolio lists holdings rather than ranking them.

### ✅ 2026-08-10 — three-lens review: finance, engineering, UI

Full review of the platform against every fixture by running the code, not reading it.
Seven defects fixed, two recorded as open (above), all six behavioural fixes
mutation-tested. Backend **153 → 246 passing** (+3 xfail), frontend **22 → 44**.

**A company's statements and its shares can be in different currencies.** 0700.HK reports
in CNY and trades in HKD — verified against Tencent's published FY2024 revenue of
RMB 660,257m, which the fixture matches exactly. The DCF built enterprise value from
statement cash flows, bridged with `totalDebt`/`totalCash` (which follow the statements),
then compared the per-share result against an HKD price. The split inside yfinance's
`info` was **measured, not assumed** — 9988.HK's `totalDebt` and `totalCash` match its own
quarterly balance sheet at 1.0000 and 0.9998, while 0700.HK's `bookValue` and `trailingEps`
sit 1.13× their statement equivalents against a CNYHKD spot of 1.1627. `financialCurrency`
was not in the `info` whitelist, so the app could not previously *detect* the mismatch at
all. Fixed at seven boundaries: the DCF equity bridge, the WACC capital-structure weights,
`resolve_beta`'s peer D/E, `fcf_yield`, `ffo_yield`, `comps.ev_implied` and Altman Z's
`equity_liabilities` term. `fx_rate` returns **None** rather than a fallback constant when
it cannot be fetched — a stale risk-free rate moves a valuation a little, a wrong FX rate
rescales all of it — and callers withhold the comparison instead. Measured: 0700.HK upside
**+30.5% → +44.5%** at the pinned test rate, composite 74 → 75.

**A dividend cut to zero improved the valuation pillar.** yfinance omits `dividendYield`
for a non-payer rather than sending 0, and `None` means *unreported* to `piecewise_score` —
so the metric left the pillar average instead of scoring its 20-point floor, raising the
average it left behind. Measured on JPM, changing nothing else: 1.68% → valuation 58,
0.10% → 51, **zero → 60**. A suspended dividend came out ahead of a token one. Now scored
as zero with `dividend_yield_assumed_zero` raised only where the profile actually uses the
metric. Latent on the fixtures (both payers), so six direct tests pin it.

**A cost basis of `0` took down the Portfolio tab unrecoverably.** `unrealized_pnl` and
`unrealized_pnl_pct` do not share a null condition — zero cost is a real gain and an
undefined return — and the renderer read the second off the first's guard. The `TypeError`
landed inside the component's own render, so `ErrorBoundary` unmounted the tab *including
the add/edit form*, leaving no route back from the UI. Reachable by typing `0` in a field
whose sibling placeholder suggests `0`. The arithmetic moved out of the endpoint into
`main.position_values` so the contract could be tested at all; that it was inline is why
the shape shipped unchecked.

**Two ratios paired figures from different fiscal years.** `_credit_spread` and
`ratio_analysis`'s interest coverage each called `_latest` twice, independently, and
`_latest` walks back until it finds anything: AAPL resolved EBIT at 2025-09-30 and Interest
Expense at **2023-09-30**, so the 33.8× on screen was two different businesses. Now pinned
to the newest period reporting both, with the period returned and displayed — the same
discipline `_statement_fcf` already enforced. Reads 29.06× for 2023; both score 100, so no
composite moved and the goldens could not have caught it.

**The DuPont ROE cap fired on banks.** JPM's equity multiplier is 12.2 because
deposit-funded intermediation is what a bank *is*, and the guard cut its ROE 78.4 → 70
while flagging `dupont_leverage_cap_applied` — which reads as an accusation of financial
engineering. The bank profile already measures capital adequacy through `equity_assets`.
Exempted via `sector_weights.LEVERAGE_IS_STRUCTURAL`; JPM composite 70 → **71**, quality
75 → 79. AAPL (multiplier 4.9, ROE 149%) is still capped, correctly. REITs deliberately
are not exempt — a REIT lifting ROE with debt is a real concern, not a regulatory floor.

**A missing debt figure read as a debt-free company.** `(totalDebt or 0)` moved AAPL's
fair value 143.99 → 147.41 with nothing on screen to say why, while `ratio_analysis`
returned `None` for the same input. The DCF still computes — refusing to value a company
over one absent field is worse — but names the leg it assumed, and the audit row shows it.

**A DCF was displayed for company types it does not fit.** O returned a complete −63.0%
upside off a base cash flow treating a REIT's property acquisitions as maintenance capex.
The scoring engine already knew, dropping `dcf_upside_pct` from the REIT and bank profiles;
the card now exports `dcf_applicable` and the Financial Models tab says so.

**Two modules doing unaudited maths had no tests.** `comps.py` (football-field IQR, every
peer-implied share value) and `indicators.js` (Wilder RSI, MACD) — 20 and 24 tests added.
Both were correct: RSI reproduces Wilder's own worked dataset. Mutation testing found two
gaps in the new tests themselves — a period-2 RSI case cannot distinguish Wilder smoothing
from a plain mean (the recurrence collapses), and nothing pinned the EMA's SMA seed until a
slope-1 ramp assertion was added, where MACD's first point is exactly 7.0.

Every behavioural fix was mutation-tested: reintroducing each defect fails only the tests
that own it. Golden diff is two tickers — 0700.HK (currency) and JPM (DuPont scope) — with
the other five byte-identical.

**Also found, not fixed** (see Now, plus §A4 in the review): the EV→equity bridge omits
minority interest, preferred stock and associates — worth +4.5% on 0700.HK at book, and
JPM carries $20.0bn of preferred that is ignored entirely. Splitting "subtract MI and
preferred" (standard) from "add associates at cost" (cost is not value) needs a decision.
Accessibility is a separate pass: 2 aria attributes and 0 roles across the app, with 22
`title` tooltips carrying information that has no other route, and `PillarBar` is a
clickable `<div>` so the metric breakdown cannot be opened without a mouse. The palette
itself measures clean — every text token passes WCAG AA on both surfaces.

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

### ⚪ Fibonacci retracement, and candlestick pattern detection

Tested 2026-08-17 (f) on ten names, five years of daily OHLCV, 12,461 bars. A permutation
test asked whether the Fibonacci level set catches more retracement terminations than a
random level set of the same size: **p = 0.415 / 0.326 / 0.226** at ZigZag thresholds of
5% / 8% / 10%. Not significant anywhere, and the test was built to favour Fibonacci — the
random levels were drawn from a range including a near-empty region the Fibonacci ratios
avoid. Terminations are near-flat from 0.4 to 1.0.

The decisive argument is internal rather than statistical: **the drawn horizontal levels
already shipping are the honest version of this.** They report how many bars actually
touched a line, so a reader who believes in 61.8% can draw it and be told. Auto-drawn
levels would replace that measurement with an assertion.

Candlestick patterns fail for a different reason: they are defined by relationships
*within* a bar, and a bar here is 1m to 1wk depending on the period dropdown, so the
detected set would change with no change in the company. There is no trading-day
expression of "a hammer" the way there is of "a 50-day average".

### ⚪ Stochastic oscillator

Measured 2026-08-17 (f) against the RSI(14) already shipping, on true intraday high/low.
Level correlation **0.845** — but the containment is what settles it: `%K<20` holds
**93.9%** of every `RSI<30` event while firing **9.0× as often** (AAPL 236 against 29;
NVDA 198 against 11). Not a second opinion; the same opinion with roughly eight extra
false alarms each time.

It also has a defect RSI does not. Its denominator is the window's min and max, the least
robust order statistics available, so **%K moves when price has not** — purely because the
bar that set an extremum rolled out of the lookback. An indicator that changes state in the
absence of an event is a poor fit for a platform that withholds numbers it cannot justify.

### ⚪ VWAP

Session VWAP is well-defined on 2 of the 9 periods this app offers (1d, 5d) and undefined
on 2 more (5y, max — a bar is a day or a week, so there is no session to anchor to). On the
1h intervals a US session is seven bars whose last is only 30 minutes long while carrying
the closing auction, which makes the average **systematically close-biased** — a number
that would look plausible and be wrong.

Anchored VWAP is computable on daily bars but its selling point is false: it is read as the
average cost basis of everyone who bought since the anchor, which assumes every share
traded is still held. A six-month anchor accumulates volume equal to roughly half of a
mega-cap's shares outstanding, and several multiples of a high-turnover name's. The anchor
is also a free parameter with no selection rule, chosen after the outcome is visible.

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

### ⚪ ~~`comps.ev_implied` still uses the one-term bridge~~ — not a defect, closed 2026-08-18

*Raised 2026-08-14 (d) as a defect. It is not one, and the fix this entry proposed would
have introduced a real error. Kept rather than deleted so the reasoning is not lost and the
"fix" is not re-attempted — which is exactly what nearly happened on 2026-08-18.*

**What the entry said.** `comps.ev_implied` bridges peer-multiple implied values with
`EV − net_debt` alone while the DCF bar beside it subtracts minority interest and preferred
and adds marked securities, so the two bars on the football field rest on different bases.
That observation is **true**. Measured across the seven fixtures, the difference is 13.9% of
price on 0700.HK, 2.1% on JPM, 1.7% on AAPL and ≤1.1% on the rest.

**Why the proposed fix was wrong — on the term that dominates.** The multiples on both
sides are the vendor's `enterpriseToEbitda` / `enterpriseToRevenue`, and the vendor does not
deduct non-operating assets from enterprise value. AAPL carries **77.7bn** of
`Investmentin Financial Assets` while its reported `enterpriseValue` sits **127k** from
`market cap + total debt − total cash` — five orders of magnitude apart. So adding
`marked_securities` to the peer bridge **double-counts**: a peer's market cap already prices
its own non-operating assets, that value is inside the median multiple, and adding the
target's again counts it twice. On 0700.HK that term alone is **+77.65 per share on a 481
price, 16.1%**.

**Corrected 2026-08-18, hours after this entry was first written.** The original version of
this entry made the same class of mistake it was closing, and both errors reached the
shipped code:

- It claimed Yahoo's EV is **exactly** `market cap + debt − cash`. That holds to the cent on
  AAPL and MSFT and **fails by 4.3% on JPM and 2.3% on O**.
- Its proof was **a null test**. AAPL and MSFT are precisely the two fixtures whose balance
  sheets carry zero minority interest and zero preferred — the only two where "net debt
  only" and "net debt plus those terms" are the same arithmetic. They cannot distinguish the
  two hypotheses. Worse, `(EV − net debt) / shares` reduces to `market cap / shares`, which
  *is* the price by construction, so "reproduces the traded price to the cent" measured
  nothing at all.
- Evidence points the other way on those terms: **JPM's 21.04bn residual is within 5% of its
  20.05bn of preferred stock**, and accounting for minority interest and preferred cuts JPM's
  error from 4.28% to 0.20% and RIVN's from 0.093% to −0.031%. It does not fit XOM or O, so
  the exact vendor formula is **not recoverable from seven fixtures**.
- It quoted **+67.03** as the marked-securities effect. 67.03 is the *net* of all four bridge
  terms; marked securities alone is **77.65**, and minority interest pulls it back to 67.03.

So: net debt only remains correct, because the term that dominates is settled and the terms
that are not settled have no better answer. What is retracted is the claim that *every* term
was proven.

The DCF bar may use the fuller bridge because its enterprise value comes from discounted
FCFF, which contains only operating cash flows. **The two bars rest on two different
definitions of enterprise value, and both are right for their own method.**

**What shipped instead** (2026-08-18): the reasoning is now a docstring on
`comps.ev_implied`, a regression test asserts that a balance sheet carrying all four bridge
terms changes the implied value by nothing, and the football field discloses the basis
difference on screen — but only when a DCF bar was actually drawn, since a bank or a REIT
has no second bar to compare against.

**No trigger.** This is settled. The only thing that would reopen it is a peer data source
carrying full balance sheets, which would allow recomputing *peer* EVs on the fuller bridge
so that both sides moved together. `get_peer_snapshot` fetches `info` only; full statements
per peer would be roughly four times the request weight for a cosmetic gain, and the
disclosure is the honest answer at a fraction of the cost.

### ⚪ HTTP-layer (TestClient) tests

Starlette's `TestClient` needs `httpx`, which is still not installed, and the OpenBB
install already demonstrated that adding packages to this venv can shift
`fastapi`/`uvicorn` versions. The endpoints are thin wrappers over tested functions; they
were smoke-tested live instead. Revisit if the endpoint layer grows real logic.

*(2026-08-09: `fastapi` is now an explicit test requirement, but only because `main` is
imported for two constants — it does not bring `httpx`, so the conclusion is unchanged.)*

### ⚪ A shared `useResource(path, deps)` hook

*Migrated here 2026-08-18 from a local architecture audit, which is being retired. Recorded
because the reasoning is measured and would otherwise be lost — the file was never tracked.*

Proposed as *"~25 lines, deletes duplicated loading/error scaffolding from six components."*
**Measured: there are 12 resource-load sites across 8 files, and a naive `useResource(path, deps)`
covers 1 of 12 unchanged** — and even that one needs the caller to deliberately ignore the
returned `error`. `ScreenerTab.jsx` has zero `useEffect` at all; its only call is a `post` with
a body inside a click handler.

*Counting rule, stated because it is not obvious: **12/8 counts resource-load operations**,
which is what such a hook would target — App ×2, ModelsTab ×2, PortfolioTab, PriceChart,
**ScorecardTab ×3**, ScreenerTab, SearchBar, TrackerTab; a `Promise.all` block counts once, and
`ChatBox`/`Debate` are stream-only and excluded. Counting every literal
`get`/`post`/`patch`/`del`/`stream` call instead gives **28 across 10 files**.*

*(The retired audit said 11/8, and a 2026-08-18 pass repeated it after "verifying" the total
without re-deriving the per-file breakdown. `ScorecardTab.jsx` has **three** load sites, not
two: `:592` inside `loadComps`, the `Promise.all` at `:607-608`, and `:613`
`get(.../history).then(setHistory).catch(...)`. The omitted one is precisely the three-line
`get(...).then(setX).catch(...)` shape this entry's own verdict calls "the genuinely shared
part" — so the strongest case **for** a hook was the site left out of the census against it.
The conclusion is unaffected: 1 of 12 is worse than 1 of 11.)*

**The divergences are the feature, not the duplication:**

- `ModelsTab.jsx:831-834` deliberately swallows its error — *"the quality bars are an
  enhancement — a failure here must not blank the tab."* A hook that surfaced `error` would
  blank the entire valuation tab because a score bar failed.
- `SearchBar.jsx:38-51` — a 220 ms debounce **plus** a sequence-number race guard, because
  *"a slow lookup for 'app' must not overwrite the newer one for 'apple'."* A naive hook fires
  per keystroke with no ordering guarantee.
- `PortfolioTab.jsx:60` gates on `if (loading && !data)` to keep stale rows visible during a
  refetch instead of flashing a loader; its error renders as a banner *above* the table.
- `TrackerTab.jsx:31-55` — three URLs behind one loading flag and one fatal error. Three hook
  calls would let the chart render with bars but no event markers: a behaviour change.
- [ScorecardTab.jsx:616](frontend/src/components/ScorecardTab.jsx#L616) — the comps URL is
  derived from a *prior* response (`loadComps(peerSuggest.suggested.join(','))`), so it cannot
  be expressed as `deps` at all.
- `ModelsTab.jsx:824-827` and
  [ScorecardTab.jsx:611](frontend/src/components/ScorecardTab.jsx#L611) seed **controlled form
  inputs** from the response (`setPeerInput(peerSuggest.suggested.join(', '))`);
  `PriceChart.jsx:237` seeds state then mutates it locally on drag/append/delete. Read-only
  `data` is incompatible with both.

Only 2 of 12 sites have any cancellation today — `PriceChart.jsx`'s `let live` guard and
`SearchBar.jsx`'s sequence number — so universal cancellation would itself be a behaviour
change. The genuinely shared part is the three-line `get(...).then(setX).catch(...)`
shape; everything a hook would have to absorb is commented-in intent. **This is duplication
that is carrying information.** No reopening condition.

### ⚪ `Protocol` for the provider + `TypedDict` for the fundamentals dict

*Migrated here 2026-08-18, same origin as the entry above.*

Proposed as *"converts the vendor-swap contract from tribal knowledge into a CI failure."*
**It cannot: there is no type checker.** CI runs `pip install`, `ruff check backend/`, `pytest`.
There is no `[tool.ruff]` section, so ruff runs its default pycodestyle + Pyflakes set — AST
lint, no type inference. Repo-wide search for `mypy|pyright|pytype|pyre`: zero real hits.

Demonstrated rather than assumed: ruff at the pinned version passes a file containing a
`TypedDict`-annotated literal missing a required key, a subscript of an undeclared key, and a
`str` where `float | None` was declared — `All checks passed!`, exit 0. And `TypedDict` is not
runtime-enforced: a dict missing a required key assigns without error, `Info(bogusKey=5)`
constructs, and `isinstance(d, Info)` raises `TypeError`.

**The `Protocol` would document zero drift.** `YFinanceProvider` has exactly six public methods,
cross-checked against every real `provider.<method>` call site — **defined set == called set**,
zero unused, zero undefined, all six already carrying return annotations.

Non-`Optional` fields would also overfit: of the **51** keys in the fixtures, **13** are null in
at least one, and the other 38 are non-null only because the sample is seven large caps.
**11 of the 13 are attributable to RIVN (pre-profit) and JPM (bank)**; the remaining two,
`exchangeDataDelayedBy` and `regularMarketTime`, are null in **all seven** — they were added
that way by the fixture-conformance fix.

*(The source audit said "49 keys, 11 null … RIVN and JPM account for all 11", which was exactly
right when written and went stale hours later: commit `7f0a64b` took `info` from 49 to 51 keys.
Re-counted 2026-08-18. The RIVN/JPM attribution still holds for 11 of 13 — stating it as "all
13" would have been true as set-coverage and misleading as explanation, since the two new nulls
have nothing to do with being pre-profit or a bank.)*

The load-bearing 10% was the fixture-conformance assertion, which needs no types at all and
**shipped separately** as `test_fixtures.py` on 2026-08-18.

**Reopening condition:** a decision to add mypy or pyright to CI. That is a separate,
non-trivial call — an untyped FastAPI + pandas + yfinance backend will produce a large
first-run baseline — not a free rider on this change.

### ⚪ Parameterising `risk_free_rate` and `fx_rate`

*Migrated here 2026-08-18, same origin as the two entries above.*

Proposed as *"4 call sites; makes the domain layer genuinely pure; removes two autouse fixtures
and `yfinance` from CI."* **Wrong on cost and wrong on benefit.**

- **Cost understated.** `risk_free_rate` is indeed one production call site
  (the single `rf = risk_free_rate(RISK_FREE_RATE)` inside `_wacc`, cited by symbol because a
  line number here has already drifted twice — `:503` → `:515` → `:523` — each time from an edit
  to the comment block sitting directly above it), but `statement_to_market_fx`
  has **6 production call sites across 4 modules** — `financial_models.py` ×3 (`:276`, `:302`,
  `:423`), plus `comps.py:376`, `forensics.py:108`, `scoring.py:129` — so threading a rate
  lookup is still a viral parameter through a chain of signatures rather than a local change.

  *(The source audit said "7 call sites across 4 modules, `financial_models` ×5". Re-counted
  2026-08-18: wrong, and self-contradictory as written — 5+1+1+1 is 8, not 7. It was already
  wrong at `8c5d467`, so this is a miscount rather than drift. **The direction is unchanged and
  the conclusion is unaffected**: 6 sites across 4 modules is still viral, just less so than
  claimed. Recorded rather than quietly corrected, because a cost argument that was inflated is
  worth knowing about.)*
- **"Removes yfinance from CI" is false.** [data_provider.py:21](backend/data_provider.py#L21)
  imports `yfinance` at module scope, and [comps.py:24](backend/comps.py#L24) imports the
  `provider` singleton. Any test importing `main` or `comps` pulls it regardless.
- **The impurity is already contained.** Both functions are day-cached in module globals, fail
  soft (`risk_free_rate` returns its fallback *uncached*; `fx_rate` returns `None` and callers
  suppress the comparison), and are documented at length.

The direction-of-dependency criticism — domain reaching into infrastructure — remains true on
principle. Its entire practical cost is two `autouse` fixtures in `conftest.py`. The
`statements.py` extraction reduced the argument further: the impure imports are now isolated in
small modules where they read honestly.

**Reopening condition:** a second data provider being added.

*The migrated text also offered "or the FX pin ever producing a test that is wrong rather than
merely artificial". Dropped 2026-08-18: that is reconsidering the item on its own merits, which
the criterion at the top of this file explicitly excludes — and the entry that added the
criterion carried the violation in the same commit. A test going wrong is a reason to fix the
test, not a trigger to re-litigate a decision.*

### ⚪ Restructuring the backend layout, or thinning the comments

*Migrated here 2026-08-18 with the three entries above. Recorded because these are the two
things a well-meaning refactor is most likely to undo, and neither is written down anywhere
else.*

**The backend DAG is not accidental.** Zero import cycles, and it really is four layers —
re-derived 2026-08-18 by parsing every module's AST for `backend.*` imports:

| layer | modules | depends on |
|---|---|---|
| 0 — leaves | `ai_client`, `data_provider`, `drawings`, `market_series`, `search`, `sector_weights`, `statements`, `store` | nothing in the project (**8 of 13**) |
| 1 | `financial_models` | leaves only |
| 2 | `comps`, `forensics`, `scoring` | `financial_models` + leaves |
| 3 | `main` | everything |

Do not add a DI container and do not add layers — the structure that makes a vendor swap
bounded is the six-method provider interface, not the directory count.

*(Two corrections in two passes, both worth recording. The retired audit said "five of twelve":
twelve was right at `8c5d467` and became thirteen when `statements.py` landed, but "five" was
never right — 7 of 12 then, 8 of 13 now. The first fix then over-corrected, claiming every
non-leaf "depends on `data_provider` or on a leaf", which is **false**: `forensics` and
`scoring` depend on `financial_models`, and neither imports `data_provider` at all. The layer
table above is what the AST actually says, which also vindicates the audit's original "four
clean layers" — the one part of that sentence that had been right.)*

**The comment density is an audit trail, not documentation.** It carries measured values, often
dated — `financial_models.py:109` records *"yfinance returned 0.173 for XOM"*, `:623-624` records
*"XOM regresses at 0.2888 and is used at 0.30"*, and `:799-800` carries *"moved fair value
143.99 → 147.41"* with its date. That is what lets this list say *"declined again, this time on
measurement rather than principle"* instead of re-arguing a decision from scratch. A refactor
that normalises it to conventional docstrings would delete the least reproducible asset in the
repo and leave the code looking tidier. **Preserve it through every refactor above.**

*(A 2026-08-18 draft of this paragraph illustrated the point with a quote —* "XOM's vendor
0.173, its measured 0.2888" *— that is not a code comment at all. It is a line from **this
file**, and the two figures live in two separate comments that never appear together. Quoting
the list to itself as evidence for the code is exactly the failure the paragraph warns about.)*
