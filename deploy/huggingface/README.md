---
title: Auditable Valuation
emoji: 📊
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: agpl-3.0
short_description: Two-stage FCFF DCF, trading comps and a 0-100 scorecard
---

# Auditable Valuation — live demo

Investment-banking valuation models as auditable code. A two-stage FCFF DCF where every
assumption carries the source it came from, trading comps, and a deterministic 0–100
scorecard built from 28 anchor curves across five sector-weighted pillars.

**Source, and the reasoning behind every number:**
[github.com/Gerald-ger/auditable-valuation](https://github.com/Gerald-ger/auditable-valuation)

## What you are looking at

This runs with `DEMO_MODE=1`. Eight companies' financial statements and prices, captured
between **2026-08-10** and **2026-08-19** and committed to the repository, answer every
request. No API key, no network call to any data vendor, no live prices.

Nothing here is fabricated and nothing is live, so every number is reproducible — these are
the same bytes the test suite pins its golden scores to.

| | |
|---|---|
| Works in full | **Scorecard**, **Financial Models**, **Portfolio** |
| Withheld | **Tracker**, **Screener** |

Tracker and Screener are refused rather than drawn with holes in them: the capture carries
weekly closes with no OHLCV, no news, no filings, and eight individual sectors rather than a
peer group to screen against. A stripped chart reads as a broken chart.

## Two things to know

**State here is shared.** The app is local-first and has no notion of a session, so the
Portfolio tab writes to one database that every visitor of this Space sees. It is wiped
whenever the Space restarts. Run it locally if you want a portfolio that is yours.

**Decision support, not financial advice.** The scorecard says so on screen, and it is not a
prediction. The score is a heuristic whose anchor curves have never been validated against
forward returns, and the LLM analyst is disabled here — it needs a local Ollama.
