"""Shared test fixtures.

Everything here is offline. The JSON files in tests/fixtures/ are real
get_fundamentals output captured by capture_fixtures.py, so the scoring tests
exercise real-world shapes (missing rows, negative equity, non-USD listings)
without a network call — which is what makes them runnable in CI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# file stem -> ticker as the app spells it
FIXTURES = {p.stem: p for p in sorted(FIXTURE_DIR.glob("*.json"))}


def load_fundamentals(stem: str) -> dict:
    """Fresh copy per call — tests must not leak mutations into each other."""
    return json.loads(FIXTURES[stem].read_text(encoding="utf-8"))


BARS_DIR = FIXTURE_DIR / "bars"

# Which index each fixture's relative strength and beta are measured against.
# Mirrors data_provider.home_index rather than importing it, so a change to that
# rule has to be made deliberately here too — these fixtures were captured
# against a specific index and silently re-pointing them would compare a
# company's returns to an index its stored bars were never aligned with.
HOME_INDEX = {"0700_HK": "_HSI", "0002_HK": "_HSI"}


def load_bars(stem: str) -> list[dict]:
    """Weekly closes for one fixture, oldest first."""
    return json.loads((BARS_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def load_market_bars(stem: str) -> tuple[list[dict], list[dict]]:
    """(company bars, home-index bars) shaped for `market_bars=`.

    Injected the same way peers are, and for the same reason: `dcf_valuation`
    and `score_company` are pure functions of their arguments, so the tests hand
    them a series instead of letting anything reach for the network.
    """
    return load_bars(stem), load_bars(HOME_INDEX.get(stem, "_GSPC"))


# China 10-year government yield. A round test constant, not a market quote, for
# the same reason TEST_CNY_HKD below is one: what these tests pin is that a CNY
# filer is discounted at a Chinese rate, not what that rate was on a given day.
# ChinaBond published 1.6864% on 2026-08-19. Net of the vendored CNY default
# spread of 0.60% this leaves a round 1.10% risk-free.
TEST_CGB_10Y = 0.017


@pytest.fixture(autouse=True)
def pinned_risk_free_rate(monkeypatch):
    """Pin the CAPM risk-free rate for every test.

    score_company runs dcf_valuation for profiles whose valuation pillar
    includes dcf_upside_pct, and _wacc() pulls the *live* US 10Y treasury yield
    through OpenBB. Left alone, every golden score would drift with the treasury
    market and this 'offline' suite would quietly require a network call.

    Pins `_us_treasury_10y`, the fetch, rather than `risk_free_rate`, the
    function that decides what to do per currency. Stubbing the outer function
    is the trap docs/currency-consistent-discounting.md predicted before the
    currency branch existed: it would satisfy every caller while guaranteeing
    that no test ever executed the branch, and the suite would stay green
    whether that branch worked or not. Patched on `data_provider` because
    `risk_free_rate` resolves the name from its own module globals at call time
    — `financial_models` imports only `risk_free_rate` itself.
    """
    from backend import data_provider, financial_models
    monkeypatch.setattr(data_provider, "_us_treasury_10y",
                        lambda: financial_models.RISK_FREE_RATE)
    # `_cgb_10y` too, and in the same fixture rather than a second one, because
    # the hazard is identical: `0700_HK` reports CNY, so any test running a DCF
    # over it would reach ChinaBond over the network from inside the offline
    # suite.
    #
    # Pinned to a *rate* rather than to `None`. `None` would have been quieter —
    # every currency would degrade to the US proxy and no golden would move —
    # and that is exactly why it is wrong: the goldens would go on pinning the
    # ChinaBond-is-down path while production ran the other one, which is the
    # trap docs/currency-consistent-discounting.md warned about, one level down.
    #
    # `(rate, live)` rather than a bare rate since 2026-08-20: the second element
    # says whether it came from today's fetch or from the store, and a test that
    # returned only the number would not exercise the branch that labels it.
    monkeypatch.setattr(data_provider, "_cgb_10y", lambda: (TEST_CGB_10Y, True))


@pytest.fixture(autouse=True)
def isolated_cgb_store(tmp_path, monkeypatch):
    """Point the CGB fallback store at a throwaway path, for every test.

    `_cgb_10y` writes a good reading to disk so the next run has something to
    fall back on. The tests that drive the real parse stub `urlopen` rather than
    the function, so they reach that write — and without this they would leave a
    file in `backend/data/`, and, worse, a *later* test would find it and pass on
    a fallback instead of on the path it meant to exercise.

    Autouse and unconditional, the same reasoning as `temp_db`: isolation that
    each test has to remember to ask for is isolation that will be forgotten.
    """
    from backend import data_provider
    monkeypatch.setattr(data_provider, "CGB_STORE_PATH", tmp_path / "cgb_10y.json")


# CNY -> HKD. A round test constant, not a market quote: the point is that the
# 0700.HK fixture reports in CNY and trades in HKD, not what the pair was worth
# on any given day. Spot was 1.1627 when the split was measured (2026-08-10).
TEST_CNY_HKD = 1.10


@pytest.fixture(autouse=True)
def pinned_fx_rate(monkeypatch):
    """Pin cross-currency conversion for every test.

    Statements are denominated in `financialCurrency` and shares trade in
    `currency`; 0700.HK reports CNY and trades HKD, so its DCF, its market-cap
    yields and its Altman Z all convert between the two. Left live, this
    'offline' suite would need a network call per run and every 0700.HK golden
    would drift with the currency market — exactly the reason the risk-free rate
    is pinned above.

    Patched on `financial_models` because that module does `from
    backend.data_provider import fx_rate`, binding the name at import; every
    other caller reaches it through `financial_models.statement_to_market_fx`.
    """
    from backend import financial_models
    rates = {("CNY", "HKD"): TEST_CNY_HKD}

    def fake_fx_rate(from_ccy, to_ccy):
        if not from_ccy or not to_ccy:
            return None
        return 1.0 if from_ccy == to_ccy else rates.get((from_ccy, to_ccy))

    monkeypatch.setattr(financial_models, "fx_rate", fake_fx_rate)


@pytest.fixture(autouse=True)
def no_live_screener(monkeypatch):
    """Keep the third peer tier off the network in the default suite.

    `suggest_peers` falls through curated -> FMP -> screener, so a test that
    reaches it with an uncurated ticker and an `_fmp_peers` stub returning `[]`
    would call live yfinance twice — once for the target's own snapshot, once
    for the screen — inside a suite that is meant to be offline. Nothing does
    that today; the point is that nothing can start doing it by accident.

    Stubbing the whole function rather than `yf.screen` is deliberate: the
    snapshot fetch happens first, so patching only the screen call would still
    leak. `test_comps.py` holds a reference to the real function, captured at
    import, for the tests that exercise it.
    """
    from backend import comps
    monkeypatch.setattr(comps, "_screener_peers", lambda t: [])


@pytest.fixture
def fundamentals():
    return load_fundamentals


@pytest.fixture
def empty_fundamentals():
    return {"ticker": "NULL", "info": {}, "estimates": {},
            "income_statement": {}, "balance_sheet": {}, "cash_flow": {}}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point store at a throwaway database so tests never touch backend/data."""
    from backend import store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init()
    return store
