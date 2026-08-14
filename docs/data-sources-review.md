# Data sources review — 2026-08-14

What this platform's numbers are actually made of: which are fetched, which are invented,
and which gaps no free source can close. Written because the platform's stated goal is to
"only make assumption when necessary", and an assumption made because nobody wired up a
source is the least necessary kind.

Companion to `quant-review-2026-08-06.md` (model correctness) and
`valuation-triangulation-review.md` (how the methods are combined). This one is about the
inputs underneath both.

---

## 1. What the platform actually depends on

Four external systems. Not four data sources — **one data source and three narrow helpers.**

| System | What it feeds | Auth | Fallback when it fails |
|---|---|---|---|
| **yfinance** (Yahoo, unofficial) | quotes, price history, news, company statements, peer snapshots, FX, ticker search | none | propagates to a `502`; FX returns `None` and callers suppress |
| OpenBB → `federal_reserve` | US 10Y treasury yield → CAPM | none | `RISK_FREE_RATE = 0.043`, uncached so it self-heals |
| OpenBB → `sec` | SEC filing markers, the 10,398-symbol search index | none | `[]` / stale disk cache |
| OpenBB → `fmp` | peer discovery where no curated list exists | key | `[]`, curated map is consulted first |
| Ollama (local) | commentary only — never a number | none | features disable with a note |

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
| HK/CNY discounted at the US 10Y | per-currency sovereign yield | ⚠️ HKMA publishes HKD; **gated, see §6** |
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
| Peer sets weak outside 21 curated names | business-mix classification data | ❌ **not free** |
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

- **FMP's free plan is US-only.** International exchanges including SEHK require payment.
- **Finnhub's free tier is US-only** for anything beyond basic quotes; its 60+ exchange
  coverage is a paid feature.
- **`README.md` reached the same conclusion independently** on 2026-08-02 by raw HTTP against
  both vendors with valid free keys: `fundamental.income/balance/cash` return `402`, news
  endpoints return `403`/`402`, *"Neither covers HK news at all."*

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
- **HKMA** — Exchange Fund Bills & Notes yields including a 10-year, free and official. The
  only clean HK-specific source found. *Documented but unverified: the endpoint was
  unreachable from this machine on 2026-08-14 (502), so it must be confirmed live before
  anything depends on it.*
- **FRED** — US macro series with history, free with a key.

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

- China's 10Y is ~1.70% against the US 4.30%, a **−260bp** move.
- A −250bp move on 0700.HK was already measured at **624.90 → 1,225.93** — roughly doubling.
- China's country risk premium is ~0.91pp, so **it does not offset the rate cut.** The hope
  recorded in `TODOLIST.md` that the two legs would cancel does not survive the numbers.
- And discounting CNY flows at a CNY rate then converting at **spot** is not obviously right:
  interest-rate parity implies a low-rate currency trades at a forward premium, so the
  conversion arguably needs a forward rate.

Today's treatment is wrong in a **named** way. The naive fix would be wrong in an **unnamed**
way, which is worse. Nearly doubling a valuation on an unexamined FX assumption is precisely
the failure this platform exists to avoid, so the rate leg waits until spot-versus-forward is
settled in writing with a worked example.
