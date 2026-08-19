"""The fixtures are a contract, and this is what holds them to it.

Every other test in this suite runs against `fixtures/*.json` instead of the
network, which is what makes the suite runnable in CI. That only works while the
fixtures still look like what `get_fundamentals` actually returns.

The regression that prompted this: `regularMarketTime` and
`exchangeDataDelayedBy` were added to the forwarded `info` fields on 2026-08-14,
four days after the fixtures were captured. Nothing failed. Every fixture-based
test simply read `None` for both — indistinguishable from a vendor that did not
report them — and the drift was found by auditing the file, not by running it.

The failure mode is quiet by construction, so the guard has to be explicit.
"""
from __future__ import annotations

import json

import pytest

from conftest import FIXTURES

from backend import data_provider
from backend.data_provider import INFO_KEYS

# What `get_fundamentals` returns at the top level.
TOP_LEVEL_KEYS = {"ticker", "info", "estimates", "income_statement",
                  "balance_sheet", "cash_flow"}

# What `get_peer_snapshot` returns. There is no *fixture* for a snapshot — it is
# built from a live `info` call rather than captured — so this set is the only
# complete record of its shape. (`test_valuation.py`'s `_peer()` helper records
# a deliberate 3-key subset, which is a different thing: it exists to prove the
# unlever path degrades, not to pin the contract.)
PEER_SNAPSHOT_KEYS = {
    "ticker", "name", "market_cap", "currency", "financial_currency",
    "sector", "industry", "beta", "total_debt", "pe_trailing", "pe_forward",
    "price_to_book", "ev_to_ebitda", "ev_to_revenue", "peg_ratio",
    "operating_margin", "revenue_growth",
}


@pytest.fixture(params=sorted(FIXTURES), ids=sorted(FIXTURES))
def fixture_payload(request):
    return json.loads(FIXTURES[request.param].read_text(encoding="utf-8"))


def test_fixture_info_keys_match_the_provider_contract(fixture_payload):
    """Exact equality, not a subset either way.

    A missing key means the fixture predates a field the app now forwards, and
    every test reading it is quietly exercising the absent case. An extra key
    means the fixture carries a field the provider stopped forwarding, so the
    tests are passing on data production can no longer produce.
    """
    assert set(fixture_payload["info"]) == set(INFO_KEYS)


def test_fixture_has_the_top_level_shape_the_model_layer_expects(fixture_payload):
    assert set(fixture_payload) == TOP_LEVEL_KEYS


class _StubTicker:
    """A complete `info` — every Yahoo key `get_peer_snapshot` reads.

    Completeness is the point. Every field in the snapshot is `info.get(...)`,
    so a key-set assertion alone passes even against `info = {}`: all 17 keys
    appear, holding `None`. Only a stub that supplies *every* source key lets
    the test below assert no value came back `None`, which is what actually
    catches a mistyped Yahoo key (`trailingPe` for `trailingPE`).

    `shortName` is deliberately absent: `name` falls back to it, and the
    fallback gets its own test rather than being masked here.
    """

    INFO = {
        "longName": "Stub Retail REIT", "marketCap": 5.9e10, "currency": "USD",
        "financialCurrency": "USD", "sector": "Real Estate",
        "industry": "REIT - Retail", "beta": 0.75, "totalDebt": 2.6e10,
        "trailingPE": 55.0, "forwardPE": 40.0, "priceToBook": 1.3,
        "enterpriseToEbitda": 17.0, "enterpriseToRevenue": 12.0,
        "pegRatio": 3.0, "operatingMargins": 0.28, "revenueGrowth": 0.06,
    }

    def __init__(self, ticker, info=None):
        self.info = dict(self.INFO if info is None else info)


def _snapshot_from(monkeypatch, info=None) -> dict:
    """`get_peer_snapshot` against a stubbed `info`, with the TTL cache bypassed."""
    monkeypatch.setattr(data_provider.yf, "Ticker",
                        lambda t: _StubTicker(t, info))
    try:
        return data_provider.YFinanceProvider().get_peer_snapshot("STUB")
    finally:
        # The snapshot is TTL-cached under ("get_peer_snapshot", "STUB", ...);
        # leaving it would serve this stub to any later test using that ticker.
        data_provider.clear_cache()


def test_peer_snapshot_carries_every_field_its_consumers_read(monkeypatch):
    """The same quiet-drift guard as above, for the other provider output.

    `get_peer_snapshot` has no fixture, because it is assembled from a live
    `info` call rather than captured. So a field dropped from it fails the way
    the `INFO_KEYS` drift did — invisibly.

    `sector` and `industry` are the two that would go unnoticed longest. They
    are read by peer *discovery* — `comps._screener_peers` since 2026-08-19,
    which is what this guard was captured a day ahead of. Losing `industry`
    degrades a screen to "no peers found", which is indistinguishable from a
    genuinely empty screen.

    Offline by construction — `yf` is stubbed, so this runs in CI rather than
    behind `-m network`, which is where such drift would otherwise hide.
    """
    snap = _snapshot_from(monkeypatch)

    assert set(snap) == PEER_SNAPSHOT_KEYS
    # The half the key-set assertion cannot do. Every value is `info.get(...)`,
    # so a mistyped Yahoo key yields None while the key set stays perfect.
    assert [k for k, v in snap.items() if v is None] == []
    assert (snap["sector"], snap["industry"]) == ("Real Estate", "REIT - Retail")


def test_peer_snapshot_name_falls_back_to_short_name(monkeypatch):
    """`name` is `longName or shortName`, and only the second branch is unused
    on the fixtures — so it is the one that can rot unnoticed."""
    info = {**_StubTicker.INFO, "shortName": "Stub Co"}
    del info["longName"]
    assert _snapshot_from(monkeypatch, info)["name"] == "Stub Co"


# ── what each fixture is *for* ───────────────────────────────────────


def test_the_fixture_set_still_covers_a_non_usd_reporting_dcf():
    """`0002_HK` is the only fixture that can exercise a non-USD discount rate.

    Six of the eight report USD. `0700_HK` reports CNY but is the one segment
    this platform deliberately does not attempt (see WACC comment in
    `financial_models`), which leaves CLP carrying the HKD case alone.

    The guard is here because the obvious replacements do not work and the
    failure would be silent. `classify` sends `sector == "real estate"` to
    `real_estate_reit` and `"bank" in industry` to `financials_bank`, and
    `dcf_applies` is False for both — so swapping CLP for SHK Properties or BOC
    Hong Kong, both HKD reporters, would leave every test passing while nothing
    discounted a Hong Kong dollar again.
    """
    from backend import sector_weights, statements

    payload = json.loads(FIXTURES["0002_HK"].read_text(encoding="utf-8"))
    info = payload["info"]
    assert info["financialCurrency"] == "HKD"

    fcf = statements.statement_fcf(payload["cash_flow"])
    classification = sector_weights.classify(info, fcf[1] if fcf else None)
    assert sector_weights.dcf_applies(classification), classification
    # A DCF also needs positive free cash flow to run at all — 0066.HK (MTR) is
    # HKD-reporting and DCF-eligible by classification, and still fails here.
    assert fcf is not None and fcf[1] > 0
