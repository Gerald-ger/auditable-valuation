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
HOME_INDEX = {"0700_HK": "_HSI"}


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


@pytest.fixture(autouse=True)
def pinned_risk_free_rate(monkeypatch):
    """Pin the CAPM risk-free rate for every test.

    score_company runs dcf_valuation for profiles whose valuation pillar
    includes dcf_upside_pct, and _wacc() pulls the *live* US 10Y treasury yield
    through OpenBB. Left alone, every golden score would drift with the treasury
    market and this 'offline' suite would quietly require a network call.
    """
    from backend import financial_models
    monkeypatch.setattr(financial_models, "risk_free_rate",
                        lambda fallback: financial_models.RISK_FREE_RATE)


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
