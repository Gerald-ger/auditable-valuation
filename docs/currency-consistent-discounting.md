# Currency-consistent discounting — 2026-08-17

**Status: analysis only. No code was changed.**

`_wacc()` applies the US 10-year treasury yield to every issuer. For 0700.HK, whose statements
are in CNY, that discounts CNY cash flows at a rate built in USD. TODOLIST recorded this as open
and set an explicit trigger before anything could be done about it:

> Trigger: the spot-versus-forward question settled in writing, with a worked 0700.HK example.

This document is that. It answers the spot-versus-forward question, reports what a
currency-consistent rate actually does to the valuation when measured rather than estimated, and
ends at a second question that the measurement exposed and that has to be answered before any
code changes.

---

## 1. What the code does today

Inside one function, four inputs sit on three different bases
([financial_models.py:628-682](../backend/financial_models.py#L628-L682)):

| Input | Keyed on | Currency |
|---|---|---|
| Risk-free rate | `financialCurrency` since 2026-08-19 — but every currency still resolves to the US 10-year, now labelled `usd_proxy` | **USD, always** |
| Equity risk premium | `financialCurrency` | reporting currency |
| Tax rate | `currency` | trading currency |
| Capital-structure weights | `totalDebt × fx` against `marketCap` | trading currency |

The ERP leg was made country-aware on 2026-08-14. The risk-free leg was not, and the in-code
comment says why: the HKD peg makes the US 10Y an acceptable proxy for an HKD-reporting issuer.
That argument is sound as far as it goes — and it does not reach 0700.HK, which reports in CNY.
CNY is not pegged.

## 2. Spot or forward — settled

TODOLIST worried that converting at spot is wrong because interest-rate parity gives a low-rate
currency a forward premium. **That concern is inverted.** Spot is correct here, and using a
forward rate in this construction would double-count the interest differential.

There are two internally consistent ways to value a foreign-currency business, and they are
algebraically identical.

**Method A — discount in the cash-flow currency, translate the result at spot.**

$$PV_{HKD} = S \times \sum_{t} \frac{CF_t^{CNY}}{(1+r_{CNY})^t}$$

**Method B — translate each cash flow at its forward rate, discount at the target-currency rate.**
Covered interest parity fixes the forward as $F_t = S \times \left(\frac{1+r_{HKD}}{1+r_{CNY}}\right)^t$, so

$$PV_{HKD} = \sum_t \frac{CF_t^{CNY} \times F_t}{(1+r_{HKD})^t}
= \sum_t \frac{CF_t^{CNY} \times S \times \left(\frac{1+r_{HKD}}{1+r_{CNY}}\right)^t}{(1+r_{HKD})^t}
= S \times \sum_t \frac{CF_t^{CNY}}{(1+r_{CNY})^t}$$

The two are the same expression. The interest differential enters **once** — through the discount
rate in Method A, through the forward curve in Method B. Applying a forward rate on top of a
local-currency discount rate would apply it twice.

The platform already uses Method A: everything in the projection is reporting-currency, and `conv`
is applied at the output boundary only ([financial_models.py:841-851](../backend/financial_models.py#L841-L851)).
**Method A with spot is the right shape. The defect is not the conversion — it is that the
discount rate is not in the cash-flow currency.**

Caveat worth stating: the equality holds under covered interest parity, which is a no-arbitrage
condition on traded forwards, not a forecast. It does not require anyone to predict the exchange
rate. It does assume the cash-flow projections and the discount rate share an inflation frame —
see §6.

## 3. The sovereign default-risk double count

A local government bond yield is not a risk-free rate. China's 10-year yield contains China's own
default risk, and Damodaran's country risk premium — already vendored in
[market_risk_premiums.json](../backend/market_risk_premiums.json) as `CNY.country_risk_premium =
0.0091` — is derived from the same sovereign default spread, carried there as
`CNY.default_spread = 0.0060`.

Take the local yield as risk-free *and* keep the country-inclusive ERP, and that spread is priced
twice: once inside the bond yield, once inside the premium. The standard correction is to subtract
it:

```
CNY risk-free = China 10Y − CNY default spread
              = 1.70%       − 0.60%
              = 1.10%
```

That is −320bp against the current 4.30%, not the −260bp TODOLIST recorded. The JSON already
carries the number, currently marked "for audit, NOT to be added to anything" — this would be its
first use in arithmetic, and the note would have to change with it.

## 4. What it actually does, measured

Run on the committed `0700_HK` fixture with `fx_rate` pinned at the suite's `CNY→HKD = 1.10`, so
the figures are reproducible from a checkout. Only the risk-free rate varies; everything else is
the model as it stands.

**Re-measured 2026-08-19, and the earlier table was not measuring the app.** Both blocks below
are reproducible from a checkout; they differ only in whether `market_bars` is passed. Every
endpoint in `main.py` passes them, so **the first block is what the platform actually produces**
and the second is what this document used to report.

### With `market_bars` — β 1.3192, regressed. **This is the app.**

| Risk-free | WACC | Terminal growth | Fair value / share | vs the 481.40 price |
|---|---|---|---|---|
| **4.30%** (US 10Y, today) | 10.43% | 2.50% | **469.48** | **−2.5%** |
| **1.70%** (China 10Y, raw) | 7.87% | 1.70% | **601.62** | +25.0% |
| **1.10%** (China 10Y − spread) | 7.28% | 1.10% | **611.62** | +27.0% |

**The effect is +30.3%** (469.48 → 611.62), not the +53.2% recorded until today.

### Without `market_bars` — β 0.745, the vendor's reported figure

| Risk-free | WACC | Cost of equity | Terminal growth | Source | **WACC − g** | Fair value / share | Upside |
|---|---|---|---|---|---|---|---|
| **4.30%** (US 10Y, today) | 7.75% | 8.13% | 2.50% | `platform_default` | **5.25%** | **680.99** | +41.5% |
| **1.70%** (China 10Y, raw) | 5.19% | 5.53% | 1.70% | `capped_at_risk_free_rate` | **3.49%** | **1,024.98** | +112.9% |
| **1.10%** (China 10Y − spread) | 4.60% | 4.93% | 1.10% | `capped_at_risk_free_rate` | **3.50%** | **1,043.30** | +116.7% |

Shared inputs: ERP 5.14% (Damodaran, China), equity weight 90.67%, fixture price 481.4 HKD.

**How this went wrong, since the mechanism matters more than the numbers.** The table was correct
when written and labelled its own β as "reported". Beta became a *regression* on 2026-08-14, which
more than doubled it for this fixture; the table was never re-run, and `financial_models.py`
copied its three figures into a comment describing current behaviour. A labelled assumption in one
document became an unlabelled claim in another.

The correction also flips the headline: at 469.48 against a 481.40 price the model now says
Tencent is **fairly valued**, where the old table said +41.5% undervalued. That strengthens the
direction-blindness argument in §7 rather than weakening it — see there.

One older correction still stands:

- **The baseline had already moved once.** TODOLIST recorded 624.90 against a then-current 680.99,
  because of the base-year and ERP work. TODOLIST's "624.90 → 1,225.93" (+96%, "roughly doubles")
  came from moving the WACC alone, which is not what the code does.

## 5. Why the second leg cancels most of the first

`terminal_growth = min(TERMINAL_GROWTH, rf)`
([financial_models.py:775-779](../backend/financial_models.py#L775-L779)) — perpetual growth is
capped at the risk-free rate. Lower the rate and the cap binds, so **both** ends of the terminal
spread fall together:

```
WACC − g  with rf = 4.30% :  7.75% − 2.50% = 5.25%
WACC − g  with rf = 1.70% :  5.19% − 1.70% = 3.49%
WACC − g  with rf = 1.10% :  4.60% − 1.10% = 3.50%
```

Once the cap binds, the terminal spread is **almost invariant to the risk-free rate**, and that is
structural rather than coincidental. Writing $WACC \approx w_e(rf + \beta \cdot ERP) + w_d \cdot r_d(1-t)$
and $g = rf$, the $rf$ terms very nearly cancel in $WACC - g$, leaving the risk premia. A perpetuity
is $\frac{1}{WACC-g}$, so the terminal block barely notices the difference between 1.70% and 1.10%.

**This inverts the priority of the two questions.** The difficult, contestable choice — whether to
subtract the default spread, and which spread — moves fair value by **1.8%** (1,024.98 → 1,043.30).
The straightforward, well-supported choice — use a CNY rate at all rather than a USD one — is worth
**+50%**. Effort belongs on the second.

It also means the change is less dangerous than the headline suggests: the model does not amplify
an error in the sourced rate, because the cap absorbs most of it.

## 6. The problem this exposes, and why nothing should be implemented yet

The cap is `g ≤ rf`. It rests on the proposition that a riskless rate is a market read of long-run
nominal growth, so nothing can outgrow it forever. That holds when the two are in the same currency
**and** the bond market is pricing growth rather than something else.

For CNY today it is not obviously true. A 1.70% ten-year yield does not represent a belief that
Chinese nominal GDP will grow 1.70% in perpetuity; it reflects the current policy and deflation
picture. Adopting a CNY risk-free rate therefore does not merely change a discount rate — **it
silently asserts that Tencent's cash flows grow at 1.1–1.7% in CNY forever**, which is a macro
forecast, arriving through the back door, in exactly the way this platform exists to avoid.

The terminal-value share moves with it: **62.96% → 73.4%** of enterprise value sits in the terminal
year after the change. More of the answer rests on the assumption that just became questionable.

So the honest position is that the currency mismatch is real and the fix is well-founded, but it
cannot be shipped as a one-line rate swap. It requires deciding, and writing down, what the
terminal-growth ceiling means in a currency whose nominal rate has decoupled from its nominal
growth. Candidates, none yet chosen:

1. Keep `g ≤ rf` and accept the implication.
2. Cap on long-run nominal GDP growth for the cash-flow currency instead of the riskless rate,
   which would mean sourcing that number per market (`NOMINAL_GDP_GROWTH = 0.04` is currently one
   constant for the US and Hong Kong both, and is diagnostic-only).
3. Cap on the higher of the two, with the reason shown on screen.

Option 2 is the most defensible and the most work: it adds a sourced assumption per market. Under
the platform's own rule — *only make an assumption when necessary* — it has to be argued as
necessary rather than assumed to be better.

## 7. The four-part test

Applied to "use a CNY risk-free rate for a CNY-reporting issuer"
(see `valuation-platform-principle`):

| | Verdict |
|---|---|
| **1. Direction blindness** — would you do it if it moved fair value *away* from price? | **Pass, and more decisively after the 2026-08-19 re-measurement.** Fixture price 481.40. The model currently says **469.48 — within 2.5% of the price**, i.e. it agrees with the market. The change pushes it to **611.62 (+27.0%)**, breaking that agreement. A change that takes the model *from* agreeing with the quote *to* disagreeing by a quarter cannot be reverse-engineering the quote. (This row previously argued the same point from 680.99 → 1,024.98, figures measured without `market_bars`; see §4.) |
| **2. Independent justification** | **Pass.** Discount rate and cash flow in the same currency is a consistency requirement, not a preference, and is standard in every international-valuation text. |
| **3. No output-chosen parameters** | **Pass.** The rate is a published sovereign yield; the spread subtraction comes from the same table already vendored. Neither is picked by looking at the answer. |
| **4. Cross-sectional** | **Pass.** It touches non-USD-reporting issuers only. Of the eight fixtures, exactly one — `0700_HK` — is affected; `0002_HK` reports HKD and the other six USD. It cannot be a price tracker because it does not move most names at all. |

The change passes all four. **The blocker is §6, not the test.**

## 8. What implementing it would cost

Recorded now so the estimate does not have to be rebuilt later.

- `risk_free_rate()` took `(fallback)` and cached one rate in a module global keyed only by
  date. **Half-discharged 2026-08-19:** it now takes `(fallback, currency)` and returns
  `(rate, source)`, the fetch having moved to `data_provider._us_treasury_10y`. The per-currency
  cache was deliberately *not* added — with one source, currency keys would store duplicates of
  a single value — so what remains is a source per market, which is the blocked part below.

  **Source availability, corrected 2026-08-18.** This bullet used to end *"China's 10-year is
  widely published; HKMA publishes Exchange Fund yields free (unverified from this machine —
  502 on 2026-08-14)"*, which reads as though one sentence covered both markets. It does not.
  HKMA publishes **HKD**, so it is silent on the CNY rate this whole document is about. And its
  Exchange Fund Bills & Notes series stops at **2 years** — issuance at three years and above
  ceased in 2015, with longer tenors moving to the Government Bond Programme endpoint
  (`gov-bond/instit-bond-price-yield-daily?segment=Benchmark`). The endpoint has now failed
  twice from this machine: `502` on 2026-08-14, and `http_code=000` after 25 s on 2026-08-18
  while the host itself answered `404` in 1.2 s. **Treat reachability as a prerequisite to
  discharge, not a caveat to carry.**

  *Provenance: every HKMA figure in this bullet is a **live** claim — the tenor range and the
  2015 cessation are read off HKMA's published API documentation, and the two failures are
  single observations from one machine on one network. None is reproducible from a checkout,
  and neither failure distinguishes a broken endpoint from a filtered route. See the `†`
  convention at the top of [data-sources-review.md](data-sources-review.md).*
- ~~**`conftest.py`'s `pinned_risk_free_rate` is `autouse`** and returns one constant for every
  call. If the rate becomes currency-aware, that fixture has to become currency-aware too, or
  **the new path is never exercised by the suite** while every test still passes.~~
  **Discharged 2026-08-19, though not the way this predicted.** Making the *fixture*
  currency-aware would have meant pinning a different rate per currency — a fiction, since
  every currency genuinely resolves to the same US 10-year. The fixture instead moved down a
  level to patch `data_provider._us_treasury_10y`, the network fetch, leaving the currency
  branch itself unstubbed and executed by **150 of the 482** tests — the ones that reach
  `_wacc`, measured by instrumenting the branch, against **0** had the outer function been
  stubbed. The warning was right about the hazard and wrong about the remedy.
- `golden_scores.json` moves for `0700_HK`: `dcf_upside_pct` feeds the valuation pillar.
- [test_valuation.py:355](../backend/tests/test_valuation.py#L355) pins AAPL's fair value at
  ≈146.49. AAPL reports USD and must not move — that test becomes the regression guard proving the
  change touches only non-USD issuers.
- The in-code comment at [financial_models.py:636-641](../backend/financial_models.py#L636-L641)
  and the TODOLIST entry both describe the current state and would need rewriting.

## 9. Where this leaves the item

The recorded trigger — spot versus forward, in writing, with a worked example — **is now
discharged**: spot is correct, and Method A is already the shape the code uses.

The item does not close. It moves from *"blocked on an unexamined FX assumption"* to
*"blocked on what the terminal-growth ceiling means in a low-nominal-rate currency"*, with the
measurements above available to whoever picks it up. That is a narrower and better-posed question
than the one it started with, and the numbers say the prize is +50% on one fixture's fair value,
not the +96% previously recorded.
