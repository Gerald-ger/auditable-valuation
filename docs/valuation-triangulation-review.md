# When the valuation methods disagree — a decision protocol

**Worked on 0700.HK (Tencent), live 2026-08-12.** Every figure here was measured, not
illustrated; each is reproducible from `/api/stock/0700.HK/comps`.

The football field exists to answer one question, and it is not "is the price inside this
bar". The reference doc states the real one (§5.2): *"Never trust one model. Assemble a
football field: each method contributes a value RANGE; the overlap zone is the defensible
fair-value band."* The quant review endorses the chart only as **"the intersection of the
three methods"**.

Until this change the chart computed no intersection. It drew three bars and three
independent verdicts of equal visual weight, which is why a reader could look at Tencent and
see *"PRICE BELOW"* beside *"IN RANGE"* and reasonably conclude the methods mildly disagreed.
They did not mildly disagree. They had no price in common at all.

---

## 1. What the chart showed, and what each bar actually was

| Method | Bar | Verdict | What it actually was |
|---|---|---|---|
| DCF (sens 25th–75th) | 606.74 – 778.12 | PRICE BELOW | IQR over WACC ±100bp and terminal g ±50bp, **growth fixed at 9.38%** |
| Peer multiples | 189.61 – 471.35 | IN RANGE | min/max of **4 point estimates**, one of which could not transfer |
| Analyst targets | 427.48 – 888.49 | IN RANGE | raw sell-side min/max, spec'd at **0% weight** |

Price 461.6. Three problems, in ascending order of importance.

> **Update 2026-08-13.** Measuring the finished chart across eleven tickers turned up two
> things this document originally got wrong, both recorded in §5. In short: the comps
> interquartile core did *not* do the Tencent work (only three multiples survived the
> suppression, so quartiles never engaged), and the DCF's habit of sitting below comps is
> not a defect to be fixed but a finding to be read. §5 carries the evidence.

### 1.1 The comps bar was set by a multiple that does not transfer

The four implied values:

```
peer_ev_revenue    189.61   <- the low
peer_trailing_pe   439.64
peer_ev_ebitda     454.21
peer_forward_pe    471.35   <- the high
```

Three of four cluster in a **1.07× band** straddling the price. The fourth is a 2.3× outlier
that alone stretched the bar to 2.48× wide — and a band that wide contains almost any price,
which is exactly the criticism the DCF bar had already been fixed for.

It is invalid by construction. EV/Sales is a margin assumption wearing a multiple's clothes:

| | Operating margin | EV/Revenue |
|---|---|---|
| Tencent | **34.3%** | 5.575× |
| 9988.HK Alibaba | 1.0% | 2.335× |
| 3690.HK Meituan | −7.5% | 1.355× |
| 9999.HK NetEase | 41.4% | 4.312× |
| 1024.HK Kuaishou | 10.5% | 1.068× |
| **peer median** | **~5.7%** | **1.84×** |

A 1.84× revenue multiple drawn from a ~5.7%-margin peer set cannot be carried onto a
34.3%-margin business. The codebase already gated P/B to balance-sheet sectors for the same
class of reason; EV/Revenue simply never got the same treatment.

**Fixed:** `comps._ev_revenue_transfers` requires the target's margin to sit within 2× of the
peer median, verified rather than assumed, and records the suppression so the absence is
explained rather than silent. Both loss-making is the deliberate exception — EV/Sales is the
conventional multiple precisely where earnings do not exist yet.

Comps now read **439.64 – 471.35, mid 454.25**: fairly valued, which is what the multiples
were saying all along.

### 1.2 The DCF bar hid the assumption it turns on

The sensitivity grid sweeps WACC and terminal growth — the two *second-order* assumptions —
and holds the first-order one fixed. Sweeping growth instead:

```
 0%  -> 399.70  (-13.4%)      9.38% -> 682.40 (+47.8%)   <- the bar
 2%  -> 448.49  ( -2.8%)     15%    -> 932.81 (+102.1%)
 4%  -> 502.96  ( +9.0%)     25%    -> 1597.78 (+246.1%)
```

The bar was narrow for the wrong reason, and its verdict was not robust: the reference doc
requires that be said out loud (§1047 — *"If the conclusion flips on a ±15% change in one
assumption, SAY SO explicitly"*).

**Fixed:** `dcf_valuation` now returns a `growth_sensitivity` band (base ±4pp, clamped to the
same `[0, 25%]` guardrail as the input), and the football field's DCF bar is the union of the
grid IQR and that sweep. Tencent's DCF bar widens **606.74–778.12 → 544.22–853.11**.

The sweep is unioned rather than pooled into the quartiles on purpose: five growth points
against twenty-five grid cells would barely move a quartile, hiding the very driver the band
exists to show.

### 1.3 The DCF and the analyst targets were never independent

```
growth_source     analyst_consensus_fwd
growth_rate_year1 0.0938
fair_value        682.40      analyst mean target  692.84
```

The DCF's dominant input **is** sell-side consensus. That is why its midpoint lands within
1.5% of the analyst mean. The chart read as *two of three methods say cheap*; it was one
sell-side forecast, once discounted and once quoted, against one genuinely independent
method — the comps row that the broken multiple was disfiguring.

**Fixed:** rows carry `independent: false` when the DCF's growth comes from consensus, and
analyst targets are marked `context_only` and excluded from the overlap and the conviction
score entirely. The reference doc gives them 0% weight; a target is a forecast of the price,
not a valuation of the business, and letting it vote lets the thing being tested judge its
own test.

---

## 2. A method that does not apply must not draw a bar

The football field gated the DCF row on `not dcf.get("error")` — *"did the model return a
number"* — which is exactly the test `scoring.py` documents as wrong. A REIT has positive
`CFO − CapEx`, so it never errors, and `O` was drawn a confident DCF bar with a full verdict
while the Financial Models tab, one tab away, suppressed the same number.

**Fixed:** the comps endpoint resolves the classification (statement-verified FCF, same input
as the scorer) and `football_field` refuses the row, naming the reason. Both callers now read
one rule, `sector_weights.dcf_applies`, so the two tabs cannot disagree about one company.

```
O   classification: real_estate_reit   dcf_applicable: False
    DCF                    N/A   A discounted-cash-flow valuation does not apply to a real estate reit.
    Peer multiples (implied)  37.31 – 90.25   envelope 33.73 – 109.51
    overlap: None   conviction: None
```

`conviction: None` with one scored method is deliberate. The intersection of a single range
is that range, and rendering it as an agreement zone would show agreement nobody reached.

---

## 3. The protocol

Run in order. Most reads stop before the end.

**1 — Does the method apply?** A struck-out row is a finding, not missing data. Banks,
insurers and REITs get no DCF; there is no substitute model in this project, and that is
recorded rather than papered over.

**2 — Is each bar built from inputs that transfer?** Check `suppressed_multiples` and the
faint envelope behind each core. A core much narrower than its envelope means the individual
estimates disagree and one of them may be doing all the work.

**3 — Are the methods independent?** A `shared input` tag means two rows are one input. Two
bars that agree because they share a number are one bar.

**4 — Is there an overlap zone?** If yes, that band is the answer and the individual bars are
scaffolding. If **no**, the chart cannot give you a fair value — stop reading it as though it
can.

**5 — When there is no overlap, back-solve the assumptions that separate them.** Averaging
two anchors that disagree by half is false precision and the reference doc forbids it
(§5.2). Name the assumptions instead. There are two, and they answer different questions:

- **What growth reconciles the DCF with the comps?** For Tencent, the DCF compounds at
  **9.38%** taken from analyst consensus and meets the peer core at **2.6%**.
- **What growth does today's price already assume?** For Tencent, **3.33%** — below the ~4%
  an economy grows, so the price needs nothing unusual. For Apple the same figure is
  **7.62%**, above it, which is most of why Apple's two bars are far apart and Tencent's
  are not.

So the question is not which bar to believe. It is:

> **Does Tencent grow free cash flow faster than ~2.6% a year?**

Above it, the DCF's premium to peers is earned and the market is wrong. Below it, today's
price is right and the sell-side is not. That is a question about the business, researchable
with evidence — which is what the chart is for, and what it could not previously produce.

**6 — Decide on that assumption, not on the bars.**

---

## 4. Two corrections, measured 2026-08-13

### 4.1 The interquartile core did not fix Tencent — the suppression did

§1.1 credits two changes for the comps bar narrowing to 439.64–471.35. Only one of them
fired. The core is a quartile band **only when four or more implied values survive**:

```
1 implied value  -> core 100.0-100.0   envelope 100.0-100.0   narrowed=False
3 implied values -> core 100.0-120.0   envelope 100.0-120.0   narrowed=False
4 implied values -> core 102.5-127.5   envelope 100.0-130.0   narrowed=True
```

Suppressing EV/Revenue left Tencent with three, so its core *is* its envelope and no
quartile was taken. The entire improvement came from the margin gate. AAPL, which keeps
four multiples, does get the narrowing.

### 4.2 The DCF sitting below comps is a finding, not a defect

The gap is structural. The implied exit multiple reduces exactly to
`(FCF/EBITDA) × (1+g)/(WACC−g)` — verified against the model's own output to two
significant figures on five fixtures — so with terminal growth pinned at 2.5% for every
company the perpetuity factor is 14–22× for all of them, and the implied exit lands at
5–13× against 10–27× traded.

The tempting reading is that the DCF is biased and needs an exit-multiple terminal to fix
it. Running the check backwards says otherwise. Solving for the terminal growth today's
**own traded multiple** requires:

| | FCF/EBITDA | traded | WACC | implied perpetual g |
|---|---|---|---|---|
| MSFT | 0.34 | 18.9 | 9.59% | **8.04%** |
| AAPL | 0.59 | 27.2 | 9.62% | **7.62%** |
| JNJ | — | — | — | 5.93% |
| XOM | 0.37 | 9.7 | 8.96% | 5.58% |
| 0700.HK | 0.67 | 15.7 | 7.66% | **3.33%** |

To justify Apple's price with a perpetuity you must believe free cash flow compounds at
7.62% **forever** — above the ~4% an economy grows. Tencent needs 3.33%, which is
unremarkable, and Tencent accordingly has the smallest DCF/comps gap in the panel.

So the DCF is not understating these companies. It is reporting that a Gordon perpetuity
cannot express what the market is pricing, and *that* is the information. An exit multiple
anchored to the traded multiple would have deleted it by making the two bars agree by
construction. This is now surfaced as
`diagnostics.market_implied_terminal_growth`, flagged against
`NOMINAL_GDP_GROWTH = 4%` — the check specified at
`financial-models-reference.md` §1.1.4 and previously unimplemented.

### 4.3 The conviction grade does not discriminate

Across eleven tickers: **overlap fired 1/11** (JNJ, 185–204) and **conviction was above LOW
0/11**. A three-band grade with one value in practice is not a grade. It still computes —
"these two methods systematically disagree" is true and worth saying once — but the chart
now leads with the midpoint spread (which ranges 43%–131%) and the two back-solves, and
states that LOW is the normal reading here rather than a warning about the company.

## 5. What this still does not do

- **`conviction` is a spread band, not a probability.** HIGH/MEDIUM/LOW come from the
  reference doc's table (midpoints within 15% / 30% / beyond). No part of it has been
  validated against forward returns, which is the same standing limitation as every anchor
  curve in the scoring engine.
- **The margin tolerance of 2× is a judgement, not a finding.** It catches the 6× gap that
  motivated it and leaves ordinary dispersion alone; it has not been tuned against outcomes.
- **The overlap zone is an intersection, not a weighted band.** The spec also defines
  per-method weights and a weighted fair value (§5.2). Those are not implemented — weights
  would need a view on relative method reliability per company type that this project has not
  earned yet.
- **The back-solve inverts growth only.** WACC and terminal growth could equally be the
  separating assumption; growth is chosen because it is the first-order driver and the one the
  grid never stressed.
- **Peer quality remains the weakest link**, as the quant review's own ranking says. Tencent's
  peer set mixes a food-delivery business and a short-video business with a games-and-social
  one. Suppressing EV/Revenue removes the worst symptom, not the cause.
