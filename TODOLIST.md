# TODO

Open work, ranked. Open items record the **trigger** (when it becomes worth doing) so
nothing gets done too early — and the deferred items record *why*, so the decision does
not get re-litigated. Entries under *Deliberately not doing* carry no trigger, which is
deliberate: they are settled rather than waiting, and inventing a reopening condition for
them would suggest otherwise. The one exception is the TestClient item, which names the
change that would reopen it. (Stated as a rule and an exception rather than as a count,
because a count goes stale every time an entry is added — it already had, twice.)

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

**What remains open is the modelling question, unchanged and now isolated.** CAPM
prices only systematic risk, so a genuinely uncorrelated business gets a low
required return however volatile it is on its own terms. Whether that is right for
a commodity cyclical is a known criticism of CAPM, and no better beta fixes it.

**Trigger: a decision to depart from CAPM.** The remaining options are a total-risk
adjustment (Damodaran's own suggestion for exactly this case), a floor keyed on
something other than the band, or accepting CAPM's answer — which is now at least
stated on screen with its precision attached.

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

### 🟡 Associates are still carried at cost, and cost is not value

*Mostly resolved 2026-08-14 (d) — see the Done entry. Both blockers this item recorded turned
out to be measurable rather than intractable.*

**The nesting is an exact identity, so the parent is safe.** On 0700.HK, both reported
periods: `Long Term Equity Investment` 348,712 = `Investmentsin Associatesat Cost` 342,409 +
`Investmentsin Joint Venturesat Cost` 6,303. Read the parent, never sum the children.

**"At cost" applied to only a third of the portfolio.** `Investmentin Financial Assets`
635,426 = `Available For Sale Securities` 428,342 + `Financial Assets at FVTPL` 207,084 —
and both of those are *already carried at fair value*. That 635bn is now in the bridge,
because using it reads a filed mark rather than inventing one. It moves 0700.HK from −11.1%
to **+3.6%** with no assumption entering the headline.

**What is left is the associates leg only** — 348.7bn, +45.06/share on 0700.HK, shown beside
the headline and excluded from it. Cost is neither a market value nor a floor: a long-held
stake is usually worth more than it cost and an impaired one less, and the filing does not
say which.

**Trigger: a holdings-level source with marks**, or a decision to accept carrying cost with
that stated on screen. Note the platform can already show the second answer — the panel
prints it — so what a source would buy is the right to put it in the headline.

### 🟡 `comps.ev_implied` still uses the one-term bridge

Raised 2026-08-14 (d). `comps.py:222` bridges every peer-multiple implied value with
`EV − net_debt` alone, which is what the DCF did until the same day. So the DCF bar on the
football field now subtracts minority interest and adds marked securities while the peer
bars beside it do not — on 0700.HK that is a 71-per-share difference in basis between bars
the chart invites you to compare.

Not fixed in the same change because it moves every peer bar on every company, which is a
different blast radius from one headline, and the football field's verdicts and overlap zone
all read off those bars.

**Trigger: before the next football-field change.** The fix is mechanical — the bridge
figure is already computed in `dcf_valuation`; the work is deciding whether comps should
import it or recompute, and re-measuring every verdict.

### 🟡 Portfolio totals ignore FX

Holdings in USD and HKD are summed at face value. The UI warns when the totals really do
span more than one currency, but the total is wrong, not merely imprecise.
**Trigger: actually holding both.** Needs a rate source; `obb.currency` is free.

*Narrowed 2026-08-17:* the warning used to read the currency of **every** row, so a
watchlist entry — which carries no market value and is therefore in no total — could
raise it on a portfolio that was not mixed at all. It now reads the same set the backend
uses to build `held`. That fixed when the warning fires; the summation it warns about is
still unconverted, which is why this item stays open.

### 🟡 CI proves the tests, not the install

[.github/workflows/ci.yml](.github/workflows/ci.yml) installs `backend/requirements-test.txt`
— six entries — then runs ruff and pytest. It never installs `backend/requirements.txt`, so
the path the README actually tells a stranger to follow (107 pins, including `openbb` and its
30 subpackages) is proven on one Windows 3.14.6 machine and nowhere else. A broken runtime
pin, or a runtime dependency that stops resolving, passes CI green.

Not a suspected break, an unexercised one: `openbb`, `openbb-core` and `openbb-sec` all
declare `requires-python >=3.10,<4`, with `pandas>=3.11` and `numpy>=3.12`, so nothing in the
set excludes 3.14. The README's "CI runs the whole suite on Linux" is true of the tests and
says nothing about the install, which is the part a first-time user hits first.

**Trigger: the first report of an install that fails, or any edit to a runtime pin.** The fix
is a CI job that installs `requirements.txt` and `-e .` and then runs nothing — the install
*is* the assertion. The cost is downloading the full set on every push, which is the reason it
is not already there. First recorded as a warning inside the 2026-08-17 Done entry; promoted
here so it is not lost inside a dated one.

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
  [PriceChart.jsx:344](frontend/src/components/PriceChart.jsx#L344) *disables* the same
  rule on `visibleGroups` deliberately — rebuilding the chart on a marker-filter change
  would discard the user's zoom — and that remains the right call there, because the
  effect sets the state it would have to depend on. (An earlier revision of this list
  called the ScorecardTab warning miscatalogued; the linter did emit it — that claim was
  wrong. The `PriceChart.jsx:398` reference it also carried was wrong: the disable is at
  line 344.)

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

**Trigger discharged 2026-08-17** — the analysis is
[docs/currency-consistent-discounting.md](docs/currency-consistent-discounting.md). Spot is
correct; the worry recorded above was inverted. Discounting in the cash-flow currency and
translating the *result* at spot is algebraically identical to translating each cash flow at
its forward rate and discounting at the target-currency rate, so the interest differential
enters exactly once. Applying a forward rate on top of a local-currency discount rate would
count it twice. Method A is already the shape the code uses.

**Two numbers in this entry are wrong, corrected by measurement.** The baseline is 680.99,
not 624.90 — the base-year and ERP work moved it. And the effect is **+50.5%** (680.99 →
1,024.98), not "roughly double": `terminal_growth = min(TERMINAL_GROWTH, rf)`, so lowering
the rate lowers the growth cap with it, and the recorded figure came from moving the WACC
alone. The terminal spread `WACC − g` is almost invariant once the cap binds (5.25% → 3.49%
→ 3.50% at rf 4.30% / 1.70% / 1.10%), which also makes netting off the sovereign default
spread worth only 1.8% — the contestable half of the change is the cheap half.

**New trigger: what the terminal-growth ceiling means in a low-nominal-rate currency.**
Adopting a 1.1–1.7% CNY risk-free rate does not only change a discount rate — through the
cap it asserts that Tencent's cash flows grow at 1.1–1.7% in perpetuity, which is a macro
forecast arriving through the back door. The terminal share rises 62.96% → 73.4% with it, so
more of the answer rests on the assumption that just became questionable. The analysis lists
three candidate resolutions and picks none. Data is not the blocker: China's ten-year is
widely published and HKMA publishes Exchange Fund yields free (unverified from this machine,
502 on 2026-08-14).

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

**`--reload` was tried first and rejected**, which is recorded in the README because the
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
mentioned it. The omission was deliberate (`comps.py:545`) and completely silent.

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

### ⚪ HTTP-layer (TestClient) tests

Starlette's `TestClient` needs `httpx`, which is still not installed, and the OpenBB
install already demonstrated that adding packages to this venv can shift
`fastapi`/`uvicorn` versions. The endpoints are thin wrappers over tested functions; they
were smoke-tested live instead. Revisit if the endpoint layer grows real logic.

*(2026-08-09: `fastapi` is now an explicit test requirement, but only because `main` is
imported for two constants — it does not bring `httpx`, so the conclusion is unchanged.)*
