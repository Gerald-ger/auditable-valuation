# Data sources review — 2026-08-14

What this platform's numbers are actually made of: which are fetched, which are invented,
and which gaps no free source can close. Written because the platform's stated goal is to
"only make assumption when necessary", and an assumption made because nobody wired up a
source is the least necessary kind.

Companion to `quant-review-2026-08-06.md` (model correctness) and
`valuation-triangulation-review.md` (how the methods are combined). This one is about the
inputs underneath both.

**Provenance: † marks a live measurement (convention added 2026-08-18).** A document about where
numbers come from should say where *its own* numbers come from. Most figures here are
reproducible from a checkout — run the suite, read a fixture, count the call sites. Some are
not: they needed a network call, a vendor credential, or both, and no artefact of them survives
in the repo. Those carry a **†** and a date.

This is a **reproducibility** marker, not a confidence one. A live measurement is often the
better evidence — the FMP and screener results below settled questions no amount of reading
could. But a `†` figure can go stale without anything here failing, and vendor peer lists
demonstrably do: FMP's UPS peers changed between 2026-08-14 and 2026-08-18 †, with
`backend/tests/test_comps.py:714-715` still recording the earlier list and the later one written
down nowhere in the repo — the marker illustrating itself. Where a `†` claim becomes
load-bearing, this repo's own answer is to capture a fixture — which is what the HKD-reporting
case got on 2026-08-19, as `0002_HK`.

---

## 1. What the platform actually depends on

Five external systems. Not five data sources — **one data source and four narrow helpers.**

| System | What it feeds | Auth | Fallback when it fails |
|---|---|---|---|
| **yfinance** (Yahoo, unofficial) | quotes, price history, news, company statements, peer snapshots, FX, ticker search | none | propagates to a `502`; FX returns `None` and callers suppress |
| OpenBB → `federal_reserve` | US 10Y treasury yield → CAPM | none | `RISK_FREE_RATE = 0.043`, uncached so it self-heals |
| OpenBB → `sec` | SEC filing markers, the 10,398-symbol search index | none | `[]` / stale disk cache |
| OpenBB → `fmp` | peer discovery where no curated list exists | key | `[]`, curated map is consulted first |
| **ChinaBond** (CCDC), direct HTTP *(added 2026-08-19)* | China 10Y government yield → CAPM for CNY-reporting issuers | none | degrades to the US 10Y labelled `usd_proxy`, uncached |
| Ollama (local) | commentary only — never a number | none | features disable with a note |

**ChinaBond is fetched at runtime and never vendored, and that is a licensing choice.** CCDC
asserts *"版权所有 未经允许 请勿转载"* — the restriction is on redistribution, not access — so
committing the curve into this public repo is the act the notice addresses and calling the
endpoint is not. That inverts the pattern used for Damodaran's premiums next door, which are
vendored precisely because Damodaran *publishes* a dated annual snapshot; the CGB curve is
published daily, and a snapshot taken 2023-08-21 would be **85bp wrong** by 2026-08.

It is the same licence class as yfinance — see §3, whose conclusion covers both: acceptable
while the platform is personal, resolve before it is hosted.

The swap point is deliberate and documented: `YFinanceProvider` exposes six methods
(`get_quote`, `get_history`, `get_news`, `get_peer_snapshot`, `get_filings`,
`get_fundamentals`) and `provider = ...` on the last line of `data_provider.py`. Any
replacement implements those six and nothing else in the app changes.

**Everything that decides a valuation comes from yfinance.** The statements the DCF
discounts, the shares it divides by, the debt in its bridge, the peers behind its comps and
its beta, and the price it compares against — one source, unaudited, with no cross-check.

---

## 2. The single-source finding

This is not a hypothetical. The codebase already documents three separate occasions where
that single source was wrong, each found by measurement and each worked around in code:

- **Betas are broken sector-wide for energy.** `financial_models.py:97-101`: XOM's peers
  return CVX 0.488, COP 0.123, SHEL −0.218, BP −0.212. Only one survives the credibility
  band and it is still implausible, so XOM falls through to a neutral 1.0.
- **`info["freeCashflow"]` is annual for some issuers and a single quarter for others** —
  MSFT at 0.24× the statement figure, GOOGL 0.31×. It silently rescaled `fcf_yield`, made
  `fcf_conversion` compare a quarter of cash against a year of earnings, and could have
  misrouted a company's entire scoring profile. Documented four times, in
  `financial_models.py:504-506`, `scoring.py:102-105`, `sector_weights.py:196-204`.
- **Rows disappear mid-history.** `financial_models.py:143-157`: yfinance stopped reporting
  AAPL's interest expense after 2023, so interest coverage on screen was FY2025 operating
  income over FY2023 interest — a ratio of two different businesses.

The pattern is the point. Each was caught by someone measuring a specific number and finding
it odd. **There is no systematic cross-validation**, so the ones nobody has measured yet are
still there. `quant-review-2026-08-06.md:144` ranked exactly this as an open risk:
*"單一來源，無交叉驗證 … beta 已證實錯誤，其他欄位未經檢驗"* — one source, no
cross-validation; beta proven wrong, the other fields untested.

---

## 3. The licence position

**yfinance is documented personal-use-only**, and Yahoo's terms prohibit automated access and
redistribution. yfinance is not affiliated with or endorsed by Yahoo; it is a scraper of
Yahoo's internal endpoints.

- **Running locally, for yourself: fine.** This is the ordinary use and the risk is low.
- **Shared, hosted, or public: this is a blocker**, not a bug. Redistributing scraped Yahoo
  data through a web app is the case the terms are aimed at, and yfinance is currently
  load-bearing for essentially every number the app shows.

**Decision taken 2026-08-14: record it, do not act on it yet.** No free source covers Hong
Kong fundamentals, so removing yfinance today would cost the coverage the platform is meant
to have. The honest sequence is: keep it while the platform is personal, and resolve this
*before* it is hosted — not after.

Two things follow from that. Any future hosting decision has a data-licensing prerequisite,
not just a deployment one. And the six-method provider interface above is what makes the
eventual swap a bounded job rather than a rewrite — it is worth keeping clean.

---

## 4. Where the gaps are, and whether free data closes them

| Gap | Data actually needed | Free source? |
|---|---|---|
| ERP flat 5% for every market | per-market equity risk premium | ✅ **done 2026-08-14** — Damodaran, vendored |
| HK/CNY discounted at the US 10Y | per-currency sovereign yield | ✅ **CNY done 2026-08-19** — ChinaBond's CGB 10Y, keyless, net of the vendored default spread. ⚠️ **HKD still open**: HKMA has not answered on three attempts across six days, and it was never able to serve the CNY case anyway. See §7 *(this row pointed at §6 until 2026-08-18 — §6 is the beta/momentum section; the risk-free gating has always been §7)* |
| Interest income not netted from FCFF | cash interest *received*, per period | ✅ likely — SEC XBRL `CompanyFacts` (US only) |
| AAPL/MSFT get no FCFF add-back | interest paid, every period | ✅ likely — same source |
| Interest coverage mixing FY2025 and FY2023 | statements with explicit period labels | ✅ same source |
| Cyclical valued off one year | 10y+ statement history | ✅ same source (US); ❌ HK |
| No score history / no backfill | point-in-time, as-first-reported fundamentals | ❌ **not free** |
| Anchor curves never validated | forward returns incl. delisted names | ❌ **not free** |
| No sector percentile scoring | bulk universe / constituents endpoint | ❌ **not free** |
| Tencent's investment portfolio ignored | holdings-level positions with marks | ❌ **not free** |
| EV→equity bridge omits MI and preferred | market values, not book | ❌ **not free** |
| HK has ~10 event markers vs AAPL's 209 | HKEX filings feed | ⚠️ HKEXnews is public but needs its own scraper — same fragility and licence class as yfinance |
| HK news | HK-native news source | ❌ **no option covers HK** |
| Peer sets weak outside 23 curated names | business-mix classification data | ✅ **free — refuted 2026-08-18**, this row used to read "not free". `info['sector']`/`info['industry']` are already in the `INFO_KEYS` whitelist and populated on all 7 fixtures incl. HK, and yfinance's screener filters on them **without a key**. Raw output and the five obstacles it carries are in §5 |
| Beta neutral-defaulted for energy | 2–5y weekly returns | ✅ **no new source needed** — see §6 |
| HK momentum vs the S&P 500 | home-market benchmark | ✅ **no new source needed** — see §6 |

### What was closed on 2026-08-14

`EQUITY_RISK_PREMIUM = 0.05` — one number for every market and every year, with no source and
no date — is replaced by Damodaran's published country table, vendored as a dated snapshot at
`backend/market_risk_premiums.json` and keyed on the currency the discounted cash flows are
denominated in.

| Market | was | now | effect on fair value |
|---|---|---|---|
| United States | 5.00% | **4.46%** | AAPL +9.2%, MSFT +9.8%, XOM +9.2% |
| Hong Kong | 5.00% | **5.01%** | ~nil |
| China (0700.HK reports CNY) | 5.00% | **5.14%** | 0700.HK **−1.8%** |

It moves US valuations up and Tencent's down. That two-directional result is what makes it a
correction rather than tuning — the direction was not chosen, and a test pins it so a future
snapshot update cannot quietly make it one-way.

Two details worth keeping straight. Damodaran's country figure is **additive** — total =
mature market + country risk premium — so consuming the total *and* adding the CRP would
count the country twice; only the total is used, and a test asserts the snapshot's own
arithmetic. And the key is `financialCurrency`, not `currency`: `tax_rate_for` keys on the
trading currency because tax follows the filing jurisdiction, but a discount rate has to
match the money it discounts. 0700.HK trades HKD and reports CNY, so it is priced off China.

---

## 5. What free tiers cannot fix — stated plainly

Measured against this platform's actual needs, not in general:

- **FMP's free plan blocks the fundamentals endpoints for everyone, and the block is not
  geographic.** This section previously read *"FMP's free plan is US-only"*. That was asserted
  rather than measured, and it is wrong twice over. `equity.compare.peers` is a *free-tier*
  endpoint and **does cover HK** — `README.md:447` records it, and it was re-measured † on
  2026-08-18: `1177.HK → 2269.HK, 1801.HK, 1093.HK, 3759.HK`, `0700.HK → 9888.HK, 1024.HK,
  1698.HK, 2518.HK`. What the free plan actually refuses is
  `fundamental.income/balance/cash`, which return `402 Restricted Endpoint` — a
  **plan-entitlement refusal, not a coverage one**. The only measured "US-only" in this repo
  attaches to FMP **Starter** (paid) for **news** (`README.md:455`) — a different plan and a
  different endpoint.

  **Stated as inference, not measurement, because that distinction is this bullet's whole
  point.** The `402` was observed on a US symbol. No FMP fundamentals call against a `.HK`
  symbol is recorded anywhere in this repo, so "the block is not geographic" is read off the
  error *class* — `402` is what a vendor returns for an unsubscribed endpoint, where a coverage
  gap returns empty data — and not off a measurement. It would be a poor correction that
  replaced an unmeasured assertion with a differently-unmeasured one and did not say so.
- **Finnhub's free tier is US-only** for anything beyond basic quotes; its 60+ exchange
  coverage is a paid feature. † Re-checked 2026-08-18 against Finnhub's published pricing and
  rate-limit documentation — this repo holds no Finnhub credential, so nothing here has ever
  called their API, and this is the weakest-provenance claim in the section.
- **What `README.md` actually measured** on 2026-08-02, by raw HTTP against both vendors with
  valid free keys: `fundamental.income/balance/cash` return `402`, news endpoints return
  `403`/`402`, *"Neither covers HK news at all."* Stated precisely because this section used to
  cite it as corroborating a *geographic* restriction, which it never tested — a `402` is a
  **plan-entitlement refusal, not a coverage one**, and no FMP fundamentals call against a
  `.HK` symbol is recorded anywhere in this repo.

So: **there is no free, redistribution-clean, Hong-Kong-covering fundamentals API.** Any plan
that assumes one exists is wrong. The realistic options are (a) stay personal-use and keep
yfinance, (b) pay for HK coverage, or (c) let HK degrade to price-and-quote only. The
platform is currently on (a) by decision, not by accident.

Free *does* cover, cleanly and with redistribution rights:

- **SEC EDGAR** (`data.sec.gov`) — filings, XBRL `CompanyFacts`, the symbol index. US
  government work, public domain, no key, 10 requests/second with a User-Agent. This is the
  strongest unused source available and it is US-only.
- **Damodaran's datasets** — ERP, country risk, tax rates, industry betas. Free, semi-annual.
  Now partly used.
- **HKMA** — free, official, no key, and disseminated through DATA.GOV.HK for re-use
  **commercial and non-commercial alike** †. The only clean HK-specific source found, and the
  only clean licence in this whole section. *Marked because it is an external licence assertion
  read off HKMA's and DATA.GOV.HK's published terms — in a section about licensing, that is the
  claim least excusable to leave looking like a measurement.*

  **Two corrections, 2026-08-18 †.** This entry used to say *"Exchange Fund Bills & Notes yields
  including a 10-year"*. There is no 10-year there: the EFBN yield series runs **7-day to
  2-year only**, because HKMA ceased issuing Exchange Fund Notes of three years and above in
  **2015**. Longer tenors moved to the **Government Bond Programme**, which is a different
  endpoint — `gov-bond/instit-bond-price-yield-daily?segment=Benchmark`. *All three facts are
  read off HKMA's published API documentation, not off a response — the endpoint has never
  answered from here. The same claim is marked † in `TODOLIST.md`; it was left unmarked here
  until 2026-08-18, so the identical fact carried two different provenance labels in two files.*

  **And it is still unreachable, twice †.** Two single observations from one machine on one
  network; neither distinguishes a broken endpoint from a filtered route. `502` on 2026-08-14; on 2026-08-18 the API path
  returned `http_code=000` after 25 s while `api.hkma.gov.hk/` itself answered `404` in 1.2 s
  and `data.gov.hk/` answered `302` in 0.8 s. The host resolves and completes TLS; the API path
  does not respond. Two failures **four days apart** — thinner than a long run of failures, but
  enough that **reachability is a prerequisite to be discharged before any work is scoped
  against this**, not a footnote.

  **And what it could settle here is smaller than it looks †.** HKMA publishes **HKD**, so it
  cannot address 0700.HK, which reports CNY (see the ⚠️ in §4). The natural reply is that it
  still serves HKD-*reporting* issuers — but measured 2026-08-18 off `financialCurrency`, **none
  of the six HK names in `PEER_SUGGESTIONS` reports in HKD**: `0700.HK`, `9988.HK`, `3690.HK`
  and `0941.HK` report CNY, and `0005.HK` and `1299.HK` report **USD**. An earlier draft of this
  section named 0005.HK and 0941.HK as the HKD case; both were wrong.

  **The curated six are not representative, though.** Across a sample of HK large caps the split
  is **30 CNY / 14 HKD / 4 USD** †, and the HKD segment is the HK-domestic names — `0001` CK
  Hutchison, `0002` CLP, `0066` MTR, `0388` HKEX, `0823` Link REIT, `2388` BOC Hong Kong and
  eight more. So an HKD rate serves a real and coherent slice of what a Hong Kong user would
  actually look up; it just serves none of what this list happens to curate.

  *Counts, not percentages, because they have to reconcile: 49 tickers were queried and **48
  resolved** — `0011.HK` returned `404 Quote not found`. A draft quoted "61% / 29% / 8%", which
  sums to 98% and leaves the 49th unexplained.* † Both figures were live `info` reads with no
  HKD-reporting fixture to check them against. **Captured 2026-08-19**: `0002.HK` (CLP Holdings)
  is now in the fixture set, HKD-reporting and DCF-eligible. The obvious candidates were not
  usable — `classify` sends `0016.HK` to `real_estate_reit` and `2388.HK` to `financials_bank`,
  and `dcf_applies` is `False` for both.
- **FRED** — US macro series with history, free with a key.

### Peer classification is free, and it is not a new licence

Kept separate from the list above on purpose, because it does **not** carry redistribution
rights — it rides the yfinance dependency the platform already has. That is the point: it adds
capability without adding a licence class.

`info['sector']` and `info['industry']` are already inside the 51-key `INFO_KEYS` whitelist and
populated on all seven fixtures, HK included (`0700.HK → Communication Services / Internet
Content & Information`). yfinance exposes a screener that filters on exactly those fields,
**with no API key**, and returns market caps so the result can be ranked by size.

`docs/financial-models-reference.md:922` had already listed `obb.equity.screener(...)` with
yfinance in the free-provider column and *"peer building"* as the use case — so this was
documented, never measured, and never carried into a peer-discovery decision. `README.md:464`
warns that table's free-provider column *"predates the measurements above"*. It has now been
measured (2026-08-18):

**† Live, 2026-08-18** — both columns needed a network call and the FMP column a credential.
Neither is reproducible from a checkout, and vendor peer lists drift.

| target | yfinance screener, keyless — **raw**, market-cap ranked † | FMP, with key † |
|---|---|---|
| O | *O*, SPG, URMCY, UNBLF, STGPF, KIM, SPG-PJ | SPG, KIM, REG, FRT |
| **RIVN** | **TSLA, TOYOF, TM, BYDDY, BYDDF, GM, RACE** | HMC, MGA, GPC, **BBY** |
| 0700.HK | *0700.HK*, 9888.HK, 1024.HK, 1698.HK, 9626.HK | 9888.HK, 1024.HK, 1698.HK, 2518.HK |
| 1177.HK | 1276.HK, 3692.HK, 2196.HK, 2096.HK, 3320.HK | 2269.HK, 1801.HK, 1093.HK, 3759.HK |

Raw rather than cleaned, because the cleaning is the work. Italics mark the target appearing in
its own results; `SPG-PJ` is a preferred at marketCap 0; `TOYOF`/`TM` and `BYDDY`/`BYDDF` are
ADR-and-ordinary pairs of one company each.

Equivalent on O and 0700.HK, worse on 1177.HK, and decisively better on RIVN — where FMP
returned a consumer-electronics retailer for a pre-profit EV maker.

**Five obstacles, all found by running it rather than predicting them.** Two are checkable
offline against the pinned yfinance — the accepted `industry` and `region` spellings are literal
dicts in `yfinance/const.py`, so the first and last reproduce with the network unplugged. The
middle three are † live, describing what a screen actually returned on 2026-08-18: the screener's industry
labels use an em-dash (`REIT—Retail`) where `info['industry']` uses a hyphen (`REIT - Retail`),
which raises `Invalid EQ value` and needs a mapping rather than a character replace; the target
appears in its own results (`O`, `0700.HK` — but not `RIVN` or `1177.HK`, so it fires on half
the sample); share classes, ADRs and cross-listings duplicate, so one company votes twice or
three times in a median — `URMCY` and `UNBLF` are both Unibail-Rodamco-Westfield, and `SPG-PJ`
is a Simon preferred sitting beside `SPG` itself, giving seven rows for five companies on the
`O` screen; foreign names arrive mixed in and are not all duplicates (`STGPF` is Scentre Group,
an Australian retail REIT), which is a judgement an implementation must make rather than
inherit; and the
region has to be derived from the ticker suffix, inheriting `home_index()`'s known limit that a
US-listed Chinese ADR still reads `us`.

### Built 2026-08-19 — and three things this section got wrong

`comps._screener_peers` ships the tier described above, ordered **below** FMP so it can only
fill a gap rather than change an existing answer. Measured across 18 non-curated names in both
regions †: peers for **18 of 18**, a full four for 16. The two short sets are thin industries
rather than failures — `0388.HK` (HKEX) has one HK peer, `0823.HK` (Link REIT) two.

Three corrections to what is written above, all forced by implementing it:

1. **"needs a mapping rather than a character replace"** overstated the evidence. The mapping is
   the right implementation, but measured 2026-08-19 a plain replace round-trips **all 145**
   industries and no screener label carries a spaced hyphen of its own. The derived lookup earns
   its place for a different reason: an unknown industry misses it and yields no peers, where a
   replace emits a rejected spelling indistinguishable from an empty screen.
2. **`SPG-PJ` is `marketCap: None`, not `marketCap 0`.** A truthiness test covers both; the
   equality test this section implied would have passed it straight through.
3. **The obstacle list was one short, and the missing one was the expensive one.** OTC arrives
   under **four** exchange codes. A filter written against `PNK` alone passed `WMMVF` (OTCID)
   and `WMMVY` (OTCQX) — one company, Walmart de México — as two of Costco's four peers.
   Measured over 36 screens — 18 industries x 2 regions, 1,162 rows †: PNK 412, OQX 23, OID 9,
   OQB 3. All four share the `fullExchangeName` prefix `"OTC Markets "` and nothing else, and
   that field was present on every one of the 1,162 rows, so the filter matches the name.

That third one also **collapsed obstacles 3 and 4 into one rule**: dropping OTC listings removes
every cross-listed duplicate *and* the genuinely foreign `STGPF`, because "a peer should trade
where the target trades" answers both.

**The ordering is left open on purpose.** The screener beat FMP on every name where the two
disagreed and a human can judge — RIVN, SBUX, ABNB, CAT, LMT † — and they agreed exactly on one
of 18 (`O`). That is suggestive, not a measurement, and reversing the order would change the
answer for key-holders. It stays below FMP until a scored peer-quality metric exists.

---

## 6. Two fixes that need no new source at all

Both inputs were already being fetched. **Both were built on 2026-08-14** — this section is
kept because what it got wrong is more useful than what it got right.

**Beta computed from price history — done.** `resolve_beta` ingested a vendor beta, checked
it against a credibility band, and fell back to peers and then to 1.0; XOM ended up at that
neutral 1.0. It now regresses five years of weekly returns against the home index, and the
vendor's figure is retained beside it as a cross-check. XOM measures **0.2888**.

That number is the interesting part. This section assumed yfinance's energy betas were
simply *broken*. An independent regression says they were **directionally right**: XOM's
vendor 0.173, its computed 0.2888 and its peers' 0.488 / 0.123 all agree that an oil major's
correlation to the S&P really is very low. What was broken was the credibility band —
`BETA_MIN = 0.3` rejected every one of those readings and substituted a number nobody
measured. The floor now binds on a *measured* value (0.2888 clamped to 0.30), which is a hint
it is calibrated for equities in general rather than for a sector that genuinely decouples.

**Home-market benchmark for momentum — done, but not the way this section proposed.** It
suggested reading `^HSI`'s own `52WeekChange`, which one extra fetch would supply. Measured
live 2026-08-14, that field is unusable: `^GSPC` reports it in **percent** (20.918) while
`^HSI` reports it in **decimal** (0.500), and the Hang Seng value matches neither its own
price history (−1.41%) nor any unit reading of it. Following this section's advice would have
scored 0700.HK at roughly −63.7% relative — worse than the defect it was fixing.

Both legs are therefore computed from weekly closes instead. On the committed bars 0700.HK
is −24.23% against the Hang Seng's −0.43%, a relative **−23.79%**, where the S&P's +20.92%
gave −45.15%. Note the per-stock scalar was no better than the index one: the fixture's
`52WeekChange` for 0700.HK says −13.74% where its own closes say −24.23%.

*(An earlier revision of this file quoted −13.6% / +18.3% / −31.9% for that comparison. Those
were live figures from an earlier date, copied from `TODOLIST.md` without re-measuring — the
same mistake this document warns about elsewhere. The figures above are computed from the
committed fixtures and are reproducible.)*

---

## 7. The one thing deliberately left undone

Per-market **risk-free rates** — the other half of the cost-of-capital pair, and the half
that would fix 0700.HK discounting CNY cash flows at a US rate. Not done, and not because it
is hard:

- China's 10Y is ~1.70% against the US 4.30%. The **applicable** move is **−320bp**, not the
  −260bp this bullet used to record: the CNY risk-free is the 10Y *net of* the CNY default
  spread, `1.70% − 0.60% = 1.10%`, so it is 1.10% against 4.30%. See
  [currency-consistent-discounting.md §3](currency-consistent-discounting.md), which already
  said so — *"that is −320bp against the current 4.30%, not the −260bp TODOLIST recorded"* —
  and which this section's 2026-08-18 rewrite adopted three corrections from while leaving this
  fourth one behind.
- China's country risk premium is ~0.91pp, so **it does not offset the rate cut.** The hope
  recorded in `TODOLIST.md` that the two legs would cancel does not survive the numbers.

**Three claims in this section were superseded, and are corrected here rather than deleted
(2026-08-18).** It said the fix would take 0700.HK **624.90 → 1,225.93, "roughly doubling"**;
that discounting CNY flows at a CNY rate and converting at **spot** was *"not obviously right"*
because interest-rate parity implies a forward premium; and therefore that the work *"waits
until spot-versus-forward is settled in writing with a worked example."*

1. **The sizing is wrong twice over.** The baseline moved, and it is not a doubling. Measured
   with the growth cap moving too, and **re-measured 2026-08-19 with `market_bars`** — which is
   what every `main.py` endpoint passes (§4 of
   [currency-consistent-discounting.md](currency-consistent-discounting.md)):

   | risk-free | fair value | vs baseline | vs the 481.40 price | move |
   |---|---|---|---|---|
   | 4.30% — US 10Y, today | **469.48** | — | **−2.5%** | — |
   | 1.70% — China 10Y raw | 601.62 | **+28.1%** | +25.0% | −260bp |
   | 1.10% — 10Y − CNY default spread | **611.62** | **+30.3%** | +27.1% | −320bp |

   **Both rows, because they are not interchangeable.** `+28.1%` is the −260bp row; the
   applicable move is −320bp, whose row is `+30.3%`. Netting the default spread is worth only
   the ~2% between them, so the contestable half of the change is also the cheap half.

   *This table read 680.99 / 1,024.98 / 1,043.30 and `+50.5%` / `+53.2%` until 2026-08-19.
   Those reproduce exactly, but only **without** `market_bars` — on the vendor's reported beta
   of 0.745 rather than the 1.3192 this fixture has regressed to since 2026-08-14. They were
   never what the app produced. The earlier note that a 2026-08-18 draft mismatched `+50.5%`
   with `−320bp` still stands; both numbers were simply from the wrong beta.*
2. **The spot-versus-forward worry was inverted.** Discounting in the cash-flow currency and
   translating the *result* at spot is algebraically identical to translating each cash flow at
   its forward rate and discounting at the target-currency rate — the interest differential
   enters exactly once. Applying a forward rate *on top of* a local-currency discount rate
   would count it twice. **Spot is correct, and it is already the shape the code uses.**
3. **The stated gate has been discharged.** "Settled in writing with a worked example" is
   [currency-consistent-discounting.md](currency-consistent-discounting.md), written 2026-08-17.

**So what still keeps this open is not FX.** It is the **terminal-growth ceiling**: adopting a
1.1–1.7% CNY risk-free rate does not only change a discount rate, it asserts through the cap
that Tencent's cash flows grow at 1.1–1.7% in perpetuity — a macro forecast arriving through
the back door, with the terminal share rising 62.96% → 73.4% as it does. That is a different
and narrower objection than the one this section originally recorded, and it is the live one.

**And the data half is blocked too.** HKMA publishes HKD, not CNY, so it cannot serve this case
whatever its uptime — and its endpoint has now failed from this machine twice (§5).
