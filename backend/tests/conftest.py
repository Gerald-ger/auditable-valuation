"""Shared test fixtures.

Everything here is offline. The JSON files in tests/fixtures/ are real
get_fundamentals output captured by capture_fixtures.py, so the scoring tests
exercise real-world shapes (missing rows, negative equity, non-USD listings)
without a network call — which is what makes them runnable in CI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# file stem -> ticker as the app spells it
FIXTURES = {p.stem: p for p in sorted(FIXTURE_DIR.glob("*.json"))}


def load_fundamentals(stem: str) -> dict:
    """Fresh copy per call — tests must not leak mutations into each other."""
    return json.loads(FIXTURES[stem].read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def pinned_risk_free_rate(monkeypatch):
    """Pin the CAPM risk-free rate for every test.

    score_company runs dcf_valuation for profiles whose valuation pillar
    includes dcf_upside_pct, and _wacc() pulls the *live* US 10Y treasury yield
    through OpenBB. Left alone, every golden score would drift with the treasury
    market and this 'offline' suite would quietly require a network call.
    """
    import financial_models
    monkeypatch.setattr(financial_models, "risk_free_rate",
                        lambda fallback: financial_models.RISK_FREE_RATE)


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
    import store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init()
    return store
