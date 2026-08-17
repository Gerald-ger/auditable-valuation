# Changelog

Notable changes to the Stock Analysis Platform. Newest first.

Format note: entries record *what changed and why it mattered*, with the measured
before/after where a change moved numbers the UI displays.

---

## 2026-08-17 (f) — a dispersion band, and two indicators tested rather than argued

A review of which technical indicators are worth adding. Frontend **46 → 54 passing**,
backend 423 unchanged — no backend code was touched. The decisions were made by running
tests on real data rather than by weighing opinions, and two of the three candidates were
rejected by their own measurements.

### Added

- **A ±2 SD dispersion band on the price chart**, off by default, centred on the MA20
  already drawn. It fills the one real gap: price, MAs, RSI, MACD and volume all describe
  level or momentum, and nothing answered "is today's move large for this name lately?".

  **Deliberately not called Bollinger Bands.** `%B`, the signal usually read off them, is
  an exact affine transform of a z-score — `%B = 0.5 + z/2k` — which the suite pins to ten
  decimal places, so a band tag carries nothing beyond "price is *z* standard deviations
  from its own recent mean". The plain name describes the lines; the eponymous one imports
  a trading claim. Nothing here needs validating against forward returns because nothing is
  asserted — the same reasoning that let the beta confidence interval ship.

  Two measured facts sit on the tooltip so it is not read as a signal: **88.5%** of closes
  fall inside (12,461 daily bars, ten names — not the 95.4% a normal distribution implies,
  because σ is estimated in-sample from the very window containing the price), so tags run
  at about **28 a year**.

  Not sent to the AI, and structurally so: the band is computed in the browser and never
  reaches the backend, and the AI context carries only `user_chart_drawings` plus model
  outputs. No indicator of any kind crosses that boundary today.

  Methodology, each decided by measurement rather than preference: period 20 so the centre
  coincides exactly with the MA20 already on the chart; the **population** divisor (÷n) to
  match charting convention, the sample form being 2.60% wider and lifting containment to
  ~90.0%; emission from bar `period-1` so it aligns with `smaSeries` bar-for-bar, which a
  test asserts; and a two-pass variance, taken because it is free rather than because it
  was needed — the one-pass form was measured at a maximum relative error of **1.5e-12**
  even at BRK.A price levels.

### Fixed

- **The README described indicator windows that no longer exist.** It said windows were
  measured in trading days, so MA50 meant 50 days on every period. `09ee627` (2026-08-13)
  changed them to count bars — because a 50-day average does not exist inside a one-day
  chart at any bar size, so MA, RSI and MACD simply vanished on the short periods — and
  the README was never updated. It now describes what ships, including why the trading-day
  scheme was abandoned and how the ambiguity is paid for in the UI instead.

- **A z-score ceiling stated the wrong way round.** For a window of *n* points the maximum
  distance any close can sit from its own mean is `sqrt(n-1)` under the population divisor
  and `(n-1)/sqrt(n)` under the sample one. The first draft had them swapped, quoting 4.25
  where the population form gives **4.3589** at n=20. Caught by the test, not by review,
  and only because that test derives the bound from the most extreme window possible
  instead of asserting a remembered formula — the largest deviation ever observed in the
  measured set was 4.00, which sits below both values and could never have distinguished
  them.

### Not done, deliberately

- **Fibonacci retracement — tested and rejected on this repo's own data.** Ten names, five
  years of daily OHLCV, 12,461 bars. For each ZigZag threshold, a permutation test asked
  whether the Fibonacci level set captures more retracement terminations than a random
  level set of the same size:

  | ZigZag | retracements | Fib captures | random | z | p |
  |---|---|---|---|---|---|
  | 5% | 1,737 | 244 (14.0%) | 229.9 ± 52.9 | +0.27 | 0.415 |
  | 8% | 663 | 100 (15.1%) | 89.4 ± 20.5 | +0.52 | 0.326 |
  | 10% | 364 | 58 (15.9%) | 48.9 ± 11.3 | +0.81 | 0.226 |

  Not significant at any threshold, and the test was **biased in Fibonacci's favour** —
  the random levels were drawn from [0.15, 0.85], which includes a near-empty region the
  Fibonacci ratios avoid. Terminations are near-flat from 0.4 to 1.0. This matches the
  published direct test (Batchelor & Ramyar on the Dow) but no longer rests on it.

  The stronger argument is internal: **the drawn horizontal levels already shipping are the
  honest version of this feature.** They report how many bars actually touched a line, so a
  user who believes in 61.8% can draw it and find out. Auto-drawn Fibonacci would replace a
  measurement with an assumption.

- **Stochastic oscillator — redundant with the RSI already shipping, and noisier.**
  Measured on true intraday high/low across the same ten names: level correlation with
  RSI(14) is **0.845**. More decisive than the correlation is the containment: `%K<20`
  holds **93.9%** of all `RSI<30` events while firing **9.0× as often** (AAPL 236 against
  29; NVDA 198 against 11). It is not a second opinion, it is the same opinion with roughly
  eight extra false alarms each time.

  It also has a defect RSI does not: its denominator is built from the window's min and max,
  the least robust order statistics, so **%K can move when the price has not** — purely
  because the bar that set an extremum rolled out of the lookback.

- **EMA as an overlay — deferred, not rejected.** `emaArray` already exists as MACD's
  helper so the cost is near zero, and it asserts nothing. But EMA(N) and SMA(N) have an
  identical mean lag of (N−1)/2 and identical iid-noise suppression of 1/N — verified
  exactly — differing only in weight shape (3× lag variance, ~1.9× weight on the newest
  bar). Measured level correlation with the SMA20 already drawn is **0.9991**, while
  producing **14% more price crossings** (higher on 9 of 10 names, tied on one). More
  whipsaw for the same information. Left out until there is a reason beyond parity with
  other tools.

- **VWAP, and candlestick pattern detection.** Session VWAP is well-defined on 2 of the 9
  periods this app offers and undefined on 2 more; on the 1h intervals a US session is
  seven bars whose last is only 30 minutes long and carries the closing auction, which
  makes the average systematically close-biased. Anchored VWAP is sold as the average
  holder's cost basis, which fails at real turnover — a six-month anchor accumulates volume
  equal to roughly half of a mega-cap's shares outstanding and several multiples of a
  high-turnover name's. Candlestick patterns are defined by relationships *within* a bar,
  and a bar here is 1m to 1wk depending on a dropdown, so the detected set would change with
  no change in the company.

## 2026-08-17 (e) — three things the model said that the world does not

A review of the valuation engine against reality, run by executing the model over every
committed fixture and reading the output rather than the code. Backend **409 → 423 passing**
(14 new tests), frontend 46. One golden moved, by one metric, as predicted before the change
was made.

### Fixed

- **The vendor's EV multiples divided an HKD enterprise value by CNY financials.** Yahoo
  computes `enterpriseToEbitda` and `enterpriseToRevenue` itself, and its two legs are in
  different currencies for a China-domiciled HK listing: EV comes from `marketCap` (trading)
  and EBITDA/revenue from the statements (reporting). Proved rather than inferred —
  `marketCap / shares` reproduces 0700.HK's HKD quote to the cent, `totalRevenue` matches the
  CNY statement, and `EV / totalRevenue` reproduces the published ratio to four decimals, so
  the currencies of both legs are pinned independently.

  0700.HK's EV/EBITDA read **15.705× against a like-for-like 14.277×**, and EV/Revenue 5.772×
  against 5.247× — overstated by the whole CNY→HKD rate. Downstream: the scored `ev_ebitda`
  metric 43 → 49 and the valuation pillar 60 → 62 (composite held at 71/A, so the score
  absorbed it); the market-implied terminal growth 5.89% → 5.46%; and the Models tab's
  implied multiple compression, which reads a currency-consistent exit multiple against this
  one, −44.6% → −39.1%.

  This also removes a compounding error in `comps.ev_implied`, which multiplies a peer
  multiple by the target's reporting-currency EBITDA and *then* converts: with a mismatched
  vendor multiple it converted the enterprise-value term twice while converting net debt
  once. Target and peers are both restated, per peer, because correcting one side of a comps
  table and not the other is worse than correcting neither — an all-HK peer set carries the
  same mismatch.

  The correction lives in the model layer, not in `data_provider`, deliberately: the test
  fixtures *are* captured `get_fundamentals` output, so a fix at the fetch boundary would
  have been invisible to the offline suite while every test stayed green.

- **A REIT was charged 21% corporation tax.** `tax_rate_for` keyed on listing currency alone.
  Elsewhere the gap between statutory and effective is tax planning, and statutory is the
  right input for a debt shield because it is the marginal rate; a REIT is different in kind,
  deducting what it distributes, so the marginal rate is approximately zero. Realty Income's
  own income statement reports 85.3m of tax on 1,155m pre-tax — **7.4%** — and that residual
  is its taxable subsidiaries rather than the trust.

  WACC 6.05% → **6.58%**, fair value 36.00 → **27.04**. The rule reads through
  `sector_weights.classify`, the same classification `dcf_applies` uses, rather than
  re-testing the industry string in a second place. Verified that only the REIT moved: the
  other six fixtures hold the rate their listing currency implies.

  Its golden did not move, and the reason was checked rather than assumed — the REIT profile
  scores `ffo_yield`, not `dcf_upside_pct` or `roic`, so the rate never reaches its score.

### Added

- **A regressed beta now reports how well it fit.** The credibility band tested whether the
  *value* looked sane and nothing tested whether the regression meant anything. Measured
  across the fixtures, that is the difference between 0700.HK at R² **0.691** and XOM at R²
  **0.028** — an index explaining under 3% of a company's variance — both arriving at the
  audit row as bare four-decimal numbers.

  XOM's 95% interval is **[0.08, 0.49]**, which is wider than the estimate it brackets, and
  inside that interval alone its fair value runs **123 to 228** (−19% to +50% upside) against
  a single published figure of 157.30, "+3.7%, fairly valued". Its window sensitivity says
  the same thing: 0.048 at 2y, 0.040 at 3y, 0.254 at 4y, 0.289 at 5y.

  `market_series.beta_fit` now returns the slope with its standard error, R² and 95%
  interval; `beta` is a thin reading of it so the value and its statistics cannot be computed
  two different ways. The standard error is the textbook OLS slope error and reuses the
  `variance` accumulator already there as its `Sxx`, so it costs one pass and no new
  dependency — cross-checked against numpy's `polyfit(cov=True)` covariance matrix and the
  algebraic form, agreeing to **1e-12** on all seven fixtures, with the identity
  `t² = R²/(1−R²)·(n−2)` holding exactly.

  The audit row also shows the **unclamped** slope, so a credibility band firing on a
  measurement is legible: XOM reads *used 0.30, regressed 0.2888* where it previously printed
  0.30 alone.

  `resolve_beta` keeps its `(beta, source)` signature. It has one caller in the app and about
  twenty in the suite, and widening it to carry reporting-only figures would have churned all
  of them; `_wacc` asks for the fit directly, guarded on the source actually being a
  regression.

### Not done, deliberately

- **No "fit too weak" threshold.** Rejecting a weak regression sends XOM down the ladder to a
  flat **1.0** — its reported 0.173 fails the band and fewer than two peers survive it —
  which is the neutral non-answer the regression was built to escape, and would move its fair
  value to 76.69. Worse, the threshold is uncalibratable here: R² jumps 0.028 → 0.148 with
  nothing between, so anything from 0.05 to 0.14 rejects exactly XOM. That is a constant
  chosen to produce a chosen outcome, which is the objection that removed the old growth
  clamp. The figures are published and the reader decides.

- **`BETA_MIN` still clamps computed betas.** Worth 2.76 per share on XOM and nothing
  elsewhere on the fixtures; now at least visible rather than silent.

- **The uncertainty display is asymmetric.** Beta carries an interval; the growth rate,
  equity risk premium and terminal growth do not, and that does not make them precise. Noted
  in `TODOLIST.md` rather than fixed by adding intervals nobody has derived.

## 2026-08-17 (d) — the README's own instructions, followed literally

An audit of every command the README tells a stranger to run, checked against what the repo
actually ships. **No application code changed** — backend **409 passing** (16 network-deselected),
frontend 46, `ruff` and `oxlint` clean, `vite build` green, all of it unchanged before and after.
One instruction was broken outright; the rest were true statements that stopped being true.

### Fixed

- **`pytest` was not installed by any documented step, and the Tests section told you to run it.**
  Install brings `backend/requirements.txt` (107 packages) and `pip install -e .`; neither carries
  `pytest`. It exists in exactly one place in the repo, `requirements-test.txt` (6 entries), which
  the README described as what *CI* installs — framing it as someone else's file. So the documented
  sequence ended at `No module named pytest`, reproduced in a clean venv rather than assumed.

  §Tests now installs it first. Verified the way it had to be — a **fresh 3.14.6 venv**, given only
  `pip install -e .` and `pip install -r backend/requirements-test.txt`, then `pytest`:
  **409 passed, 16 deselected**. Testing this in the existing venv would have proved nothing, since
  that venv has had `pytest` all along, which is why the gap survived this long.

  Layering the test set over `requirements.txt` is a measured no-op — `pip --dry-run` reports zero
  installs, zero upgrades, zero downgrades, zero conflicts — so it cannot disturb the `fastapi` /
  `uvicorn` ceiling OpenBB pins.

- **The Node floor was wrong in both directions.** README and `engines` both said `>=22`. The
  toolchain says `^20.19.0 || >=22.12.0` — Vite 8.2.0, oxlint 1.76.0 and `@vitejs/plugin-react`
  6.0.5 all declare it. So 22.0–22.11 satisfied the documented requirement while failing the real
  one, and 20.19+ was excluded despite working. Both files now carry the toolchain's own range;
  `package.json` and `package-lock.json` had to move together or `npm ci` refuses to run at all.

  Untested rather than known-broken, and the README now says so: nothing has ever run in the
  22.0–22.11 window. Development is on 24, and CI's `node-version: "22"` resolved to **v22.23.2**
  with no `EBADENGINE` warnings — read out of the run log, not inferred.

- **`.\start.ps1` fails on a stock Windows install**, which the README offered as a peer of
  `start.bat` with no caveat. A default client policy blocks unsigned scripts; this machine only
  runs it because `CurrentUser` is `RemoteSigned`, and that setting does not travel with a clone.
  The README now quotes the actual refusal — `running scripts is disabled on this system` — and
  gives the two ways out. Both the failure and the documented workaround were run to confirm the
  wording is verbatim.

- **`start.bat` and `start.ps1` launched blind; `start.sh` had always checked.** Double-clicking
  before installing opened two windows that each died on a missing interpreter — worst first
  impression on the platform the README leads with. Both now carry the guard `start.sh` already
  had. Exercised in **both** directions with the launch calls stubbed: absent venv → one readable
  line, exit 1, nothing spawned; present venv → falls through to both launches with the paths
  correctly interpolated. `start.ps1` also stops naming the interpreter path twice, so the guard
  and the command it guards can no longer drift apart.

### Changed

- **`pip install -e .` now runs before the dependency install.** `requires-python` is the version
  gate and `-e .` is the only step that reads it, so ordering it last meant paying for 107 packages
  before being told the interpreter was wrong. Measured on Python 3.11: **8.8 s** to
  `ERROR: Package 'finance-analysis-platform' requires a different Python: 3.11.3 not in '>=3.14'`.
  Safe because `-e .` needs nothing from `requirements.txt` — into an empty venv it installs
  exactly one distribution, itself.

- **The `./start.sh` Ctrl-C claim is now hedged like every other uncertain claim here.** It was
  stated as fact; the record says the trap could never be exercised from this machine's Git Bash.
  Every other unverified thing in this README carries a caveat, and this one now does too.

### Not done, deliberately

- **CI still never installs `requirements.txt`.** It installs the 6-entry test set, so the README's
  real install path — 107 pins including OpenBB and its 30 subpackages — remains proven on one
  Windows 3.14.6 machine only. No metadata conflict exists (`openbb`, `openbb-core` and
  `openbb-sec` all declare `>=3.10,<4`; `pandas>=3.11`; `numpy>=3.12`), so this is an untested
  path rather than a suspected one. Closing it means a CI job that installs and does nothing else.

## 2026-08-17 (c) — two warnings that were not telling the truth

Backend **409 passing** (16 network-deselected), frontend 46. `npm run lint` is now clean; it
had emitted one warning on every build.

### Fixed

- **The portfolio's mixed-currency warning fired on portfolios that were not mixed.** It read the
  currency of every row, including watchlist entries, but the sentence it prints is about the
  *totals* — and a watchlist row has no market value, so it is absent from every total. Five USD
  holdings listed beneath one watched HK name produced a red warning about an FX problem that did
  not exist. The published `docs/images/portfolio.png` is a picture of exactly that.

  It now reads the same set the backend uses to build `held` — truthy `market_value` — which also
  excludes a held row whose quote failed, for the same reason: it is not in the totals either.
  Verified in both directions against the running app, because a warning that never appears would
  also have passed a test that only checked it was gone: five USD holdings → hidden; give the HK
  name shares → shown; take them away → hidden.

  The underlying limitation is untouched and still open — totals really do add HKD and USD at
  face value. Only the trigger was wrong.

- **`ScorecardTab` emitted an `exhaustive-deps` warning on every build.** `loadComps` was a plain
  function, rebuilt each render, so listing it in the effect's dependencies would have refetched
  on every render and omitting it was the warning. It is now `useCallback` keyed on `ticker`, the
  only input it reads, so its identity changes exactly when the effect's own dependency does —
  same behaviour, one fewer suppression. This is the pattern `PortfolioTab` already used.

  Deliberately *not* the `eslint-disable-line` used at `PriceChart.jsx:344`: that one marks an
  effect that must not list `pinned` because it sets `pinned` and would loop. Nothing here loops;
  suppressing it would have hidden a fixable problem behind a comment meant for an unfixable one.

### Added

- **`docs/currency-consistent-discounting.md`** — the written analysis TODOLIST set as the trigger
  for the HK risk-free-rate item, with a worked 0700.HK example. No code changed. It resolves the
  spot-versus-forward question (spot is correct; the concern as recorded was inverted, and a
  forward rate on top of a local-currency discount rate would count the interest differential
  twice), and corrects the recorded sizing: measured with every leg moving, the effect is **+50.5%**
  (680.99 → 1,024.98), not the "roughly doubles" previously recorded from moving the WACC alone.

  It also reports why: `terminal_growth = min(TERMINAL_GROWTH, rf)`, so lowering the rate lowers
  the growth cap with it and the terminal spread `WACC − g` is almost invariant once the cap binds
  (5.25% → 3.49% → 3.50% across 4.30% / 1.70% / 1.10%). That makes the contestable half of the
  change — whether to net off the sovereign default spread — worth 1.8%, while the well-supported
  half is worth +50%.

  The item stays open, on a better-posed question: adopting a 1.1–1.7% CNY risk-free rate also
  asserts that Tencent grows at 1.1–1.7% in perpetuity, which the cap imports silently. That is a
  macro forecast arriving through the back door, and it has to be settled before any rate changes.

---

## 2026-08-17 (b) — the README shows the product

### Added

- **Five screenshots, one per tab**, under *What it looks like*, directly beneath the disclaimer
  so a visitor sees the product before the install steps.

  Financial Models and Scorecard are cropped. GitHub renders README images at about 890 px wide,
  so the full 1400 px captures landed at 63% and their body text was unreadable; each is cut to
  the part that carries the argument. Cut lines were chosen by scanning each row for text and
  cutting inside a blank band rather than by eye — `models.png` 1263 → 578 px and 245 → 105 KB,
  `scorecard.png` 1294 → 724 px and 272 → 130 KB.

  The demo portfolio is fabricated and the README says so. Its first version used a cost basis of
  999 for XOM against a price near 160, showing −84% and dragging the total to −35%; on a project
  whose pitch is auditable valuation, a number that could not have happened reads as a defect. At
  175 the position shows −8.5% in red against a +41.6% total in green, exercising both states of
  the P&L styling.

### Not done, deliberately

- **The screenshots were not automated.** The tab and ticker are React state, not URL parameters,
  so a headless browser only ever reaches the Tracker tab on its default ticker. Every shot needs
  a real click.
- **The AI panels show "offline" and were left that way.** Ollama is not installed here, and the
  README's own limitations section says so. A screenshot showing the documented state is more
  honest than one staged around it.

---

## 2026-08-17 (a) — a stranger can clone it and run it

Backend **408 → 409 passing** (16 network-deselected), frontend 46. Scope changed from
*portfolio piece only* (2026-08-14) to **a runnable source project**: Docker and binary releases
remain out.

### Changed

- **`backend/` is a real Python package.** The modules imported each other flat (`import comps`),
  which worked only because uvicorn was launched with `--app-dir backend` and the test conftest
  edited `sys.path`. Nothing outside `backend/` could import the code, and generic names —
  `search.py`, `store.py`, `main.py` — sat directly on `sys.path` beside site-packages.

  Adds `pyproject.toml` and `backend/__init__.py`, rewrites sibling imports to
  `from backend import …`, and drops the `sys.path` insert. Install with `pip install -e .`; the
  launchers now run `backend.main:app` from the repo root with no `--app-dir`.

  The import *form* is preserved deliberately — `from backend.data_provider import fx_rate`, never
  `from backend import data_provider` plus attribute access. Two autouse fixtures monkeypatch
  `financial_models.fx_rate` and `.risk_free_rate` to pin the FX rate and treasury yield, and
  those patches bind because `from X import name` copies the name onto the importing module.
  Attribute access would have made both fixtures inert, the "offline" suite would have started
  hitting the network, and every golden score would drift with the market — silently, with nothing
  turning red. Proved by poisoning `RISK_FREE_RATE` and confirming the golden snapshot fails.

  `backend/__init__.py` is empty and must stay: deleting it keeps all 409 tests green through the
  namespace-package fallback while breaking `pip install -e .`. The suite does not protect it.

- **Three requirements files became one runtime set.** None was named `requirements.txt`, which
  forced a documented workaround in CI, and two of them pinned `fastapi` to different versions.
  `requirements.post-openbb.txt` → `requirements.txt`; the pre-OpenBB rollback snapshot deleted
  (the README recorded that it will not boot the app — it omits `aiohttp`); ruff's pin moved out of
  the workflow into `requirements-test.txt`. CI now also runs `pip install -e .`.

- **The frontend talks to `/api` on its own origin.** Vite proxies it to port 8000, so CORS is not
  involved in development at all. Before this, Vite silently moved to 5174 when 5173 was taken
  while the backend allowed exactly two origins: the page rendered normally, with no data and no
  error anywhere, which is close to undiagnosable for a first-time user. `strictPort` now turns
  that collision into a loud startup failure. Better than adding 5174 to the allow list, which
  only moves the trap one port along.

- **README leads with install.** Prerequisites, Install and Run moved from line ~206 to the top,
  and macOS/Linux gets a full install path rather than a paragraph telling it to substitute the
  interpreter throughout.

### Added

- **`start.sh`** for macOS/Linux. Both existing launchers are Windows-only — `start.ps1` calls
  `powershell`, which does not exist off Windows. Vite runs in the *foreground* so Ctrl-C reaches
  it through the terminal, leaving the trap responsible only for a single childless backend
  process. `.gitattributes` pins its line endings, because CRLF would fail at the shebang with an
  error that names no line ending.
- **`engines: { node: ">=22" }`**, which existed only in prose and CI before.
- **A test guarding the methodology document `ai_client` reads at runtime.**
  `_reference_excerpt` swallows `OSError` and returns `""` — correct at runtime, but it means
  reorganising `docs/` would quietly strip the methodology out of every AI answer with no error
  and no log line.
- **`docs/release-readiness.md`** — what is done, what is deliberately not, and the limitations a
  reader deserves up front, including that CI never installs the runtime requirements set, so a
  broken runtime pin passes green.

### Fixed

- **The staleness banner printed a launch command that no longer works.** The banner shown when
  the backend is running older code told the user to restart with
  `uvicorn main:app --app-dir backend`, which fails under the new packaging. The one piece of UI
  whose entire job is to get the user unstuck was handing them a broken instruction. Nothing
  caught it because it is a string in JSX: the suite verifies that the app runs, not that it tells
  people the truth about how to run it.
- **A false claim about the Python floor.** The README said `pandas==3.0.5` and `numpy==2.5.1`
  "publish no wheels for earlier interpreters", presenting 3.14 as dependency-imposed. Checked
  against PyPI: pandas ships wheels back to cp311 and declares `>=3.11`; numpy back to cp312 and
  `>=3.12`. The real floor is `requires-python` in `pyproject.toml`, set to match the only tested
  configuration. Both documents now say that instead of inventing a constraint.
- **The tier palette had three copies.** `TIER_COLORS` was defined identically in three
  components and `ScreenerTab` reimplemented `scoreColor` with raw hex instead of the CSS
  variables the rest of the app uses, so the screener would have drifted from every other tab the
  first time the theme changed. Verified no-op: its literals were exactly `--up` / `--gold` /
  `--down`.

### Not done, deliberately

- **No `.env` or env-var config.** Port 8000 was hardcoded in six places, but the real defect was
  the repetition, which the proxy change removed. Module constants stay.
- **`index.css` (2,033 lines) and the two largest tab components were not split.** Real
  single-contributor risks, but there are no component tests, so the diff would be unverifiable.
- **The Python floor was not lowered.** 3.12/3.13 would plausibly work; lowering it honestly means
  running the suite there first, which is a task, not a config edit.

### Repository

- Local tooling removed from git history. 38 `.claude/agents/*.md` files were committed in the
  first commit and deleted later, but a deletion only adds a "these are gone now" entry — anyone
  who cloned could still read every one with a single `git show`. Removed from the whole history
  with `git filter-repo`; the tree hash was byte-identical before and after, which is the proof it
  changed no current content.

  Verified, not assumed: **GitHub still serves the removed files to a direct request for the old
  SHA** after a force-push, because that does not trigger garbage collection. Recorded rather than
  chased — the content was agent role definitions with no credentials and no personal data, and
  the hash appears in no file, no commit message and no entry of the repo's public events API.
- Default branch `openBB-testing` → `main`, the experiment branch deleted, description rewritten
  from a keyword dump into a sentence, 14 topics set. Project name aligned across the repo slug,
  `pyproject.toml` and the README title.

---

## 2026-08-14 (f) — the price is as fresh as the feed allows, and says how fresh

Backend **402 → 408 passing** (16 network-deselected), frontend 46.

### Changed

- **The price is refetched on a 60-second cache instead of riding the 15-minute fundamentals
  cache.** Measured: `/analysis` returned 441.0 twice seconds apart while the uncached `/quote`
  said 441.2, because the price sat inside `get_fundamentals`'s TTL. Stacked on Yahoo's own
  15-minute delay that put the valuation screen up to **~30 minutes** behind the market. It is
  now ~15 — the vendor's floor — and `/analysis` and `/quote` agree.

  Five places read the price and all five read the same two `info` fields, so one refresh point
  fixed the DCF upside, the football-field price rule, the gap bridge, the momentum metrics and
  the score history with no call-site changes.

  60 seconds rather than uncached because one page view fires several endpoints at once — a
  Scorecard load hits `/score`, `/peers` and `/comps` — so this is one quote fetch per view
  instead of three or four, while staying far inside the delay it exists to work around.
  `get_quote` remains uncached; the Tracker depends on that.

### Added

- **`price_as_of` and `price_delayed_by_minutes` in the DCF assumptions**, rendered in the audit
  row. Both are the vendor's own figures, forwarded rather than estimated. The price was the
  denominator of the headline upside and the only input on that screen carrying no provenance,
  while beta, FCF, the equity premium and the FX rate all state theirs.

### Not done, deliberately

- **Market cap is not refreshed with the price.** It feeds the WACC weights, so refreshing it
  would make fair value drift intraday with no filing having changed — a valuation that will not
  reproduce minute to minute. Leaving it also keeps P/E, P/B, EV/EBITDA and `fcf_yield` mutually
  consistent as of one snapshot rather than half-refreshed. Pinned by a test: two different
  prices must leave `fair_value_per_share` and `wacc` identical while `upside_pct` moves.
- **The batch screener keeps the snapshot price.** A stale quote cannot reorder a ranking, and a
  fetch per ticker would roughly double the network work of a fifty-name run.
- **Yahoo's 15 minutes stays.** `docs/data-sources-review.md` already records that no free
  source clears it for HKEX.

### Fixed

- **The refresh copies rather than mutates.** `get_fundamentals` output is TTL-cached and shared
  between requests, so writing a price into it would hand a later caller statements and a price
  from different fetches with nothing saying so. Asserted directly, and mutation-checked by
  making it mutate, which fails that test alone.

---

## 2026-08-14 (e) — the app notices when the backend is running old code

Backend **399 → 402 passing** (16 network-deselected), frontend 46.

### Added

- **`source_changed_since_start` on `GET /api/health`**, and a banner when it flips. A digest
  of `backend/*.py` is captured at import and re-checked per call.

  This exists because the equity-bridge panel shipped at 14:17 against a backend started at
  13:28, so the API never returned `diagnostics.equity_bridge`, the panel correctly rendered
  `null`, and the result was indistinguishable from a feature that had never been built —
  diagnosed by hand, for the third time in one day. `ErrorBoundary` already told the reader to
  suspect a stale backend; now the app says it before anything looks broken.

- **`/health` replaces `/ai/status` as the frontend's poll.** It already carried the same AI
  block, so one 30-second timer now answers both questions instead of adding a second.

### Fixed

- **The digest reads text, not bytes.** A byte hash looked correct and was wrong on Windows:
  measured 2026-08-14, `git checkout` restored `sector_weights.py` with **252 CRLF** where the
  running process had loaded LF, so the guard reported a stale server for a file `git status`
  called unmodified. A banner nobody can clear is a banner people learn to ignore. Pinned by a
  test, and mutation-checked by reverting to `read_bytes()`, which fails it.

### Not done, deliberately

- **`--reload` is not recommended, and the README now says why.** Tried here first: WatchFiles
  logged `detected changes in 'backend\main.py'. Reloading...`, the replacement worker never
  started, and the old process kept serving — *with the log claiming it had reloaded*, which is
  worse than no reload at all. It also orphaned a child holding port 8000 after the parent was
  killed, so the next start failed with `WinError 10048` and the socket had to be freed by
  hand. The health flag does the job without pretending to fix it.

---

## 2026-08-14 (d) — the equity bridge carries four of its five terms

Backend **389 → 399 passing** (16 network-deselected), frontend 46.

### Changed

- **The EV→equity bridge implements the identity its own reference document states.**
  `docs/financial-models-reference.md:38` specifies
  `EV − Net Debt − Minority Interest − Preferred + Non-operating Assets`. The model
  implemented one term; `dcf_valuation` never read the balance sheet. Three are now read
  from the newest balance-sheet date, and the fourth is reported without being adopted.

  | | now | was | minority interest | marked securities |
  |---|---|---|---|---|
  | **0700.HK** | **498.67 (+3.6%)** | 427.75 (−11.1%) | −11.23 | **+82.11** |
  | AAPL | 140.00 (−55.0%) | 134.67 (−56.7%) | 0 | +5.33 |
  | MSFT | 269.64 (−44.7%) | (−45.7%) | 0 | +4.89 |
  | XOM | 157.30 (+3.7%) | 158.98 (+4.8%) | −1.75 | +0.07 |
  | O | 36.00 (−42.6%) | (−42.8%) | −0.73 | +0.86 |

  Tencent's verdict reverses **without any assumption entering the headline**, because the
  635bn of securities is already carried at fair value in the filing. Two directions across
  the set (Tencent up, XOM down), and no tier moved.

- **Associates and joint ventures are shown and excluded.** 348.7bn, +45.06/share on
  0700.HK, printed beside the headline as `fair_value_including_associates` and kept out of
  it — the same treatment the normalised base year already gets. Cost is neither a market
  value nor a floor, and the filing does not say which way it errs.

### Added

- **An equity-bridge panel on the Models tab.** Before this, a grep of `frontend/src/` for
  `totalDebt`, `balance_sheet`, `minority`, `associate` or `invest` returned **zero hits** —
  the reader could not see a single balance-sheet line anywhere in the product, and none of
  the 27 existing caveat strings mentioned what the valuation leaves out. The panel prints
  every term with its per-share effect and how it is carried. A company with nothing to
  bridge gets one line saying so, rather than silence that reads as "nothing was checked".

### Fixed

- **A consistency trap in the making.** `net_debt` was subtracted at four separate places —
  the headline, the WACC × terminal-growth grid, the growth sweep and the normalised base
  year. A bridge applied to some of them would have printed a sensitivity table whose centre
  cell disagreed with the fair value directly above it. Both grids now assert that their
  centre cell *is* the headline; mutation-checked by reverting one site, which fails that
  test and nothing else.

- **No cross-year fallback in the new reads.** `_value_at`, not `_latest`. MSFT reports
  `Long Term Equity Investment` at 2025-06-30 and nothing at 2026-06-30, so `_latest` would
  have carried a year-old balance into today's valuation — the period-drift defect that
  produced FY2025 EBIT over FY2023 interest once already. A vanished row reads nil and is
  named; a row never reported is silently nil, because flagging that would warn on all seven
  fixtures and train the reader to ignore warnings.

### Not done, deliberately

- **Associates are not marked.** Adding them at carrying cost would flip Tencent a second
  time on a number the filing does not support.
- **`comps.ev_implied` still uses the one-term bridge** (`comps.py:222`), so peer-multiple
  bars and the DCF bar on the same football field now differ in basis by ~71/share on
  0700.HK. Changing it moves every peer bar on every company and every verdict read off
  them, which is a different blast radius; logged in `TODOLIST.md` with the next
  football-field change as its trigger.

---

## 2026-08-14 (c) — beta and relative strength are measured, not read

Backend **373 → 389 passing** (16 network-deselected), frontend 46.

### Changed

- **Beta is regressed from price history instead of read from the vendor.** New
  `backend/market_series.py` runs cov/var over five years of weekly returns against the
  home index — `^HSI` for `.HK` tickers, `^GSPC` otherwise — cross-checked to 1e-9 against
  numpy's covariance and a least-squares slope. It sits above the existing ladder; the peer
  and reported tiers keep their old order, so a history outage restores exactly the previous
  behaviour rather than a third one. The vendor figure stays on screen as a cross-check.

  | | was | now | composite | fair value |
  |---|---|---|---|---|
  | XOM | 1.0 *(neutral default)* | **0.2888** → 0.30 | 70 → **74** | **+103%** |
  | 0700.HK | 0.745 *(vendor)* | **1.3192** | 73 → **70** | −34% |
  | AAPL | 1.086 | 1.1546 | 65 → 65 | −4.6% |
  | MSFT | 1.099 | 1.1412 | 71 → 71 | −3.0% |

  Two directions, and no tier moved. XOM's +103% is the size of an error that was already
  there: a neutral 1.0 standing in for a company whose measured beta is 0.29.

- **Relative strength is measured against the index the company actually trades on.**
  `rel_52w_change` benchmarked every ticker to the S&P 500. Both legs are now computed from
  weekly closes; 0700.HK reads −23.79% against the Hang Seng where the S&P gave −45.15%.
  Falls back to the old vendor scalars when bars are unavailable, and flags it.

- **`_ttl_cached` now keys on every argument, not just the ticker.** It was fine while every
  cached method took nothing else. Caching `get_history` on the old key would have served
  the chart's 1y hourly bars to the beta regression's 5y weekly request, or the reverse.

### Added

- `backend/tests/fixtures/bars/` — weekly closes for the seven fixtures plus both indices,
  144 KB. `capture_fixtures.py` gained `--bars-only` / `--fundamentals-only`, because
  regenerating the statements refetches live data and would move every pinned figure with it.

### Fixed

- **A UI message that became an accusation.** `ModelsTab` printed "(reported X, **not
  credible**)" whenever beta came from anywhere but the vendor. Once a measured beta can
  outrank a perfectly credible vendor one, "we had something better" and "your data is
  untrustworthy" stop being the same statement. The backend now reports
  `beta_reported_credible` and the UI says "vendor X", adding "not credible" only when the
  band actually rejected it.
- **`.src-tag.peer_median_relevered` had no style.** The class is the whole source string, so
  `.peer_median` never matched it — that tag has rendered unstyled since the re-levering tier
  was added. Pre-existing; fixed here because the same rule needed a `.computed` variant.

### Corrected

- **A stale figure I propagated.** Three documents stated 0700.HK's relative reading as
  −31.9% (from −13.6% and +18.3%). Those were live figures from an earlier date; yesterday's
  data-sources review copied them from `TODOLIST.md` without re-measuring. Computed from the
  committed bars it is **−23.79%** against the Hang Seng, or −45.15% against the S&P.
- **"yfinance's energy betas are broken" was wrong.** The regression says they were
  directionally right — XOM's vendor 0.173, measured 0.2888 and peers at 0.488 / 0.123 all
  agree the correlation is genuinely very low. What was broken is `BETA_MIN = 0.3`, which
  rejected every one of those readings and substituted a number nobody measured. The floor
  now binds on a *measured* value, which is logged as an open calibration question.

---

## 2026-08-14 (b) — the equity risk premium is sourced, and the data layer is audited

Backend **366 → 373 passing** (16 network-deselected), frontend 46.

### Changed

- **The equity risk premium is per market instead of a flat 5%.** `EQUITY_RISK_PREMIUM =
  0.05` was one number for every market and every year, with no source and no date — the
  largest remaining hardcoded constant in the model. It is replaced by Damodaran's published
  country table, vendored dated at `backend/market_risk_premiums.json`.

  | Market | was | now | effect on fair value |
  |---|---|---|---|
  | United States | 5.00% | **4.46%** | AAPL +9.2%, MSFT +9.8%, XOM +9.2% |
  | Hong Kong | 5.00% | **5.01%** | ~nil |
  | China (0700.HK reports CNY) | 5.00% | **5.14%** | 0700.HK **−1.8%** |

  It moves US valuations up and Tencent's down. That two-directional result is what makes it
  a correction rather than price tuning, and a test pins it so a future snapshot update
  cannot quietly make it one-way.

  Keyed on `financialCurrency`, deliberately unlike `tax_rate_for`, which keys on the
  trading currency: tax follows the filing jurisdiction, a discount rate follows the money.
  0700.HK trades HKD and reports CNY, so it is priced off China's premium.

  Vendored rather than fetched — the data changes twice a year, so a parser on the request
  path would be fragile for no benefit and would put a network call inside the offline test
  suite. The Models tab now names which of the three sources a valuation used
  (`damodaran_<date>` / `mature_market` / `platform_default`).

- **Golden scores.** One line moved: 0700.HK's `dcf_upside_pct` 82 → 80. Every other name is
  anchor-clipped at the −40 floor and unchanged; no composite and no tier moved.

### Added

- **`docs/data-sources-review.md`** — what the platform's numbers are actually made of.
  Records that there is effectively *one* data source rather than four, the three occasions
  this codebase has already proven that source wrong, a gap table saying which needs a free
  source can and cannot close, and the two fixes that need no new source at all (beta from
  price history, HK momentum against `^HSI`).

- **The yfinance licence position**, newly recorded as an open decision. It is
  personal-use-only and Yahoo's terms prohibit redistribution, which is fine locally and is a
  **blocker to resolve before the app is hosted or shared**. Kept for now because no free
  source covers Hong Kong fundamentals — FMP's free plan is US-only and Finnhub's
  international coverage is paid.

### Fixed

- **A test that stopped measuring its own subject.**
  `test_correcting_the_currency_also_corrects_the_wacc_weights` builds its comparison by
  flipping `financialCurrency`, which now also selects the ERP — so it was no longer
  isolating the capital-structure weighting effect it is named for. The premium is pinned
  across both runs there now. A genuine side effect of this change, caught by the suite.

### Not done, deliberately

- **The risk-free rate stays the US 10Y for every issuer**, and after measurement that is a
  decision rather than a backlog item. China's ten-year runs ~1.70% against the US 4.30%
  (−260bp) while China's country risk premium is only 0.91pp, so the legs do not cancel as
  `TODOLIST.md` had hoped — sourcing the rate would roughly *double* Tencent's valuation.
  A second problem also surfaced: discounting CNY flows at a CNY rate and converting at
  **spot** ignores interest-rate parity, which implies a low-rate currency trades at a
  forward premium. Today's treatment is wrong in a named way; the naive fix would be wrong
  in an unnamed way. Gated until spot-versus-forward is settled in writing.

---

## 2026-08-14 — the DCF bar carries its third assumption, and radius gets a rule

Backend **357 → 366 passing** (16 network-deselected), frontend 46.

### Changed

- **The football-field DCF bar now spans the base year as well as the rates.** The bar
  stressed WACC and terminal growth through the sensitivity grid and the starting growth
  rate through `growth_sensitivity` — three rate assumptions, and none of them the level
  those rates are applied to. `_dcf_band` now unions `fair_value_normalised` in, so the bar
  shows what the company's own multi-year average margin implies alongside what its newest
  filed year implies. Fair value is homogeneous of degree one in base FCF, so a level error
  there is permanent and undamped; it was the largest assumption the bar did not carry.

  Fires on two of four fixtures (risk-free pinned at 4.3%), and in both directions across
  the set, which is what distinguishes a band from a thumb on the scale:

  | | reported | normalised | bar before | bar after |
  |---|---|---|---|---|
  | XOM | 71.75 | 102.17 | 59.25–86.35 | **59.25–102.17** |
  | MSFT | 248.51 | 321.75 | 211.58–290.97 | **211.58–321.75** |
  | AAPL | 129.29 | 144.27 | 109.76–151.89 | unchanged, already inside |
  | 0700.HK | 663.32 | **628.00** | 561.47–781.62 | unchanged, already inside |

  The basis string names `+ base year` only when it moved an edge, following the rule the
  growth sweep's one-sided wording already set. The midpoint tick still marks the
  reported-year answer: this is a union, not a substitution.

- **Corner radius is four tokens instead of twelve values.** `--r-tag: 4px`,
  `--r-control: 6px`, `--r-surface: 10px`, `--r-pill: 999px` over 31 of 42 declarations.
  Visible movement is small and deliberate: four chips 5 → 6px, five surfaces 8 → 10px.
  `.tier-badge` (14px), `.chat-msg` (12px), `:focus-visible` and the concentric
  `.ff-track` / `.ff-bar` pair are kept as specials with the reasoning written beside them.

### Fixed

- **Ten "radii" that were really `height / 2`.** `.pillar-track` and `.pillar-fill` are 8px
  tall at 4px, `.ff-envelope` 6px at 3px, the scrollbar thumb 8px at 4px — pills expressed
  as numbers. The earlier audit had counted them as radius choices, and the three-token
  plan it produced would have flattened them into squircles. They now use `--r-pill`, which
  is pixel-identical for the exact halves and imperceptibly rounder for `.quality-*` and the
  3px swatches, already over-rounded past their own half-height.

### Not done, deliberately

- **The cyclical headline swap stays declined**, now on measurement rather than principle.
  XOM's FCF margins run 14.65 → 9.99 → 9.05 → **7.29%**, monotonically down, where MSFT,
  AAPL and 0700.HK oscillate: the four-year window holds a trend, not a cycle, so its mean
  is a lagged trend rather than a mid-cycle estimate. Separately, `SECTOR_MAP` routes
  `basic materials` to `industrials`, so no clean cyclical classification exists to key on.
  The scoring objection turned out to be nearly empty — `dcf_upside_pct` is anchor-clipped
  at −40, so XOM's metric moves 0 → 9 of 100 and the composite stays 70, tier A — but the
  two findings above stand. The bar union above takes the part of the value that costs no
  assumption. Full reasoning in `TODOLIST.md`.

---

## 2026-08-13 — the football field triangulates, and the base year stops being free

Backend **254 → 357 passing** (16 network-deselected), frontend 44 → 46. Two questions
answered: what the valuation chart is actually claiming when its bars disagree, and what
the DCF assumes by taking one filed year as its starting point.

### Changed

- **The growth clamp is gone.** `[0%, 25%]` was two economic judgements dressed as data
  hygiene. The floor grew shrinking companies at zero — fourteen analysts put XOM at
  −2.3%, and flooring it inflated fair value **15.7%**. The ceiling truncated a **42.6%**
  consensus from 55 analysts on NVDA. Replaced by a validity range of −50% to +200% that
  **rejects** a corrupt figure rather than truncating a genuine one, with the provenance
  labelled either way, so no number on screen is untraceable.

- **The explicit stage went 5 years to 1**, with a 9-year fade after it. The growth figure
  is a *one-year* consensus; holding it flat for five invented four years nobody forecast.
  Measured: AMD's 72.1% consensus compounded free cash flow **15.1×** over five flat years
  before any fade began, which is why its fair value ran from −81.4% clamped to +33.6%
  unclamped. One year at the forecast rate then a linear fade gives **7.2× on NVDA against
  13.5×** for the old plateau — most of the conservatism the cap was reaching for, without
  discarding a basis point of observed data. This is what let the ceiling go; the ceiling
  existed to survive the plateau, not to express a view about growth.

- **`analyst_upside` is no longer scored in any pillar.** It divided *someone's forecast of
  price* by price, while every other valuation metric divides a reported figure or the
  platform's own model. Worse, `dcf_valuation` already takes its growth from analyst
  consensus, so one source moved two of five V metrics with correlated errors of the same
  sign. The scoring curve also anchored 0% upside at **45/100**, i.e. near-neutral, against
  published targets that sit above price structurally — the seven fixtures scored a mean of
  **69** against a centred 50. Removed from scoring, kept on screen as labelled context,
  matching what the football field already did. Composite moved **−3 to +1**; no fixture
  changed tier.

- **Terminal growth shows its derivation** instead of appearing as a bare 2.5%, held under
  two displayed ceilings: long-run nominal GDP, and the risk-free rate per Damodaran. The
  cap applies **only** to the platform's default — a caller naming a rate gets that rate,
  because `solve_for_fair_value` sweeps past both ceilings on purpose and capping it there
  would report "closing this gap needs 7.01% perpetual growth" as unreachable, which is the
  most useful sentence the reconciliation produces.

### Added

- **The base year is now shown as the assumption it is.** Free cash flow enters the
  valuation linearly, so a base year 22% below normal is a valuation 22% below normal —
  permanently, through every projected year *and* the terminal value. Measured across the
  fixtures, the newest reported year sits below that company's own mean FCF margin for
  three of the four profitable names: **AAPL 0.90×, MSFT 0.78×, XOM 0.71×**, with 0700.HK
  the exception at 1.06×. Taking whatever period the vendor reported last is therefore a
  one-directional bias, and unlike the terminal-growth band it does not wash out across
  names — it penalises whoever is mid-investment or mid-cycle, corrupting exactly the
  cross-name ranking a screener exists for.

  `base_year_context` decomposes the base year **exactly** — `FCF/revenue = CFO/revenue −
  capex/revenue`, no residual and no assumption — so the panel separates a business
  *spending more* from one *earning less*. MSFT is the case it exists for: capex ran 13.3%
  → 18.1% → 22.9% → **34.9%** of revenue over four years while operating cash *rose* 41.3%
  → 55.1%. The reported year stays the headline; the normalised figure sits beside it and
  the platform explicitly declines to choose, because whether that capex wave ends is a
  forecast about the world, not a figure in the accounts.

  **The direction is the whole argument.** Normalisation moves 0700.HK *down* (+29.8% →
  +22.9% upside) while moving MSFT (−49.0% → −34.0%) and XOM (−52.7% → −32.6%) up. A change
  that narrowed every gap to the market price would be a price tracker, not a model, and a
  test pins both directions so a future change cannot quietly make it one-way.

- **The football field refuses to draw what does not apply.** The DCF bar is gated on
  `sector_weights.dcf_applies`, the same rule the scorer uses, so a REIT gets a struck-out
  row naming the reason rather than a confident number the Models tab suppresses one tab
  away. `peer_ev_revenue` is suppressed when target and peer operating margins differ by
  more than 2×: on 0700.HK the curated peer set medians **5.7%** operating margin (9988
  1.0%, 3690 −7.5%, 1024 10.5%) against Tencent's **34.3%**, so the peer median 1.84×
  revenue multiple implied **189.61** a share against a **439–471** cluster from every
  other multiple. That single number stretched the comps bar to **2.48× wide** and was the
  sole reason its verdict still read "in range" — a bar that broad contains any price.
  Analyst targets became context rather than a vote, with dispersion carried separately as
  an uncertainty signal.

- **A conviction grade that never varied was replaced by arithmetic.** It read LOW on all
  eleven names tested and the overlap zone was non-empty **once**; a signal that never
  varies is not a signal. The chart now leads with a bridge decomposing model value → price
  into named steps ending in an explicitly *unexplained* residual. The residual is left
  that way on purpose: it is the market pricing a longer advantage period, a lower discount
  rate or a higher terminal cash conversion than a ten-year fade at 2.5% can express, and
  closing it by tuning would make the DCF an expensive way to display the share price.

- **Market-implied terminal growth**, solved backwards from today's traded multiple, which
  is the more useful direction to read an exit multiple. Measured: AAPL 7.30%, MSFT 7.63%,
  0700.HK 3.23% against a 4.0% nominal-GDP line — so Tencent's price needs nothing unusual
  while Apple's needs free cash flow compounding above the economy in perpetuity.

### Fixed

- **White-on-accent failed WCAG AA at 3.68:1** (4.5:1 required) on the primary button, the
  active nav tab, the period picker, the segment controls and the user's own chat bubbles —
  all 13-14px body text. The hover state measured **4.80:1**, i.e. *more* readable than the
  resting state, which is backwards. Filled surfaces now use `--accent-fill` (#2b6fd9,
  4.80:1) with `--accent-fill-hover` (#1d4ed8, 6.70:1); `--accent` still drives strokes,
  links, focus rings and chart bars, all of which already passed.

- **71 user-visible strings** had em-dash and en-dash punctuation restructured into periods,
  colons, commas and parentheses. The `—` no-data glyph returned by `num`/`big`/`pct` was
  deliberately **kept**: in a column of financial figures a hyphen reads as a minus sign,
  and that glyph is a table convention rather than prose.

- **Four defects in the above, caught by reviewing the work rather than by the tests.** The
  base-year panel quoted its ratio against the mean of *all* years and its two legs against
  the mean of the *others*, so a reader recomputing from the table on screen got −5.8pp
  where the sentence beneath said −7.7pp. The driver sentence claimed "spending more, not
  earning less" for XOM, where capex rose **and** operating cash fell — both legs adverse.
  A first fix for that keyed on the two signs alone and contradicted itself on 0700.HK,
  naming operating cash the larger leg and calling it "a business spending more" in the same
  breath; the six reachable combinations now resolve in the backend where they are tested.
  And rounding was applied per period then averaged, compounding a display artefact instead
  of landing once at the output.

---

## 2026-08-10 (b) — the two decisions the review left open

Both items the three-lens review deliberately did not settle alone, now decided. Backend
**246 → 254 passing, and the 3 xfails are gone** — the calibration below fixed the
behaviour they were pinning.

### Fixed

- **Cash runway ignored capital expenditure**, which for a pre-profit manufacturer is most
  of the burn. RIVN's 2025 operating outflow is **0.78bn against 1.71bn of capex**, so
  runway read **27.3 quarters** — past the anchor table's top rung at 20, scoring 100 —
  where the free-cash-flow burn gives **8.5 quarters and 63**. Overstated by **3.2×**, on
  the single metric the pre-profit Health pillar leans hardest on.

  The rate now comes from `_statement_fcf`, so both legs share a period by construction.
  The *trigger* deliberately stays operating-outflow-negative rather than moving to
  free-cash-flow-negative, because **capex is discretionary in a way that operating burn is
  not**: a company whose operations fund themselves can stop building and survive, and does
  not have a runway problem to measure. Trigger and rate answer different questions on
  purpose, and a test pins the distinction — the mutation that widens the trigger initially
  survived every other test in the suite.

- **The scoring engine failed its own written acceptance criterion.**
  `docs/scoring-system-design.md` §5.2 specifies that a pre-profit name lands in **Tier
  3–5** and that "no bankrupt-adjacent name outranks a mega-cap compounder". RIVN scored
  **74 / Tier A**, ahead of AAPL 67 and MSFT 73.

  Beyond the runway defect, the `pre_profit_growth` profile weighted the pillar these
  companies fail at **15%** (quality 10 — gross margin 7.5%, operating margin −50.4%) and
  the pillar they ace at **35%** (growth 98). For a pre-profit company "can this become
  profitable" *is* the quality pillar's question, so burying it under growth measured the
  wrong thing. Rebalanced to **Q 0.25 / G 0.25**.

  Measured together: RIVN **74 → 60**, Tier **A → B**, health pillar 82 → 63. Only RIVN
  moved — `cash_runway_q` appears in one profile and the weight change touches only that
  profile, so the other six goldens are byte-identical. The final ordering puts every
  mega-cap above the cash-burner, which is what §5.2 asked for.

  **Two limitations, stated because they do not go away.** First, this re-calibrates curves
  that have **never been validated against forward returns**; §5.2 is a plausibility
  expectation written down in advance, not a market fact, so enforcing it substitutes one
  judgement for another rather than adding evidence. Second — and this matters for the only
  reason `score_history` exists — **the pre-profit series breaks here**: rows recorded
  before today come from the old formula, rows after from the new one, and there is **no
  backfill**. Any future calibration study must treat 2026-08-10 as a discontinuity for
  `pre_profit_growth` and for nothing else.

- **The Portfolio tab made the comparison the Screener refuses to make.** `ScreenerTab`
  carries a prominent warning that composites from different profiles are not one
  measurement — citing "a bank's 70 and a pre-profit growth company's 74", which were the
  live JPM and RIVN values. `PortfolioTab` then rendered those same composites in one
  column, adjacent rows, with no classification and no caveat.

  `store.latest_scores` already returned `classification`; the endpoint was dropping it.
  Each score now shows the profile that produced it, and the table carries the Screener's
  caveat **in the Screener's own wording** — two tabs describing one limitation differently
  is how it got lost in the first place. Not grouped: weights, P&L and concentration are
  portfolio-level figures that need a single list, and the portfolio lists holdings rather
  than ranking them.

---

## 2026-08-10 — currency correctness, scoring guards, a crash, and the tests that were missing

Full three-lens review (finance / engineering / UI) run against every fixture by executing
the code rather than reading it. Backend **153 → 246 passing** plus 3 deliberate xfails;
frontend **22 → 44**. Every behavioural fix below was mutation-tested: reintroducing the
defect fails only the tests that own it.

### Fixed

- **A company's statements and its shares can be in different currencies, and the DCF
  compared them directly.** 0700.HK reports in **CNY** and trades in **HKD** — confirmed
  against Tencent's published FY2024 revenue of RMB 660,257m, which the fixture matches to
  the yuan. Enterprise value was built from statement cash flows and bridged with
  `totalDebt`/`totalCash` (which follow the statements), then divided by shares and
  compared against an HKD price.

  Which `info` field sits on which side of the rate is **measured, not assumed** — yfinance
  documents none of it. Against the quarterly statements, 9988.HK's `totalDebt` and
  `totalCash` come back at **1.0000** and **0.9998** (reporting currency), while 0700.HK's
  `bookValue` and `trailingEps` sit **1.13×** their statement equivalents against a CNYHKD
  spot of 1.1627 (trading currency). `financialCurrency` was not in the `info` whitelist,
  so the app could not previously detect the mismatch at all.

  Corrected at seven boundaries: the DCF equity bridge, the WACC capital-structure weights,
  `resolve_beta`'s peer D/E (each peer on its own rate), `fcf_yield`, `ffo_yield`,
  `comps.ev_implied`, and Altman Z's `equity_liabilities` term. Measured on 0700.HK —
  upside **+30.5% → +44.5%**, fair value **628.44 → 695.47 HKD**, `fcf_yield` score 64 → 68,
  composite **74 → 75**. The unit-free diagnostics (terminal-value share, implied exit
  multiple) are deliberately *not* scaled; the WACC does move (7.69% → 7.66%) because its
  weights were genuinely mixed.

  `fx_rate` returns **None** rather than a fallback constant when unreachable — a stale
  risk-free rate moves a valuation a little, a wrong FX rate rescales all of it. Callers
  then withhold the upside, drop the two market-cap yields, and report Altman Z as `n/a`
  with the reason. Pinned by `-m network` tests so a provider change cannot move every HK
  valuation silently.

- **A dividend cut to zero *improved* the valuation pillar.** yfinance omits
  `dividendYield` for a non-payer rather than sending 0, and `None` reads as *unreported*,
  so the metric left the pillar average instead of scoring its 20-point floor — raising the
  average it left behind. Measured on JPM, changing nothing else: **1.68% → 58, 0.10% → 51,
  zero → 60**. A suspended dividend beat a token one and recovered the whole composite,
  across exactly the profiles where a cut matters most (staples, utilities, REITs, banks,
  insurers). Now scored as zero, with `dividend_yield_assumed_zero` raised only where the
  profile uses the metric. Latent on the fixtures — both are payers — so six direct tests
  pin it.

- **A cost basis of `0` took down the Portfolio tab, unrecoverably.** `unrealized_pnl` and
  `unrealized_pnl_pct` do not share a null condition — zero cost is a real gain and an
  undefined return — and the renderer read the second off the first's guard. The
  `TypeError` fired inside the component's own render, so `ErrorBoundary` unmounted the
  whole tab *including the add/edit form needed to fix the position*: the only way back was
  deleting `app.db`. Reachable by typing `0` in a field whose sibling placeholder suggests
  `0`. The row arithmetic moved out of the endpoint into `main.position_values` so the
  contract could be tested at all — being inline is why the shape shipped unchecked.

- **Two ratios paired figures from different fiscal years.** `_credit_spread` and
  `ratio_analysis`'s interest coverage each called `_latest` twice, independently, and
  `_latest` walks back until it finds *anything*: AAPL resolved EBIT at **2025-09-30** and
  Interest Expense at **2023-09-30**, so the 33.8× coverage on screen — and scored 100 in
  the Health pillar — was a ratio of two different businesses. Both legs are now pinned to
  the newest period reporting both, and that period is displayed. AAPL reads **29.06× in
  2023**; both score 100, so no composite moved and the goldens could never have caught it.

- **The DuPont leverage cap fired on banks.** JPM's equity multiplier is 12.2 because
  deposit-funded intermediation is what a bank is, and the guard cut ROE **78.4 → 70** while
  raising `dupont_leverage_cap_applied` — which reads to a user as an accusation of
  financial engineering. The bank profile already measures capital adequacy properly via
  `equity_assets`. Exempted through `sector_weights.LEVERAGE_IS_STRUCTURAL`: JPM quality
  **75 → 79**, composite **70 → 71**, flag gone. AAPL (multiplier 4.9, ROE 149%) stays
  capped — that is what the guard is for. REITs are deliberately not exempt.

- **A missing debt figure read as a debt-free company.** `(totalDebt or 0)` moved AAPL's
  fair value **143.99 → 147.41** with nothing on screen to say why, while `ratio_analysis`
  correctly returned `None` for the same input. The DCF still computes — refusing to value
  a company over one absent field is worse — but now names the leg it assumed, on the audit
  row.

- **`null >= 0` is `true` in JS**, so an unavailable portfolio P&L rendered green. Same bug
  already fixed once on the DCF upside chip.

### Changed

- **A DCF is no longer presented as an answer for company types it does not fit.** O
  returned a confident **−63.0%** upside off a base cash flow that treats a REIT's property
  acquisitions as maintenance capex; a bank has no `CFO − CapEx` at all. The scoring engine
  already knew — both profiles drop `dcf_upside_pct` — so the card now exports
  `dcf_applicable` and the Financial Models tab states it. The model is still shown; it is
  not shown as a result.
- **The DCF panel names its currency.** An unlabelled `628.44` sat four lines under a header
  reading `Mkt cap 4.33T HKD`, in a different unit. Where a conversion happened the audit
  row states the reporting currency and the rate used.

### Added

- **`tests/test_plausibility.py` — the §5.2 acceptance criteria as assertions.** The design
  doc specifies "RIVN … Tier 3–5" and "no bankrupt-adjacent name outranks a mega-cap
  compounder"; RIVN scores **74 / Tier A**, above MSFT 73, JPM 71, XOM 70 and AAPL 67. The
  profile weights the pillar it fails at 15% (quality 10 — operating margin −50.4%) and the
  one it aces at 35%, and `cash_runway_q` reads 27.3 quarters because it divides cash by
  operating burn and ignores capex.

  Nobody noticed because **`golden_scores.json` had recorded 74/A as the expected value**.
  Snapshot tests catch unintended change and are structurally blind to a wrong answer that
  never changes — the third time that limitation has bitten this codebase. Filed as
  `xfail(strict=True)`: reported in every run, and an error the moment a calibration change
  fixes it. The remedy is a pending decision, recorded in `TODOLIST.md`.

- **Tests for the two modules doing unaudited maths.** `comps.py` (20) — the
  football-field interquartile band, the positive-only peer median, the EV→equity bridge in
  `ev_implied`. `indicators.js` (24) — Wilder's RSI against his own worked dataset, MACD
  alignment and EMA seeding. Both were already correct; neither had a single test.

  Mutation testing then found two holes in the *new* tests: a period-2 RSI case cannot
  distinguish Wilder smoothing from a plain mean (at n=2 the recurrence collapses to
  `(avg + x)/2`), and nothing pinned the EMA's SMA seed until a slope-1 ramp was added,
  where the SMA seed puts MACD's first point at exactly **7.0** against **−4.97** for a
  raw-value seed.

- **`main.position_values`** and 11 tests, pinning which portfolio fields can be null and
  when — the contract whose violation caused the crash above.

---

## 2026-08-07 (c) — GMT+8 clock, 1-minute bars, chart drawings

### Fixed

- **The chart showed UTC, which matched neither the exchange nor the reader.**
  yfinance returns exchange-local timestamps and the backend converts them to
  epochs correctly, but lightweight-charts renders an epoch as UTC and has no
  timezone setting. Measured: AAPL's 09:30 ET open drew as **13:30**, and
  0700.HK's 09:30 HKT open drew as **01:30**. Intraday bars are now shifted to
  **GMT+8** at the chart boundary (`charttime.js`), one clock for every market.
  Daily and weekly bars are date strings and pass through untouched — a US daily
  bar dated 2026-08-06 is that session, not a moment to be shifted.
  Consequence, stated in the UI: a US session runs **21:30 → 03:59** in GMT+8 and
  therefore spans two calendar dates. Inherent to the choice, not a defect.

### Changed

- **1-day charts use 1-minute bars** (was 2m): 390 bars, the finest Yahoo serves
  and its most rate-limit-prone feed. No indicator behaviour changes — day-based
  windows already exceeded a single session at 2m.

### Added

- **Trendline and horizontal-level drawing tools.** lightweight-charts@5.2.0
  ships *no* drawing tools (checked: `TrendLine`/`DrawingTool`/`LineTool` — zero
  matches), only the primitive API, so the renderer, hit-testing, drag handles
  and pixel↔price/time conversion are all custom (`drawingPrimitive.js`).
  Draw, select, drag either endpoint, delete, clear. While a tool is active or a
  handle is held, the chart's own pan/zoom is switched off so the canvas does not
  fight the cursor for the gesture.
  Persisted in SQLite per ticker as **true UTC epochs**, never chart-space time,
  so a drawing survives a change of display timezone. `store.py`, `main.py`
- **The local AI can read your drawings** — through the deterministic engine, not
  by looking at pixels. `drawings.py` computes the price on the line today, its
  slope per day, distance from current price, and how many bars came within 0.5%
  of it; the AI receives those figures and comments on them. Every drawing is
  tagged `drawn_by: "user"` and the context block says in words that these are
  the reader's assertions rather than engine output — without that the model
  would discuss a hand-drawn level as though the system derived it, which is the
  one thing the AI in this app must never do.
  **Unverified end-to-end:** Ollama is still not installed, so the geometry is
  tested offline but no model has ever consumed it. See `TODOLIST.md`.

### Tests

153 offline (was 140): 13 new in `test_drawings.py` covering line extrapolation
beyond the drawn segment, degenerate (vertical) trendlines, touch counting at the
0.5% tolerance, and the user-assertion labelling that keeps a drawn level from
reading as a computed one.

---

## 2026-08-07 (b) — Ticker search, finer chart bars, day-based indicators

### Added

- **Typo-tolerant search box with a clickable result list**, replacing the bare
  text input that sent whatever you typed straight to yfinance — one wrong
  character produced an empty chart and no explanation.
  Two tiers, merged on one relevance scale (`search.py`):
  - **local**: SEC EDGAR's symbol/name list via `obb.equity.search(provider="sec")`
    — 10,398 US symbols, free, no key, cached to disk for 30 days. Fuzzy-matched
    with difflib. **2–3 ms** warm.
  - **remote**: `yf.Search`, the only route to Hong Kong and other non-US names.
  Ranking is tiered so an exact symbol always wins, but a remote hit outranks a
  local *name* match — the measured failure being that "tencent" matched Tencent
  **Music** (a US listing) while 0700.HK, the wanted answer, fell off the list.
  - Latency work: a first pass took **1.85 s** on "microsft" scanning all 10,398
    rows twice. Bucketing fuzzy candidates by first character plus difflib's own
    `real_quick_ratio`/`quick_ratio` prefilters brought the local tier to 2–3 ms.
    The trade-off is stated in the code: a typo *in the first character* is not
    corrected.
  - `enable_fuzzy_query=True` on the Yahoo call, which is **off by default**.
    With it off Yahoo returns nothing at all for `microsft` or `tencnt`; with it
    on both resolve (and `tencnt` -> 0700.HK), and the call gets *faster* —
    1645 ms -> 278 ms, because the no-match path is the slow one. A 3 s timeout
    keeps a slow lookup from stalling a per-keystroke dropdown.
- **One-click chips** under the search box for watchlist/holdings (new
  `/api/portfolio/tickers` — deliberately separate from `/api/portfolio`, which
  prices every position live) and recently viewed tickers (`recents.js`,
  localStorage).

### Changed

- **Chart bars are much finer up to 2 years** (`PERIOD_INTERVALS` in `main.py`).
  Measured against live Yahoo responses, because these are hard API limits:

  | period | was | now | bars |
  |---|---|---|---|
  | 1d | 15m | **2m** | 195 |
  | 5d | 60m | **5m** | 390 |
  | 1mo | 1d | **30m** | 299 |
  | 3mo / 6mo / 1y / 2y | 1d | **1h** | 441 / 868 / 1,749 / 3,487 |
  | 5y / max | 1d | 1d / 1wk | — |

  **5y and max cannot go finer.** Sub-hourly data is capped at the last 60 days
  (3mo at 30m returns *zero* bars) and hourly at 730 days (5y at 1h returns
  *zero* bars). `/history` now falls back to daily rather than rendering an
  empty chart when a name has no intraday history.

- **Indicator windows are now measured in trading days, not bars.** Every period
  in `indicators.js` counted bars, so finer candles silently redefined every
  indicator: on 1h bars "MA50" was a 50-bar ≈ **7.2-trading-day** average, and
  RSI(14) was ≈ 2 days. This already affected the 1d/5d tabs before this change;
  serving intraday bars up to 2y would have spread it across the whole chart.
  `/history` now returns a measured `bars_per_day` — derived from the data, not
  hard-coded, because Hong Kong's session is shorter than New York's — and
  `barsForDays()` converts. MA50 on a 1y hourly chart is now a 350-bar average,
  which is 50 trading days, as the label says.

  Consequence, stated plainly: a window that needs more history than the period
  holds is **not drawn**, because a 50-day average does not exist inside one
  session. On 1d and 5d no moving average is available; on 1mo, MA10 and MA20
  are, MA50 is not. The chart says which and why rather than drawing a
  differently-meaning line under the same label.

### Tests

140 offline (was 119): 21 new covering search ranking, typo tolerance, remote
failure degradation, the period->interval contract (including the two zero-bar
limits above), and `bars_per_day`.

---

## 2026-08-07 — Comparability, beta methodology, forensic checks

Acts on the priorities in [docs/quant-review-2026-08-06.md](docs/quant-review-2026-08-06.md)
§6 and four defects found reading the code afterwards. Every figure below was
measured against the seven committed fixtures with the risk-free rate pinned.

### Fixed

- **The Screener ranked across company types, which is not a defined comparison.**
  `score_batch` sorted every card by `composite_score` regardless of
  classification, and the UI numbered the result 1..N. Two composites from
  different profiles are outputs of different formulas: the profiles score
  different metric sets (RIVN's valuation pillar was one metric, AAPL's four),
  weight the pillars differently (G is 35% for pre-profit and 10% for a bank),
  score some shared metrics on different anchor curves (`RELAXED_ND_EBITDA`),
  and renormalize around whichever pillars had coverage.
  **Measured:** holding every pillar score fixed and changing *only* the weights
  to one common ruler moved three of seven positions — RIVN 2nd→6th, JPM 4th→2nd,
  O 7th→4th. Ranking is now grouped by classification and never crosses one;
  single-member groups are marked `comparable: false` and left unranked.
  On the default seven-ticker input only `technology` has two members, so the
  tab now shows plainly that there was almost no valid ranking in it.
  `main.py:score_batch`, `ScreenerTab.jsx`

- **The classifier read the one field the codebase had already rejected.**
  `classify()` chose `pre_profit_growth` off `info["freeCashflow"]`, which
  yfinance reports annually for some issuers and for a single quarter for others
  (MSFT 16.4B vs 67.0B on the statement, 0.24×). That field decides the
  *profile*, and the profile decides the whole model — a misroute changes every
  metric and weight, not one number. Now takes the period-verified statement FCF
  the rest of the app uses. **No fixture changes classification**; this closes a
  latent hazard rather than a live wrong answer. `sector_weights.py`, `scoring.py`

- **The football field drew the DCF bar from the sensitivity grid's corners.**
  The reference doc (§5.2) specifies the 25th–75th percentile; the code took
  min/max, which is the compounded worst and best case of two assumptions moved
  together. **Measured widths:** AAPL 55.27→26.73, MSFT 132.95→64.00, XOM
  30.26→14.42, O 32.50→14.31, 0700.HK 330.00→149.08. The width was load-bearing:
  0700.HK read `in range` only because of the corners and reads `price below`
  against the interquartile band. `comps.py`

- **The Momentum pillar contained a metric that opposed the other three.**
  `price_vs_200dma`, `range_52w_pos` and `rel_52w_change` all reward price going
  up; `analyst_upside` rewards price being *below* a target, so a rally raised
  three and lowered one and they partly cancelled. It is a valuation signal and
  now sits in the Valuation pillar for every profile. **Measured:** momentum
  moves up to 18 points (0700.HK 42→24), composite −3 to +1, AAPL crosses B→A
  (64→67). `sector_weights.py`

- **`ffo_yield` is not NAREIT FFO** — it is net income plus total D&A, with no
  deduction for gains on property sales. yfinance exposes no gain-on-sale-of-real-
  estate row at all, so the correct figure cannot be built from this source. The
  computation is unchanged (candidate adjustments scored 69–77 against 71 on O,
  ~0.5 composite points) but cards that score it now carry `ffo_yield_is_proxy`
  instead of implying a precision the data cannot support. `scoring.py`

### Changed

- **Peer betas are unlevered before the median and re-levered to the target**,
  per reference doc §1.1.2 — previously a raw levered median, which imported the
  peers' balance sheets along with their business risk:
  `Bu = Bl / (1 + (1-Tc)·D/E)`, then re-levered at the target's own D/E. Needs
  each peer's leverage, so `get_peer_snapshot` now carries `total_debt` (free —
  same `info` call). Degrades in order: re-levered median → levered median (when
  too many peers lack leverage) → neutral 1.0, and the result is held inside the
  same credibility band as a reported beta. `beta_source` records which path ran.
  This is the [Simply Wall St](https://github.com/SimplyWallSt/Company-Analysis-Model)
  spec item with the best evidence-per-hour; their published ERP and 5-year-average
  risk-free rate are **not** done (the free `treasury_rates` call returns only
  1 year — 249 rows, mean 4.27% vs spot 4.63%). Their terminal-growth-equals-10Y
  rule was deliberately **not** adopted: at a 4.6% yield it sets terminal growth
  above long-run nominal GDP, which reference doc §1.1.3 forbids.
  `financial_models.py`, `comps.py`, `data_provider.py`, `main.py`

### Added

- **Forensic checks panel** on the Scorecard: Altman Z, Piotroski F, Sloan
  accrual ratio, net share issuance — the four highest-evidence, lowest-cost
  gaps against GuruFocus, all computable from statements already fetched.
  **Displayed, never scored.** The composite already blends ~40 anchor curves
  that have never been validated against forward returns; four more unvalidated
  curves would move every score without adding evidence. Each row prints its
  published threshold so the reader applies it.
  Applicability is explicit rather than silent: Z returns `n/a` with a reason for
  banks and insurers (no working-capital or sales term) **and for REITs and
  utilities** — the O fixture scores 1.08, Altman's "distress" band, for an
  investment-grade REIT covering interest 2.0×, because Z's sales/assets and
  working-capital terms read an asset-heavy levered balance sheet as failure.
  Altman's Z'' variant covers those and is not implemented. `forensics.py`

### Tests

119 offline (was 94): 21 new in `test_forensics.py`, 5 new unlever/re-lever cases
in `test_valuation.py`. Golden snapshots regenerated — the diff is the record of
the pillar move and is reproduced above.

---

## 2026-08-06 (d) — Readability: ratio quality bars, revenue trend, scorecard verdict

Verified in a real browser over CDP.

### Fixed

- **The revenue trend chart could not show what it was for.** Bars were drawn as
  `revenue / max`, and because a mature company's revenue barely moves, every bar
  came out nearly the same length: AAPL's four years spanned **92.1%–100%** of the
  width — a 7.9pp visual difference for a real 8.6% change. XOM was worse: its
  revenue *fell* (−16.0%, +1.4%, −4.5%) and the bars did not show it at all.
  Truncating the bar axis would have made the difference visible by overstating
  it — a bar's length is its value — so the form changed instead, per the
  dataviz method (trend over time → line; above/below a baseline → diverging bar):
  - **level** is now a line with a near-range baseline, which is legitimate for a
    line and makes the shape readable;
  - **year-on-year change** gets its own zero-centred diverging bars, where the
    real spread lives.
  Every year's absolute revenue is still printed beside its bar, so no value is
  reachable only by hovering.

- **Revenue axis labels pointed at the wrong heights.** First pass placed the
  min/max labels at the top and bottom of the plot box while the line was inset
  by its padding. They are now pinned to the actual plotted y positions.

- **The football field's price marker was drawn inside every row**, so it read as
  a per-row tick rather than one reference. It is now a single rule spanning the
  plot with a value tag, plus a labelled min/mid/max axis and a per-method
  verdict (`price above` / `price below` / `in range`). The verdict wording is
  spelled out because "above" alone did not say *what* was above what.

### Added

- **Quality bars on every ratio.** The Financial Models tab showed raw numbers
  with no indication of whether they were good — the reader had to know from
  memory that a 1.0 current ratio is mediocre. Each ratio now carries the 0–100
  score the scorecard already computes from its calibrated anchor curves, as a
  small colour-banded bar. **No new thresholds were invented** — it reuses the
  engine covered by the golden tests, so the two tabs cannot disagree about the
  same number. Metrics a company's sector profile drops (EV/EBITDA for a bank)
  render a dashed "not scored for this type" bar rather than an empty gap.
  Measured on AAPL: EV/EBITDA 27.2 → **7**, operating margin 32.6% → **100**,
  current ratio 1.0 → **50**. `ModelsTab.jsx`

- **A computed verdict line on the Scorecard**, above the pillars: e.g. "Mixed
  overall at 64/100. Quality is the strongest pillar (82), valuation the weakest
  (22)." Deliberately composed from the pillar scores rather than written by the
  LLM — it must work with Ollama offline, never state a figure the engine did not
  produce, and say the same thing every time. It also names any pillar excluded
  from the composite and flags sub-HIGH confidence.

- `scoreColor` moved into `format.js` and shared, replacing the copy that lived
  in `ScorecardTab` — the Models tab needed the same banding and two definitions
  would have drifted.

### Changed

- The DCF panel title said "5-year FCFF", which stopped being true when the model
  became two-stage. It now reads "two-stage FCFF" and states the actual shape
  from the payload (`5 explicit years + 5-year fade`).
- Opening the Financial Models tab now also fetches `/api/score` (cached, so
  near-free) and therefore records a score-history row. Harmless — history is
  upserted once per ticker per UTC day, so it is the same row the Scorecard tab
  would have written.

### Not done (deliberately)

Two options offered and not chosen: expanding pillar metric detail by default,
and grouping the Scorecard into sections. Both left as-is.

---

## 2026-08-06 (c) — Chart: SEC event markers, volume axis, click-to-open, interactions

Verified in a real browser (headless Chrome driven over CDP), not by inspection.

### Fixed

- **Volume was drawn against the price axis.** The histogram sat on a hidden
  `priceScaleId: 'vol'` overlaid on the price pane, so the only visible axis
  beside 34M–132M volume bars was the *price* scale reading ~310. The data was
  never wrong — verified `auto_adjust=True` does not alter Volume and the API
  serves the true figures (AAPL 2026-07-06 = 53,590,000). Volume now has its own
  pane and its own scale, so it cannot be misread.
  *Known cosmetic limit:* in a pane this short lightweight-charts renders only
  the last-value badge (`49.18M`) and no intermediate ticks. Tried a custom
  price formatter to force them; it changed the badge format but produced no
  ticks either, so it was reverted rather than left as unexplained complexity.
  The value is readable from the badge and the hover legend.

- **News dots flashed and could not be clicked.** The popup was rendered under
  the cursor with `pointer-events: auto`. Hovering it took the mousemove away
  from the chart, the chart reported "cursor left", the popup unmounted, the
  chart got the cursor back, and it re-mounted — forever. Split into a
  `pointer-events: none` hover **preview** that cannot steal the cursor, and a
  **click-to-pin** panel that is the interactive one, with a close button.
  *Verified over CDP:* preview stayed visible on **20/20** jitter samples on the
  marker (the flash test), a click produced a pinned panel with a live link
  (`sec.gov/Archives/edgar/data/320193/...-index.htm`), and the panel survived
  the cursor moving away.

- **Markers only appeared on exact date matches.** A marker was drawn only where
  a bar's date equalled a news date, while the popup used a ±3-day window — so
  the dots and the popup disagreed, and any event on a non-trading day produced
  no dot at all. Events are now snapped to the next trading bar on or after
  their date (clamped to the last bar for events dated after it, e.g. today's
  news against yesterday's close), and both the dot and the lookup use that
  same bar.

### Added

- **SEC filings as chart events**, because the real cause of "only 2 dots" was
  the data, not the chart: yfinance returns 20 news items for AAPL spanning
  **3 distinct dates**, of which 2 fell inside the chart range. The chart was
  already drawing every dot it had. New `provider.get_filings()` (SEC via
  OpenBB — free, no key) adds **278 events across 140 distinct dates back to
  2021** for AAPL. Measured on a 5-year chart: **142 dot-bars, or 62 with
  insider filings off by default**, against 2 before.
  Filing types are mapped to categories (`10-K/10-Q → earnings`,
  `8-K → material`, `3/4/5 → insider`) and everything else — 144, SC 13G/A,
  PX14A6G — is dropped as chart noise.
  **US-only:** EDGAR has no CIK for HK listings, so `.HK` tickers return `[]`
  without paying a round-trip to fail, and the UI says so rather than leaving
  it unexplained.

- **`GET /api/stock/{ticker}/events`** — news + filings merged, with per-category
  counts and a `filings_supported` flag. Deliberately separate from `/news`:
  the AI context keeps consuming headlines only, because 217 Form 4 filings
  would crowd a 7B model's prompt out of the stories that explain a price move.

- **Marker type filter** — one chip per category with its live count; clicking
  toggles it. Insider filings (217 of 278 for AAPL) start **off**. Markers live
  in their own effect, so toggling a filter no longer rebuilds the chart and
  throws away your zoom.

- **Standard chart interactions**: magnet crosshair (snaps to OHLC), Lin/Log/%
  price-scale modes, zoom in/out buttons, Reset, and double-click-to-fit.
  Scroll-to-zoom and drag-to-pan already worked but were undocumented — the
  caption now says so.

### Verified, no change needed

Volume figures themselves: `auto_adjust=True` leaves Volume untouched, and the
served values match the source exactly.

---

## 2026-08-06 (b) — Valuation accuracy: beta, two-stage DCF, credit spread, jurisdiction tax

All measured on the committed fixtures with the risk-free rate pinned to 4.3% so
the before/after is not contaminated by treasury drift.

### Fixed

- **An unvetted beta was the single largest error in the whole valuation.**
  `_wacc()` trusted `info["beta"]` with only an `or 1.0` guard for `None`.
  yfinance reports **0.173 for XOM** — implausible for an oil major — which
  produced WACC 5.11% and made the stock look 33.9% undervalued. Sensitivity
  measured across the plausible range:

  | beta | WACC | fair value | upside |
  |---|---|---|---|
  | 0.17 (reported) | 5.11% | 203.02 | **+33.9%** |
  | 0.60 | 7.13% | 111.23 | −26.6% |
  | 0.90 | 8.53% | 83.69 | −44.8% |
  | 1.10 | 9.47% | 71.41 | −52.9% |

  A **79-point swing in upside from one field.** New `resolve_beta()` keeps a
  reported beta only inside `[0.3, 2.5]`, otherwise substitutes the median of the
  peers' betas, otherwise 1.0. The chosen beta, its source and the raw reported
  value are all returned so the substitution is auditable.
  *Live impact:* XOM upside **+32.8% → −55.7%**, scorecard 75 → **69**
  (`dcf_upside_pct` metric 84 → 0). `backend/financial_models.py`

- **Peer-median beta does not rescue the case that motivated it — and now says
  so.** Measured across sectors, peer betas are usually fine (AAPL 4/4 usable,
  JPM 4/4, KO 4/4, 0700.HK 3/4) but **yfinance's energy betas are broken
  sector-wide**: XOM's peers return CVX 0.488, COP 0.123, SHEL **−0.218**,
  BP **−0.212**. Only one clears the credibility band, and 0.488 is still
  implausible. A median of one observation is not a median, so `MIN_PEER_BETAS = 2`
  makes those cases fall through to the neutral 1.0 default rather than
  laundering a single bad number as "peer evidence".

- **Every company paid an identical cost of debt.** `cost_of_debt = rf + 0.015`
  was flat, so a net-cash issuer and a highly levered REIT were charged the same.
  Measured: all seven fixtures returned `cost_of_debt_after_tax = 0.046`,
  identical to four decimal places. Replaced with a synthetic-rating ladder keyed
  on interest coverage (EBIT / interest). *Live impact:* MSFT (55.4× coverage)
  and XOM (69.4×) pay 0.6%, O (2.04×) pays 3.0% — after-tax Kd 4.13% vs 6.03%.

- **Hong Kong issuers were taxed at the US 21%.** `tax_rate_for()` now resolves
  the statutory rate from the listing currency (HKD 16.5%, USD 21%); yfinance does
  not forward a country field through the `get_fundamentals` whitelist, so currency
  is the proxy. The same rate now feeds NOPAT in the `roic` metric, which had also
  been hardcoded at 21%. *Impact is small and was measured before being
  prioritised:* 0700.HK fair value 490.16 → 488.30 in isolation (0.4%), because tax
  only scales the debt leg and debt is 9% of that capital structure. 0700.HK
  `roic` metric 95 → 96.

- **FCF and net income could still drift apart.** `_statement_fcf()` and the
  net-income lookup scanned for their periods independently — they happened to
  agree on all seven fixtures, but nothing enforced it, which is how the FCF bug
  fixed earlier today arose in the first place. `_statement_fcf()` now returns
  `(period, value)` and `fcf_conversion` pins net income to that exact period via
  the new `_value_at()`, dropping the metric (with a
  `fcf_conversion_period_mismatch` flag) rather than computing a mixed-basis
  ratio. When FCF falls back to `info["freeCashflow"]` there is no verified period,
  so conversion is not computed at all.

### Changed

- **Two-stage DCF: 5 explicit years + 5 fade years, replacing a single 5-year
  fade.** The old shape compressed a durable compounder's entire growth phase into
  five years. *Measured (fair value, upside):* MSFT 179.89 → **319.49**
  (−63.1% → −34.5%), AAPL 112.68 → **143.99** (−63.8% → −53.7%), 0700.HK
  490.16 → **628.44** (+1.8% → +30.5%), O 19.29 → **23.18**.

  It also fixed the terminal-dominance problem as a by-product, which was not the
  stated goal: **terminal value fell from 72–88% of enterprise value to 51–66%**
  (XOM 88% → 51%, AAPL 72% → 55%, MSFT 73% → 60%), because ten explicit years
  capture value the perpetuity used to absorb.

- **DCF trust diagnostics** are now returned and shown in the Financial Models
  tab: `terminal_value_share` (with a >75% warning line, the conventional
  threshold above which the perpetuity rather than the forecast is driving the
  answer) and `implied_exit_ev_ebitda` — what multiple the terminal value assumes
  the market pays in year 10, next to today's multiple. This is the check that
  explains the mega-cap results: AAPL's DCF implies exiting at **8.5×** EBITDA
  against **27.2×** today, MSFT **5.0×** against **18.9×**. The model's negative
  verdict is an assumption of severe multiple compression, now visible instead of
  buried. The panel also surfaces the beta and its source, the credit spread and
  coverage, the tax rate, and the exact FCF period used.

- **Peer discovery falls back to FMP.** `suggest_peers()` keeps the curated map
  first — FMP is measurably worse where a curated list exists (UPS → HWM, GD, MMM)
  — and uses `obb.equity.compare.peers(provider="fmp")` only for the rest.
  Verified working on the free tier and it covers HK. *Impact:* ASML went from no
  peers to `MU, AMD, CSCO, AMAT` and its football field from 2 bars to 3.
  Successes are cached for the process lifetime; failures are not, matching the
  `risk_free_rate` convention. `backend/comps.py`

- `dcf_valuation()` stays a **pure function**. Peer betas are resolved by the
  caller and injected, and `main._peer_betas()` only fetches when the reported
  beta is already implausible — so the common path makes no extra network calls,
  the offline test suite stays offline, and the AI endpoints resolve it inside
  `asyncio.to_thread` rather than on the event loop.

### Score re-basing

Regenerating the golden snapshots moved three of seven fixtures. Every other
score is byte-identical.

| Ticker | Composite | Cause |
|---|---|---|
| XOM | 75 → **69** | beta 0.173 → 1.0; `dcf_upside_pct` 84 → 0 |
| 0700.HK | 73 → **75** | two-stage DCF + HK tax; `dcf_upside_pct` 52 → 82, `roic` 95 → 96 |
| MSFT | 72 → **72** | `dcf_upside_pct` 0 → 7 (valuation 31 → 33) |
| AAPL, JPM, O, RIVN | unchanged | AAPL's upside improved −63.8% → −53.7% but is still past the −40% anchor floor, so the metric stays 0 |

### Verified, no change needed

Checked against the fixtures before assuming a problem existed:
`Interest Expense` is reported **positive** by yfinance, so interest coverage was
never sign-flipped; the four DuPont inputs already resolve to one period on all
seven fixtures; `sharesOutstanding` agrees with `marketCap / price` to within
0.01% (RIVN 0.27%), so per-share fair value was never distorted; and
`revenue_cagr_3y` genuinely spans 3 years on every fixture.

### Still open

- The beta credibility band catches extremes, not a plausible-but-wrong 0.45.
- `EQUITY_RISK_PREMIUM` is still a flat 5% for every market and period, and HK
  issuers still discount at the US 10Y.
- XOM's growth input is 0% (analyst consensus), which does more work in its
  −55.7% result than the beta fix does. Growth sourcing was not in scope here.

---

## 2026-08-06 (a) — Score history, screener, portfolio; scoring FCF fix; async AI

### Fixed

- **The scorecard was still using the FCF source the DCF fix rejected.**
  The 2026-08-02 entry below fixed `dcf_valuation()` to read free cash flow from the
  cash-flow statement, but `scoring.py` was never updated and kept reading
  `info["freeCashflow"]` for **both** `fcf_yield` (valuation pillar) and
  `fcf_conversion` (quality pillar). Re-measured 2026-08-06, the field is still a
  single quarter for some issuers and annual for others: MSFT **0.244×**, GOOGL
  **0.309×**, 0700.HK 0.684×, XOM 0.875×, AAPL 1.091× of the annual statement.
  Worse, `fcf_conversion` divided that possibly-quarterly figure by net income taken
  from the *annual* income statement — a mixed-basis ratio, not a conversion rate.
  `extract_metrics()` now uses `_statement_fcf()` first and falls back to
  `info["freeCashflow"]` only when the statement lacks both legs, raising a new
  `fcf_from_info_unverified_period` flag when it does.
  *Impact* (fixtures, risk-free rate pinned): MSFT `fcf_conversion` metric score
  **7 → 30** and `fcf_yield` **21 → 38**, composite 70 → **72**; 0700.HK composite
  68 → **72** (valuation 46 → 59, quality 80 → 85); XOM 72 → **74**; AAPL 65 → **64**.
  Verified period alignment: `_statement_fcf` and the net-income lookup resolve to
  the same period on all six fixtures. MSFT's resulting 0.501 conversion is real —
  FY26 net income $133.7 B against $67.0 B FCF. `backend/scoring.py`,
  `docs/scoring-system-design.md`

- **Scorecard drew a full-width bar for pillars excluded from the composite.**
  `ScorecardTab` branched only on `data.score === null`, but a pillar can carry a
  real score *and* `insufficient: true`, in which case the composite drops it. A
  pillar could read 97 while contributing nothing. It now renders the score struck
  through with the availability percentage and an explicit "excluded from the
  composite" note. `frontend/src/components/ScorecardTab.jsx`

- **AI replies were not reproducible.** Ollama defaults to `temperature 0.8`, so the
  same question produced a different answer each time — next to a deterministic
  scoring engine. Now `temperature: 0`, fixed `seed`, `top_p: 1`.
  `backend/ai_client.py`

### Added

- **Score history (SQLite).** Every `/api/score/{ticker}` and every screener row
  upserts one row per ticker per UTC day into `backend/data/app.db`, storing the
  composite, all five pillars, tier, confidence, coverage — and **the price at
  scoring time**. That price column is the point: the anchor tables in `scoring.py`
  are hand-set heuristics that `docs/scoring-system-design.md` §5 admits are
  validated for consistency, not forward returns. Nothing was previously recorded,
  so the question could not even be asked. New `GET /api/score/{ticker}/history`
  and a composite-vs-price chart on the Scorecard tab. `backend/store.py`

- **Screener tab** — paste a list, score and rank it with the same deterministic
  engine. `POST /api/score/batch` (max 50 tickers, 4-way concurrent fetch,
  duplicates merged). Per `docs/scoring-system-design.md` §4.3, cards below 60%
  coverage are returned but marked `rankable: false` and excluded from the ordering
  rather than silently taking a place they cannot support. Measured: 6 tickers in
  5.1 s on a cold cache.

- **Portfolio tab** — watchlist and holdings with cost basis, live pricing,
  unrealized P&L, weights, top-1/top-3 concentration and a Herfindahl index. A row
  with 0 shares is a watchlist entry. The latest stored score is joined onto each
  row. `GET/POST/DELETE /api/portfolio*`

- **Bull vs bear debate** — `POST /api/ai/debate/{ticker}` runs three separate
  passes (bull → bear → verdict), each seeing the previous, instead of asking one
  model to hold all three views at once. The verdict is instructed not to split the
  difference and to name what would change its mind.

- **pytest suite, 57 tests, fully offline.** Replaces the hand-run
  `backend/test_scoring.py` assert script. Seven real `get_fundamentals` payloads are
  committed to `backend/tests/fixtures/` (280 KB), chosen to cover technology,
  bank, REIT, energy, pre-profit and HK paths plus MSFT as the FCF regression case.
  Golden snapshots of every card are checked in; regenerate deliberately with
  `UPDATE_GOLDEN=1` and review the diff. Verified the snapshots actually fail when
  the FCF fix is reverted (5 of 7 fixtures break; JPM and O correctly do not use FCF
  metrics). Live provider-contract tests are marked `network` and deselected by
  default. `backend/tests/`, `pytest.ini`

- **CI** — `.github/workflows/ci.yml`: ruff + pytest on Python 3.14, and
  oxlint + vite build for the frontend. `backend/requirements-test.txt` keeps the CI
  install to pytest/yfinance/pandas rather than the full 107-package runtime set.

### Changed

- **All AI endpoints stream.** `ai_client` moved from synchronous `requests` to
  `aiohttp`, and chat, outlook, narrative and debate are now `async def` returning
  newline-delimited JSON. Previously a 60–180 s CPU reply parked a uvicorn threadpool
  worker with a 300 s timeout and the UI showed nothing until it finished. Every
  blocking yfinance call inside an async endpoint goes through `asyncio.to_thread`,
  so moving to `async def` did not relocate the stall onto the event loop.
  Verified: `/api/health` takes 2.22 s alone and 2.23 s while a stream is running
  (the 2 s is the Ollama connect timeout itself), and three concurrent streams
  complete in 3.9 s versus 3.5 s for one. **No new dependency** — `aiohttp` 3.14.3
  was already present via OpenBB, and installing pytest shifted no versions.
  `AIUnavailable` becomes a terminal stream event rather than an HTTP error, because
  by the time the model fails the response headers are long gone.

- **TTL cache (15 min) on `get_fundamentals` and `get_peer_snapshot`.** One scorecard
  page load previously fetched the same ticker twice (`/api/score` plus
  `/api/stock/../comps`) on top of four peer snapshots. `get_quote` is deliberately
  left uncached — a live tracker must stay live. Measured: 2.57 s cold, 0.0000 s
  warm. `TODOLIST.md` deferred this until "the first FMP-backed endpoint entering the
  request path"; batch screening is the equivalent trigger, since it multiplies the
  repeat fetches by N. `backend/data_provider.py`

- `full_analysis()` is now wrapped by `_guard` on `/api/stock/{ticker}/analysis`, so a
  model-layer exception returns 502 with a message instead of a bare 500.

### Known gaps — deliberately not addressed here

- **The bull/bear debate and all streaming output are unverified end-to-end.** Ollama
  is not installed on this machine (`localhost:11434` unreachable), so only the
  offline path was exercised: all four AI endpoints emit a well-formed
  `ai_unavailable` event and the UI renders it. Token-level streaming, debate
  staging and reply quality have never been observed running.
- `_statement_fcf()` and the net-income lookup scan for their periods
  independently. They align on all seven fixtures and the golden tests will catch
  drift, but alignment is not enforced by construction.
- The methodology reference is still hard-truncated at 16,000 characters
  (`ai_client._reference_excerpt`), so the back half of a 1,087-line document never
  reaches the model. Retrieval instead of truncation is still open.
- Portfolio totals sum mixed currencies at face value with no FX conversion; the UI
  warns when holdings span more than one currency.

---

## 2026-08-02 — OpenBB installed; DCF correctness fixes

### Fixed

- **Momentum pillar was silently dropped from every scorecard.**
  `get_fundamentals()` whitelists the `info` fields it forwards, and five momentum
  inputs were missing: `twoHundredDayAverage`, `fiftyTwoWeekLow`, `fiftyTwoWeekHigh`,
  `52WeekChange`, `SandP52WeekChange`. Only 1 of pillar M's 4 metrics survived, so
  `available_fraction` (0.25) fell below the 0.4 threshold, `insufficient` was set, and
  the pillar's **15% weight was redistributed away** on every company.
  The bar shown in the UI came from `analyst_upside` alone and was badly unrepresentative
  — 0700.HK displayed momentum **97** while down 13.6% over 52 weeks.
  Verified all five fields are present for US and HK tickers alike.
  *Impact:* coverage 89–92% → **100%**, zero missing metrics. Composite moved −5 to +3;
  AAPL and KO crossed B → A. `backend/data_provider.py`

- **DCF base free cash flow could be off by 4x.**
  `dcf_valuation()` preferred `info["freeCashflow"]`, which yfinance reports annually for
  some issuers and quarterly for others — MSFT returned 16.4 B against a statement figure
  of 67.0 B (0.24x), rescaling the whole valuation. The statement is now the primary
  source and `info["freeCashflow"]` the fallback, recorded in `assumptions.fcf_source`.
  Added `_statement_fcf()`, which takes both legs from the **same** period; the previous
  fallback used two independent `_latest()` lookups and could pair this year's operating
  cash flow with last year's CapEx.
  *Impact:* MSFT fair value 37.57 → **166.50**; NVDA 25.84 → **50.59**;
  0700.HK 341.07 → **462.05** (upside −28.2% → −2.8%, scorecard 68 → 71).
  `backend/financial_models.py`

- **Risk-free rate was a hardcoded 4.3%**, ~38 bp stale against the actual US 10Y (4.68%).
  `_wacc()` now calls `data_provider.risk_free_rate()`, and reports the rate used in
  `assumptions.risk_free_rate`. `backend/financial_models.py`, `backend/data_provider.py`

- Provider interface was documented as "four methods" in both the module docstring and the
  README; it is **five** — omitting `get_peer_snapshot` would break the comps table and
  football field. `backend/data_provider.py`, `README.md`

### Added

- `risk_free_rate(fallback)` in `backend/data_provider.py` — US 10Y treasury yield via
  `obb.fixedincome.government.treasury_rates(provider="federal_reserve")`. Free, no API
  key. Cached once per calendar day; **failures are not cached**, so it resumes live rates
  as soon as connectivity returns. Sanity band `0 < rate < 0.25` guards against a provider
  switching to percent units. The `openbb` import is deferred into the function: backend
  startup stays at 1.3 s and only the first request that runs a DCF pays the ~4 s import.

- `backend/requirements.lock.txt` — 43 packages, the pre-OpenBB state. This is the rollback
  target if the `fastapi`/`uvicorn` downgrade ever causes trouble.
- `backend/requirements.post-openbb.txt` — 107 packages, the current state.

### Changed

- **OpenBB Platform 4.7.2 installed** into the existing venv: 41 MB, 66 wheels, no sdists
  (so no C compiler needed), on Python 3.14.6. Downgraded `fastapi` 0.141.1 → 0.136.3 and
  `uvicorn` 0.52.0 → 0.40.0; `pandas`, `numpy`, `pydantic` and `yfinance` were untouched.
  Verified after install: `pip check` clean, backend serves `/api/health` and
  `/api/score/AAPL`, `wacc_override` still honoured, football field intact, zero 500s.

- README corrected on three points that were **factually wrong**:
  the install size (~2 GB → 41 MB), the claim that OpenBB fixes sparse historical news
  (false on the free tier), and the claim that value turnover "becomes available with
  OpenBB" (unverified, now stated as not implemented).

### Investigated — no code change

- **Historical news is paywalled on both free tiers.** Verified by raw HTTP against each
  vendor, bypassing OpenBB: Tiingo `403 {"detail":"You do not have permission to access
  the News API"}`, FMP `402 Restricted Endpoint: not available under your current
  subscription`. Both keys are valid — the same keys return `200` on
  `tiingo/daily/AAPL/prices` and `fmp/stable/stock-peers`. **403/402 is a plan-entitlement
  refusal, not an authentication failure**; a bad key returns 401, which never occurred.
  Matches both vendors' published pricing (Tiingo News ✗ on free; FMP news starts at
  Starter $22/mo).

- **Caching layer deliberately deferred.** Installing OpenBB consumes no API quota, so it
  was not a prerequisite, and a cache actively obstructs integration debugging — you edit
  provider code, refresh, and get stale results. The correct trigger is the first
  FMP-backed endpoint going into the request path. See `TODOLIST.md`.

---

## 2026-07-31 — Initial platform

- FastAPI backend + React (Vite) frontend, three tabs: Tracker, Financial Models, Scorecard.
- yfinance data adapter behind a five-method `provider` interface.
- 5-year FCFF DCF with sensitivity grid, ratio analysis, DuPont decomposition, peer comps,
  football-field valuation ranges.
- Deterministic 0–100 scoring engine with a sector weight library and coverage-aware
  pillar weighting.
- Optional local AI (Ollama) for chat, outlook and scorecard narration — degrades to an
  "AI offline" state when absent.
