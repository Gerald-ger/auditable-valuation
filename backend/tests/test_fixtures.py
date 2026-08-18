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

from backend.data_provider import INFO_KEYS

# What `get_fundamentals` returns at the top level.
TOP_LEVEL_KEYS = {"ticker", "info", "estimates", "income_statement",
                  "balance_sheet", "cash_flow"}


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
