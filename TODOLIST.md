# TODO

Open work, ranked. Each item records the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated.

Status: 🔴 open bug · 🟡 improvement · 🔵 decision needed · ⚪ deliberately deferred

---

## Now

### 🔵 The pre-profit calibration is now enforced, but still unvalidated

Resolved 2026-08-10 (b) below: RIVN moved 74/A → 60/B and `tests/test_plausibility.py`
went green. What that did **not** do is make the anchors evidential. §5.2 is a
plausibility expectation someone wrote down in advance; enforcing it substitutes one
judgement for another. The composite still has no forward-return validation, exactly as
`docs/scoring-system-design.md` §5.6 and the README say.

**Also now true:** the `pre_profit_growth` series in `score_history` is **discontinuous at
2026-08-10**. Rows before that date come from the old weights and the old runway formula,
rows after from the new ones, and there is no backfill. Any calibration study must treat
that date as a break for this one profile.

**Trigger: the same ~2 quarters of data as the score-history item below.** When the
calibration query is finally written, it has to exclude or segment pre-profit rows across
that boundary.

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
- **It is not one number.** The sensitivity grid, `growth_sensitivity`, the football-field
  mid and `price_gap_bridge` are all built on the reported base. Swapping the headline
  without rebuilding them puts the mid outside its own bar (hidden by `_clamped_mid`) and
  makes the bridge either double-count its adjustment or show a zero-length step.

What was *not* an argument against it, contrary to the earlier assumption: **scoring.**
`dcf_upside_pct` is anchor-clipped at −40, so XOM's metric moves 0 → 9 of 100 and the
composite stays **70, tier A**. The swap is a display change almost entirely.

The cheap part of the value was taken instead — see the 2026-08-14 Done entry: the DCF
bar now spans both bases, so the chart shows the base-year uncertainty without the
platform choosing a side.

**Trigger: a cyclical whose reported-year headline proves misleading in use**, or margin
history long enough to contain a turn. Options if revisited: normalised headline for
`energy` only, a multi-year consensus average, or the 3-year revenue CAGR.

### 🔵 Beta re-levering has never been audited on a net-cash company

Raised 2026-08-13 and not investigated. `resolve_beta` unlevers peer betas and re-levers
them to the target's capital structure, which is correct in general. AAPL and MSFT carry
more cash than debt, and it has never been checked what the Hamada formula does with a
*negative* net position, nor whether the result is the right input for a company whose
financial risk is essentially nil. CAPM with a historical ERP is a known suspect for
overstating the required return on exactly this kind of business.

**Trigger: before treating the mega-cap DCF gaps as settled.** Cheap to look at; direction
unknown, which is why it is not listed as a defect.

### 🔵 Tencent's investment portfolio is not in the valuation at all

Raised 2026-08-13, sized but not acted on. 0700.HK's balance sheet carries `Investments in
Associates at Cost` 342bn, `Long Term Equity Investment` 349bn and `Investment in Financial
Assets` 635bn against a 4,333bn market cap. A DCF of the operating business plus an equity
bridge misses all of it, so the valuation is incomplete rather than wrong.

Not fixed because the line items **nest** (adding them naively double-counts) and are held
**at cost** rather than fair value. Choosing which line to use and how to mark it are both
assumptions, which is why this is not the "zero-assumption" fix it first appears to be.

**Trigger: a holdings-level source, or a decision to accept book value with that stated.**

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
- ~~Twelve distinct corner radii, with no rule~~ — **done 2026-08-14**, see the Done entry
  below. The 2026-08-13 audit undercounted: it read ten of the declarations as radius
  choices when they were `height / 2` pills written as numbers.
- The footer metadata strip uses two middle dots on one line where the house rule allows
  one. Same category as above: real, cosmetic, unactioned.
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

### 🔵 yfinance is personal-use-only, and it carries the whole app

Raised 2026-08-14 during the data-layer audit. yfinance supplies quotes, history, news,
statements, peer snapshots, FX *and* search — every number that decides a valuation. It is
an unofficial scraper of Yahoo's internal endpoints, documented **personal-use-only**, and
Yahoo's terms prohibit automated access and redistribution.

- Running locally, for yourself: fine, and that is what the platform does today.
- **Shared, hosted or public: this is a blocker**, not a bug. Redistributing scraped Yahoo
  data through a web app is the case those terms target.

**Decided 2026-08-14: record it, keep yfinance.** There is no free, redistribution-clean,
HK-covering fundamentals API — FMP's free plan is US-only, Finnhub's international coverage
is paid, and the README's own 2026-08-02 measurements found the same. Removing yfinance now
would cost exactly the Hong Kong coverage the platform is meant to have.

**Trigger: any decision to host or share this.** That decision has a data-licensing
prerequisite, not just a deployment one, and the realistic answers are pay for HK coverage
or let HK degrade to price-and-quote. The six-method `YFinanceProvider` interface is what
keeps the eventual swap bounded — worth keeping clean. Full reasoning in
`docs/data-sources-review.md` §3.

### 🔵 HK stocks are benchmarked against the S&P 500

`rel_52w_change = 52WeekChange − SandP52WeekChange` treats every ticker as US.
0700.HK (−13.6%) is scored against the S&P (+18.3%) for a −31.9% relative reading.
[docs/scoring-system-design.md:89](docs/scoring-system-design.md#L89) specifies this
formula and flags a sector-ETF-relative upgrade as future work.
**Options:** keep as "relative to global equity", or benchmark HK names to `^HSI`
(costs one extra fetch). Investment judgement, not correctness.

### 🔵 HK stocks still use the USD risk-free rate *(the ERP half was fixed 2026-08-14)*

**The ERP leg is done.** `EQUITY_RISK_PREMIUM = 0.05` is replaced by Damodaran's published
country table, vendored dated at `backend/market_risk_premiums.json` and keyed on
`financialCurrency` — US 4.46%, HK 5.01%, China 5.14%. It moves US fair values **up** ~9%
and 0700.HK **down** 1.8%, so it is two-directional and cannot be read as tuning. See the
2026-08-14 Done entry and `docs/data-sources-review.md` §4.

**The risk-free leg is not**, and after measuring it, that is deliberate rather than
pending. `_wacc()` still applies the US 10Y to every issuer.

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

**Trigger: the spot-versus-forward question settled in writing, with a worked 0700.HK
example.** Not a data problem any more — the HKMA publishes Exchange Fund yields free and
official (unverified from this machine, 502 on 2026-08-14), and China's ten-year is widely
published. It is a modelling question, and doubling a valuation on an unexamined FX
assumption is exactly what this platform exists to avoid.

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
