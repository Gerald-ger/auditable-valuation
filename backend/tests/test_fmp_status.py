"""Whether the FMP key is configured, and whether it is working.

Until 2026-08-28 neither question had an answer anywhere in the app. `_fmp_peers`
caught every exception and returned `[]`, so six different situations produced
the same silence: no key, a key at the wrong path, malformed JSON, a mistyped
field name, a key that is simply wrong, and an exhausted free quota. Setting the
key means hand-editing a JSON file at a path most people have never opened, and
there was no way to find out whether it had worked.

The half that needs care is the sixth situation's opposite: a ticker that
genuinely has no peers. FMP answers that with `EmptyDataError`, and reporting it
as a failure would tell someone their working key is broken — worse than the
silence it replaced. That is what `test_a_ticker_with_no_peers_is_the_key_working`
pins.
"""
from __future__ import annotations

import json
import sys
import types

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from backend import comps


@pytest.fixture(autouse=True)
def clean_fmp_state(monkeypatch, tmp_path):
    """No inherited key, no inherited verdict, no inherited cache."""
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr(comps, "USER_SETTINGS_PATH", str(tmp_path / "user_settings.json"))
    monkeypatch.setattr(comps, "_FMP_LAST_CALL", None)
    monkeypatch.setattr(comps, "_FMP_PEER_CACHE", {})


def _write_settings(monkeypatch, tmp_path, body: str):
    p = tmp_path / "user_settings.json"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setattr(comps, "USER_SETTINGS_PATH", str(p))


def _fake_openbb(monkeypatch, *, results=None, raises=None):
    """Stand in for the `from openbb import obb` inside `_fmp_peers`.

    A fake rather than a live call on purpose: the point of these tests is what
    the app reports about FMP, and reaching FMP to find out would spend the
    free-tier quota this feature exists to make visible.
    """
    def peers(symbol, provider):
        if raises is not None:
            raise raises
        return types.SimpleNamespace(results=results or [])

    obb = types.SimpleNamespace(
        equity=types.SimpleNamespace(compare=types.SimpleNamespace(peers=peers)))
    monkeypatch.setitem(sys.modules, "openbb", types.SimpleNamespace(obb=obb))


# ── configured: the setup-time question ─────────────────────────────────────

def test_no_key_anywhere_reports_not_configured():
    assert comps.fmp_status() == {"configured": False, "last_call": None}


def test_a_key_in_the_environment_is_found():
    """`FMP_API_KEY`, not `OPENBB_FMP_API_KEY`.

    OpenBB lower-cases the variable name and matches it against its credential
    fields, so the prefixed spelling lands under `openbb_fmp_api_key` and is not
    the FMP credential at all. Reading the same name here keeps this honest
    about what OpenBB will actually use.
    """
    import os
    os.environ["FMP_API_KEY"] = "env-key"
    try:
        assert comps.fmp_status()["configured"] is True
    finally:
        del os.environ["FMP_API_KEY"]


def test_a_key_in_the_settings_file_is_found(monkeypatch, tmp_path):
    _write_settings(monkeypatch, tmp_path,
                    json.dumps({"credentials": {"fmp_api_key": "file-key"}}))
    assert comps.fmp_status()["configured"] is True


def test_the_field_name_has_to_be_right(monkeypatch, tmp_path):
    """One of the failure modes this exists to make visible.

    `fmp_apikey` is a plausible mistake and produces a file OpenBB reads happily
    and gets nothing from. Before this, the result was peers quietly falling to
    the keyless tier with no way to tell.
    """
    _write_settings(monkeypatch, tmp_path,
                    json.dumps({"credentials": {"fmp_apikey": "wrong-field"}}))
    assert comps.fmp_status()["configured"] is False


def test_a_malformed_settings_file_reports_not_configured(monkeypatch, tmp_path):
    """False is the useful answer: OpenBB would get no key out of it either."""
    _write_settings(monkeypatch, tmp_path, "{ this is not json")
    assert comps.fmp_status()["configured"] is False


def test_the_status_never_carries_the_key():
    """The endpoint reporting this has no authentication."""
    import os
    secret = "sk-THIS-MUST-NOT-APPEAR-ANYWHERE"
    os.environ["FMP_API_KEY"] = secret
    try:
        assert secret not in json.dumps(comps.fmp_status())
    finally:
        del os.environ["FMP_API_KEY"]


# ── last_call: the runtime question ─────────────────────────────────────────

def test_nothing_is_claimed_before_a_call_has_been_made():
    assert comps.fmp_status()["last_call"] is None


def test_a_successful_lookup_is_recorded(monkeypatch):
    _fake_openbb(monkeypatch, results=[types.SimpleNamespace(symbol="MSFT"),
                                       types.SimpleNamespace(symbol="GOOGL")])
    assert comps._fmp_peers("AAPL") == ["MSFT", "GOOGL"]
    assert comps.fmp_status()["last_call"] == "ok"


def test_a_ticker_with_no_peers_is_the_key_working(monkeypatch):
    """The one that would be easy to get backwards, and damaging if it were.

    `EmptyDataError` means the call reached FMP and FMP answered. Recording it
    as a failure would tell someone with a perfectly good key that their key is
    broken — a false alarm is worse than the silence this replaced, because it
    sends them to re-do a setup that was already correct.
    """
    _fake_openbb(monkeypatch, raises=EmptyDataError("no peers"))
    assert comps._fmp_peers("OBSCURE") == []
    assert comps.fmp_status()["last_call"] == "ok"


def test_a_rejected_key_or_spent_quota_is_recorded_as_failed(monkeypatch):
    _fake_openbb(monkeypatch, raises=RuntimeError("Invalid API KEY"))
    assert comps._fmp_peers("AAPL") == []
    assert comps.fmp_status()["last_call"] == "failed"


def test_the_recorded_failure_carries_no_message(monkeypatch):
    """FMP takes the key as an `?apikey=` query parameter, so a raised URL can
    carry it. Only the verdict is kept, never the exception text."""
    leak = "https://financialmodelingprep.com/api/v3/x?apikey=sk-LEAKED"
    _fake_openbb(monkeypatch, raises=RuntimeError(leak))
    comps._fmp_peers("AAPL")
    assert "sk-LEAKED" not in json.dumps(comps.fmp_status())


def test_a_cache_hit_does_not_claim_a_fresh_verdict(monkeypatch):
    """It did not call FMP, so it has no news about FMP.

    Overwriting the verdict here would make a stale 'ok' look current every time
    a cached ticker was viewed, which is the failure this feature is meant to
    surface rather than manufacture.
    """
    monkeypatch.setattr(comps, "_FMP_PEER_CACHE", {"AAPL": ["MSFT"]})
    monkeypatch.setattr(comps, "_FMP_LAST_CALL", "failed")
    assert comps._fmp_peers("AAPL") == ["MSFT"]
    assert comps.fmp_status()["last_call"] == "failed"


def test_demo_mode_never_reaches_fmp(monkeypatch):
    """`suggest_peers` returns before the FMP tier under DEMO_MODE, so a demo
    visitor's `last_call` stays None and the banner that reads it never fires —
    without demo mode needing a special case here."""
    monkeypatch.setattr(comps, "DEMO_MODE", True)
    _fake_openbb(monkeypatch, raises=RuntimeError("must not be reached"))
    assert comps.suggest_peers("AAPL") == []
    assert comps.fmp_status()["last_call"] is None
