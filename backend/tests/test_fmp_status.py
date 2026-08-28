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
from pathlib import Path

import pytest

from backend import comps


class EmptyDataError(Exception):
    """Stand-in for OpenBB's, injected below with the fake `openbb` module.

    Not the real class, and deliberately not imported: `requirements-test.txt`
    does not install OpenBB, and a module-scope import of it here aborts
    collection for the whole file in CI. `_fmp_peers` resolves the name through
    `sys.modules` at call time, so a fake registered there is the class its
    `except` clause actually matches -- which is what these tests are about.
    """


# Captured at import, because the autouse fixture below redirects the module's
# copy at every test. The drift test needs the value the app actually ships.
REAL_SETTINGS_PATH = comps.USER_SETTINGS_PATH


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
    # A leaf already in sys.modules short-circuits the import machinery before it
    # touches the parent packages, so `openbb_core` itself need not exist.
    monkeypatch.setitem(sys.modules, "openbb_core.provider.utils.errors",
                        types.SimpleNamespace(EmptyDataError=EmptyDataError))


# ── configured: the setup-time question ─────────────────────────────────────

def test_the_settings_path_still_matches_openbbs_own():
    """The drift test for computing that path instead of importing it.

    `comps` cannot import `openbb_core.app.constants` -- doing so took five test
    modules out of CI on 2026-08-28 -- so it derives the same path itself. This
    pins the two together wherever OpenBB is installed, and skips where it is
    not, which is exactly the CI job that cannot answer the question anyway.
    """
    constants = pytest.importorskip("openbb_core.app.constants")
    assert Path(REAL_SETTINGS_PATH) == Path(constants.USER_SETTINGS_PATH)


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


# ── saving: writing a file this app does not own ────────────────────────────

def _settings_at(monkeypatch, tmp_path, data: dict | str):
    p = tmp_path / "user_settings.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(comps, "USER_SETTINGS_PATH", p)
    return p


def test_saving_a_key_leaves_every_other_setting_alone(monkeypatch, tmp_path):
    """The test this feature most needs, and the reason it is read-modify-write.

    Measured on the development machine before any of this was written: that file
    holds a `tiingo_token` beside the FMP key, plus `preferences` and `defaults`.
    A convenience feature that silently drops an unrelated provider's credential
    would be a far worse bug than the one it set out to fix.
    """
    p = _settings_at(monkeypatch, tmp_path, {
        "credentials": {"tiingo_token": "keep-me", "fmp_api_key": "old"},
        "preferences": {"output_type": "dataframe"},
        "defaults": {"commands": {}},
    })
    _fake_openbb(monkeypatch, results=[types.SimpleNamespace(symbol="MSFT")])

    comps.save_fmp_key("new-key")

    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["credentials"]["fmp_api_key"] == "new-key"
    assert after["credentials"]["tiingo_token"] == "keep-me", "took another provider's key"
    assert after["preferences"] == {"output_type": "dataframe"}
    assert after["defaults"] == {"commands": {}}


def test_a_file_that_cannot_be_parsed_is_refused_rather_than_replaced(monkeypatch, tmp_path):
    """Stopping is the safe failure. Starting fresh would destroy what is there,
    and what is there may be the only copy of somebody's other credentials."""
    p = _settings_at(monkeypatch, tmp_path, "{ not json at all")
    _fake_openbb(monkeypatch)

    with pytest.raises(comps.CredentialFileError):
        comps.save_fmp_key("new-key")

    assert p.read_text(encoding="utf-8") == "{ not json at all", "overwrote it anyway"


def test_saving_into_a_machine_with_no_settings_file_yet_works(monkeypatch, tmp_path):
    monkeypatch.setattr(comps, "USER_SETTINGS_PATH", tmp_path / "sub" / "user_settings.json")
    _fake_openbb(monkeypatch, results=[types.SimpleNamespace(symbol="MSFT")])

    comps.save_fmp_key("first-key")

    written = json.loads((tmp_path / "sub" / "user_settings.json").read_text(encoding="utf-8"))
    assert written == {"credentials": {"fmp_api_key": "first-key"}}


def test_an_empty_key_is_rejected_rather_than_stored(monkeypatch, tmp_path):
    _settings_at(monkeypatch, tmp_path, {"credentials": {"fmp_api_key": "old"}})
    with pytest.raises(ValueError):
        comps.save_fmp_key("   ")


def test_saving_verifies_the_key_instead_of_just_reporting_it_stored(monkeypatch, tmp_path):
    """The whole point of doing this in the app rather than in a text editor."""
    _settings_at(monkeypatch, tmp_path, {})
    _fake_openbb(monkeypatch, raises=RuntimeError("Invalid API KEY"))

    assert comps.save_fmp_key("wrong-key") == {"configured": True, "last_call": "failed"}


def test_the_verification_leaves_nothing_in_the_peer_cache(monkeypatch, tmp_path):
    """The probe is a health check, not a lookup someone asked for."""
    _settings_at(monkeypatch, tmp_path, {})
    _fake_openbb(monkeypatch, results=[types.SimpleNamespace(symbol="MSFT")])

    comps.save_fmp_key("good-key")
    assert comps._FMP_PROBE not in comps._FMP_PEER_CACHE


def test_removing_a_key_takes_only_that_key(monkeypatch, tmp_path):
    p = _settings_at(monkeypatch, tmp_path, {
        "credentials": {"tiingo_token": "keep-me", "fmp_api_key": "going"},
        "preferences": {"output_type": "dataframe"},
    })
    monkeypatch.setattr(comps, "_FMP_LAST_CALL", "ok")

    assert comps.clear_fmp_key() == {"configured": False, "last_call": None}

    after = json.loads(p.read_text(encoding="utf-8"))
    assert "fmp_api_key" not in after["credentials"]
    assert after["credentials"]["tiingo_token"] == "keep-me"
    assert after["preferences"] == {"output_type": "dataframe"}


def test_demo_mode_refuses_to_write_a_key_at_all(monkeypatch):
    """Hiding the tab is the visible half and is not a control.

    On a hosted demo the filesystem being written is the operator's, not the
    visitor's, so this has to be refused at the endpoint rather than in the UI.
    """
    import asyncio

    from fastapi import HTTPException

    from backend import main

    monkeypatch.setattr(main, "DEMO_MODE", True)
    for call in (lambda: main.set_fmp_key(main.FmpKeyRequest(key="x")),
                 lambda: main.delete_fmp_key()):
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(call())
        assert excinfo.value.status_code == 403
