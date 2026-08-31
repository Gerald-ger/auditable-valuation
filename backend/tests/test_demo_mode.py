"""Demo mode: the committed fixtures served as if they were a data vendor.

The regression that matters most here is the quiet one. `DEMO_MODE` is read from
the environment once, at `data_provider` import, and a mis-read would serve
frozen August data as though it were live — with no exception, no flag, and a
banner that never appears because the frontend reads the same value. Nothing
else in the suite would notice: every other test already runs against these very
fixtures, so a provider that always served them would look correct everywhere.

So the first test below asserts the *default*, and it is the one that earns its
place in CI. The rest test the pieces directly, which they can do without the
flag because `FixtureProvider` and the five `_demo_*` functions are ordinary
callables — only the wiring needs a separate process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from conftest import BARS_DIR, FIXTURE_DIR, FIXTURES, load_bars

from backend import data_provider as dp

REPO_ROOT = Path(__file__).resolve().parents[2]

# The eight as the app spells them, read from the fixtures rather than listed, so
# adding a ninth does not silently leave this file testing eight.
DEMO_TICKERS = sorted(
    json.loads(p.read_text(encoding="utf-8"))["ticker"] for p in FIXTURES.values()
)


@pytest.fixture
def fp():
    return dp.FixtureProvider()


def _fixture_info(ticker: str) -> dict:
    """The raw `info` block for a ticker, read from disk rather than the provider.

    An oracle has to come from somewhere the code under test did not, which is
    why this re-reads the file instead of calling `get_fundamentals`.
    """
    path = FIXTURES[dp._demo_stem(ticker)]
    return json.loads(path.read_text(encoding="utf-8"))["info"]


# ───────────────────────────── the wiring ─────────────────────────────

def test_demo_mode_is_off_unless_the_environment_says_exactly_one():
    """The default, asserted in CI, where the variable is unset.

    This is the guard against the failure that has no symptom: frozen data
    served as live. `== "1"` is strict on purpose — `DEMO_MODE=true` is *not*
    demo mode. A truthiness test would make `DEMO_MODE=0` enable it, which is
    the opposite of what anyone typing that means.
    """
    assert os.environ.get("DEMO_MODE") is None
    assert dp.DEMO_MODE is False
    assert isinstance(dp.provider, dp.YFinanceProvider)


def test_the_environment_variable_selects_the_fixture_provider():
    """The wiring, in its own process — the flag is bound at import.

    Checks the two bindings that work by different mechanisms: `provider` is
    read through the module (`data_provider.provider`), while `fx_rate` is
    bound by name at import into `financial_models`. If the rebinding block ran
    too late, the second would still point at the live function.
    """
    probe = (
        "from backend import data_provider as dp, financial_models as fm, comps;"
        "from backend import search, store;"
        "import json;"
        "print(json.dumps({"
        "  'provider': type(dp.provider).__name__,"
        "  'demo': dp.DEMO_MODE,"
        "  'fx_bound': fm.fx_rate is dp._demo_fx_rate,"
        "  'rf': dp._us_treasury_10y(),"
        "  'peers': comps.suggest_peers('AAPL'),"
        "  'index_source': search._INDEX_SOURCE,"
        "  'db': store.DB_PATH.name,"
        "  'as_of': [dp.demo_data_as_of('AAPL'), dp.demo_data_as_of('0002.HK')],"
        "}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "DEMO_MODE": "1"}, check=True,
    )
    got = json.loads(out.stdout)

    assert got["demo"] is True
    assert got["provider"] == "FixtureProvider"
    assert got["fx_bound"] is True
    assert got["rf"] is None
    # Not the curated names: four tickers that cannot resolve would render as
    # "No data for: MSFT, GOOGL, META, AMZN", which reads as a network failure
    # rather than as a demo that carries no peer data.
    assert got["peers"] == []
    # `"sec"` here would be a false provenance claim — these rows come from the
    # fixtures, not from SEC's symbol list.
    assert got["index_source"] == "demo"
    # The isolated store. Before this, every demo scorecard view wrote a row
    # into the real database, dated today, carrying a frozen August price.
    assert got["db"] == "demo.db"
    assert got["as_of"] == ["2026-08-10", "2026-08-19"]


# ─────────────────────────── the fixture provider ───────────────────────────

@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_the_quote_goes_through_the_same_mapping_as_the_live_provider(fp, ticker):
    """Shape parity, and by construction rather than by coincidence.

    Both providers call `quote_fields`, so this cannot drift; the test pins that
    they still do. Comparing against the *function* rather than a written list
    is the point — a hand-kept second list is the thing that goes stale.

    The value assertions are not decoration. `quote_fields` is all `dict.get`, so
    it returns the same key set for **any** input including `{}` — shape parity
    alone would pass even if `get_quote` ignored the fixture entirely and mapped
    an empty dict. The fixture is the oracle for whether it read anything.
    """
    q = fp.get_quote(ticker)
    assert set(q) == set(dp.quote_fields("X", {}))

    info = _fixture_info(ticker)
    assert q["price"] == (info.get("currentPrice") or info.get("regularMarketPrice"))
    assert q["market_cap"] == info["marketCap"]
    assert q["currency"] == info["currency"]
    assert q["name"] == info["longName"]


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_the_peer_snapshot_goes_through_the_same_mapping(fp, ticker):
    snap = fp.get_peer_snapshot(ticker)
    assert set(snap) == set(dp.peer_snapshot_fields("X", {}))

    # Same reason as above: the shape would match over an empty dict too. `beta`
    # and `total_debt` are the two `resolve_beta` unlevers a peer with, so they
    # are the ones worth pinning to the fixture.
    info = _fixture_info(ticker)
    assert snap["beta"] == info["beta"]
    assert snap["total_debt"] == info["totalDebt"]
    assert snap["sector"] == info["sector"]


def test_the_quote_leaves_uncaptured_fields_none_rather_than_inventing_them(fp):
    """Four fields the 51-key whitelist never carried.

    Filling `day_high`/`day_low` from `currentPrice` would put a day's range on
    screen that no capture supports — the same rule that keeps a zero-interest
    issuer's coverage ratio `null` rather than printing the top anchor.
    """
    q = fp.get_quote("AAPL")
    assert q["price"] == 311.0
    for absent in ("previous_close", "day_high", "day_low", "exchange"):
        assert q[absent] is None, absent


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_the_fundamentals_are_the_fixture_and_a_fresh_copy_each_call(fp, ticker):
    first = fp.get_fundamentals(ticker)
    assert first["ticker"] == ticker
    first["info"]["marketCap"] = -1
    assert fp.get_fundamentals(ticker)["info"]["marketCap"] != -1


def test_the_home_index_series_resolves_to_its_bars_fixture(fp):
    """`^GSPC` and `^HSI` are what `home_index` returns; `_GSPC` is the filename.

    `main._market_bars` asks for the index by the caret spelling, so a stem that
    only handled `.`→`_` would raise here and the momentum pillar would quietly
    degrade for every company.
    """
    for caret, stem in (("^GSPC", "_GSPC"), ("^HSI", "_HSI")):
        assert fp.get_history(caret, "5y", "1wk") == load_bars(stem)


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_the_bars_are_the_series_the_scoring_path_asks_for(fp, ticker):
    bars = fp.get_history(ticker, "5y", "1wk")
    assert bars, ticker
    # `{time, close}` only. Asserted rather than assumed: `market_series` reads
    # just `close`, but a caller that started wanting `volume` would get None
    # from a dict that never had the key, not an error.
    assert set(bars[0]) == {"time", "close"}
    assert bars == sorted(bars, key=lambda b: b["time"])


def test_an_unknown_ticker_raises_rather_than_reading_as_a_company_with_nothing(fp):
    """`{}` would reach the model layer as a company that reports nothing.

    That is a different claim from one this demo does not carry, and the callers
    that can degrade already catch — `_market_bars` and `peer_beta_inputs` both
    wrap in `try/except`.
    """
    for absent in ("TSLA", "GOOGL", "NVDA"):
        with pytest.raises(KeyError):
            fp.get_fundamentals(absent)
        with pytest.raises(KeyError):
            fp.get_history(absent)


def test_get_history_refuses_a_resolution_the_capture_does_not_carry(fp):
    """One series exists. Serving it for every request mislabelled it.

    `/api/stock/{t}/history` echoes the interval it was asked for, so a request
    for daily bars came back tagged `"1d"` over weekly data; `ai_predict` sliced
    `bars[-30:]` meaning thirty trading days and got thirty **weeks**. Refused
    rather than resampled, on the same rule that withholds the Tracker: the
    capture has one resolution and the others were never observed.
    """
    for period, interval in [("1y", "1d"), ("6mo", "1d"), ("5y", "1d"),
                             ("1mo", "1wk"), ("max", "1wk")]:
        with pytest.raises(ValueError) as excinfo:
            fp.get_history("AAPL", period, interval)
        assert f"{period}/{interval}" in str(excinfo.value)
        assert "5y/1wk" in str(excinfo.value)


@pytest.mark.parametrize("ticker", DEMO_TICKERS)
def test_the_captured_resolution_is_still_served(fp, ticker):
    """The refusal must not cost the one call the scoring path actually makes."""
    assert fp.get_history(ticker, *dp.DEMO_BARS)


def test_an_unknown_ticker_is_reported_before_an_unsupported_resolution(fp):
    """Both are wrong; the ticker is the one the caller can act on.

    `_market_bars` and `peer_beta_inputs` both catch broadly, so the class of
    exception is not load-bearing for them — but a 502 saying "5y/1wk" when the
    real problem is a ticker that does not exist would send a reader looking in
    the wrong place.
    """
    with pytest.raises(KeyError):
        fp.get_history("TSLA", "1y", "1d")


def test_the_captured_resolution_agrees_with_both_downstream_spellings():
    """Three modules name this pair. They have to agree or the demo serves nothing.

    `capture_fixtures` chose it, `main` asks for it, and `FixtureProvider` now
    enforces it. Asserted here rather than shared by import because both of the
    others import `provider` from `data_provider`, so either import would be a
    cycle — which is exactly the situation where a drift test earns its place.
    """
    from backend import main

    from conftest import FIXTURES as _  # noqa: F401  (keeps conftest on the path)
    import capture_fixtures

    assert dp.DEMO_BARS == (capture_fixtures.BARS_PERIOD, capture_fixtures.BARS_INTERVAL)
    assert dp.DEMO_BARS == (main.BETA_PERIOD, main.BETA_INTERVAL)


def test_the_endpoints_degrade_rather_than_mislead_under_the_refusal():
    """What the refusal costs each caller, measured in a demo-mode process.

    The point of refusing is that every caller already had a correct degradation
    path and none of them was being taken. This asserts they are now.
    """
    probe = """
import json
from fastapi import HTTPException
from backend import main

out = {}

# the scoring path asks for the captured pair and must be unaffected
bars = main._market_bars("AAPL")
out["market_bars"] = None if bars is None else [len(bars[0]), len(bars[1])]

# the chart endpoint: a 502 naming the reason beats bars labelled "1d"
try:
    main.history("AAPL", period="1y")
    out["history"] = "NO ERROR"
except HTTPException as e:
    out["history"] = [e.status_code, e.detail]

# the lead-in must cost the left edge of an indicator, never the request
out["lead_in"] = main._lead_in("AAPL", "1y", "1d", "2024-01-01")

print(json.dumps(out))
"""
    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "DEMO_MODE": "1"}, check=True,
    )
    got = json.loads(run.stdout)

    assert got["market_bars"] == [262, 262], "the scoring path lost its series"
    assert got["history"][0] == 502
    assert "5y/1wk" in got["history"][1]
    assert got["lead_in"] == [], "a lead-in failure must not raise"


def test_news_and_filings_are_empty_not_missing(fp):
    """The capture carries neither. `[]` is what "we have none" looks like here."""
    assert fp.get_news("AAPL") == []
    assert fp.get_filings("AAPL") == []


# ──────────────────────── the rates and the FX pair ────────────────────────

def test_the_demo_rate_readings_carry_labels_that_are_true(monkeypatch):
    """A pinned reading is a *stored* reading, and says so.

    `_cgb_10y`/`_hkgb_10y` return `(rate, live)`; `False` selects the
    `*_stored_less_spread` label — "the last good reading rather than today's",
    which is exactly what these are. `_us_treasury_10y` returns None, so USD
    reports `platform_default`: "no feed, `fallback` stands in". Neither claims
    a fetch that never happened.
    """
    monkeypatch.setattr(dp, "_us_treasury_10y", dp._demo_us_treasury_10y)
    monkeypatch.setattr(dp, "_cgb_10y", dp._demo_cgb_10y)
    monkeypatch.setattr(dp, "_hkgb_10y", dp._demo_hkgb_10y)

    assert dp.risk_free_rate(0.043, "USD")[1] == "platform_default"
    assert dp.risk_free_rate(0.043, "CNY", 0.006)[1] == "cgb_10y_stored_less_spread"
    assert dp.risk_free_rate(0.043, "HKD", 0.0051)[1] == "hkgb_10y_stored_less_spread"


def test_the_demo_rates_are_the_published_readings_not_the_round_test_constants():
    """`conftest`'s constants are deliberately round; a demo shows real analysis.

    Reusing `TEST_CGB_10Y = 0.017` would put a number on screen whose own
    comment calls it "a round test constant, not a market quote".
    """
    from conftest import TEST_CGB_10Y, TEST_HKGB_10Y
    assert dp.DEMO_CGB_10Y != TEST_CGB_10Y
    assert dp.DEMO_HKGB_10Y != TEST_HKGB_10Y
    assert dp._demo_cgb_10y() == (dp.DEMO_CGB_10Y, False)
    assert dp._demo_hkgb_10y() == (dp.DEMO_HKGB_10Y, False)


def test_demo_fx_covers_the_one_pair_these_fixtures_need():
    """`0700.HK` reports CNY and trades HKD; the other seven are single-currency.

    Anything else returns None, which is the real function's own failure mode —
    the comparison is suppressed rather than guessed.
    """
    assert dp._demo_fx_rate("CNY", "HKD") == dp.DEMO_CNY_HKD
    assert dp._demo_fx_rate("USD", "USD") == 1.0
    assert dp._demo_fx_rate("HKD", "HKD") == 1.0
    assert dp._demo_fx_rate("EUR", "JPY") is None
    assert dp._demo_fx_rate(None, "HKD") is None


def test_no_fixture_needs_a_currency_pair_the_demo_cannot_supply():
    """The claim above, checked against the files rather than remembered."""
    for stem, path in FIXTURES.items():
        info = json.loads(path.read_text(encoding="utf-8"))["info"]
        rate = dp._demo_fx_rate(info.get("financialCurrency"), info.get("currency"))
        assert rate is not None, stem


def test_the_captured_price_stands_in_demo_mode():
    """`with_fresh_price` refreshes by default, which is a live call per request."""
    assert dp._demo_live_price("AAPL") is None
    f = {"ticker": "AAPL", "info": {"currentPrice": 311.0}}
    monkey = dp.live_price
    try:
        dp.live_price = dp._demo_live_price
        assert dp.with_fresh_price(f) is f
    finally:
        dp.live_price = monkey


# ──────────────────── persistence, and how old the data is ────────────────────

def test_the_store_writes_to_the_live_database_unless_demo_mode():
    """The CI-side half of the isolation, and the one that guards the regression.

    `/api/score/{ticker}` records every score, keyed on today's date. Under demo
    mode that wrote frozen August prices into the real calibration set — six such
    rows existed when it was found — and `ON CONFLICT ... DO UPDATE` overwrote any
    genuine row for the same ticker and day. The demo half is asserted in the
    subprocess probe; this is the half that runs in CI, where the flag is unset.
    """
    from backend import store

    assert store.DB_PATH.name == "app.db"
    assert store.DB_PATH.parent.name == "data"


def _stub_store(monkeypatch):
    """Records what `upsert_position` was called with instead of writing it.

    An oracle the defect can be read off directly: what is wrong with the
    unguarded endpoint is the *write*, not the response, and stubbing the writer
    is what makes "never reached the store" checkable without a demo.db on disk.
    """
    from backend import store
    wrote = []
    monkeypatch.setattr(store, "upsert_position",
                        lambda *args, **kwargs: wrote.append(args))
    return wrote


def test_a_ticker_the_demo_cannot_price_never_becomes_a_position(monkeypatch):
    """Left open by the 2026-08-27 demo review, and hosting is what closed it.

    `POST /api/portfolio/position` took any string, so a visitor could add
    `TSLA` and get a permanent row whose quote read "TSLA is not one of the demo
    tickers". That was left because the message is accurate and actionable — an
    argument that assumed the row was the visitor's own to delete, which is
    exactly what a hosted demo removes.
    """
    from backend import main

    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setattr(main, "provider", dp.FixtureProvider())
    wrote = _stub_store(monkeypatch)

    with pytest.raises(HTTPException) as excinfo:
        main.upsert_position(main.PositionRequest(ticker="TSLA", shares=10))

    assert excinfo.value.status_code == 400
    assert "not one of the demo tickers" in excinfo.value.detail
    assert wrote == [], "the refused position still reached the store"


def test_a_demo_ticker_is_still_recorded(monkeypatch):
    """The other half, without which the guard could be refusing everything."""
    from backend import main

    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setattr(main, "provider", dp.FixtureProvider())
    wrote = _stub_store(monkeypatch)

    main.upsert_position(main.PositionRequest(ticker="0700.HK", shares=10))

    assert [args[0] for args in wrote] == ["0700.HK"]


def test_live_mode_records_a_position_without_asking_the_provider(monkeypatch):
    """The guard is demo-only on purpose, and this is the reason.

    A provider check on the live write path is a network call between you and
    your own record of what you hold: a Yahoo outage, or a ticker yfinance
    happens not to know, would refuse a position that exists. Being unable to
    write down a holding is a worse failure than the junk row demo mode refuses,
    so live mode keeps taking the ticker at its word.
    """
    from backend import main

    class Refuses:
        def __getattr__(self, name):
            raise AssertionError(f"live mode reached the provider: {name}")

    monkeypatch.setattr(main, "DEMO_MODE", False)
    monkeypatch.setattr(main, "provider", Refuses())
    wrote = _stub_store(monkeypatch)

    main.upsert_position(main.PositionRequest(ticker="TSLA", shares=10))

    assert [args[0] for args in wrote] == ["TSLA"]


def test_a_live_answer_reports_no_data_vintage():
    """`None` means live. A date here would claim a capture that never happened."""
    for ticker in DEMO_TICKERS + ["TSLA", "NVDA"]:
        assert dp.demo_data_as_of(ticker) is None, ticker


def test_the_demo_vintage_is_the_oldest_capture_in_each_payload():
    """From PROVENANCE.md, and understating rather than overstating.

    Seven fixtures carry statements from 2026-08-10 and bars from 2026-08-14;
    `0002_HK` carries both halves from 2026-08-19. Naming the *newer* half would
    say the statements are fresher than they are, so the older one is reported.
    """
    # Checked against PROVENANCE.md rather than against themselves. That file is
    # the repo's only record of what was captured and when, and it is required
    # reading before a recapture — so if the fixtures are ever refreshed and it
    # is updated, this fails and the demo constants get updated with it.
    provenance = (FIXTURE_DIR / "PROVENANCE.md").read_text(encoding="utf-8")
    assert dp.DEMO_DATA_AS_OF_DEFAULT in provenance
    for stem, date in dp.DEMO_DATA_AS_OF.items():
        assert date in provenance, stem

    assert dp.DEMO_DATA_AS_OF_DEFAULT == "2026-08-10"
    assert dp.DEMO_DATA_AS_OF == {"0002.HK": "2026-08-19"}
    # Every key must name a ticker the demo actually serves, or it is a typo that
    # silently falls through to the default.
    assert set(dp.DEMO_DATA_AS_OF) <= set(DEMO_TICKERS)


def test_capture_fixtures_refuses_to_run_against_the_fixtures_it_writes():
    """Under the flag `provider` is `FixtureProvider`, whose source is this
    script's own output directory — so it would read all eight and write them
    back byte-identical, with no exception, nothing in `failed`, and exit 0.

    Asserted by mtime, not by the message: a guard that printed a warning and
    rewrote the files anyway would pass a message-only check.
    """
    fixture_files = sorted(FIXTURE_DIR.rglob("*.json"))
    assert len(fixture_files) >= 18, "expected the eight payloads and ten bars files"
    before = {p: p.stat().st_mtime_ns for p in fixture_files}

    out = subprocess.run(
        [sys.executable, str(FIXTURE_DIR.parent / "capture_fixtures.py")],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "DEMO_MODE": "1"},
    )

    assert out.returncode == 1, out.stdout + out.stderr
    assert "DEMO_MODE" in out.stdout
    assert {p: p.stat().st_mtime_ns for p in fixture_files} == before


# ─────────────────────────────── search ───────────────────────────────

def test_the_demo_index_offers_only_tickers_that_resolve(fp):
    """Nothing a visitor can pick from the dropdown can 404.

    Built from each fixture's own `ticker` field rather than by reversing
    `_demo_stem`, so `0700_HK.json` yields `0700.HK` without guessing where the
    dot went.
    """
    from backend import search

    rows = search._demo_index()
    assert sorted(r["symbol"] for r in rows) == DEMO_TICKERS
    for row in rows:
        assert row["name"]
        assert fp.get_fundamentals(row["symbol"])["ticker"] == row["symbol"]


def test_the_demo_index_does_not_include_the_benchmark_series():
    """`_GSPC`/`_HSI` are bars, not companies — they live in `bars/`, not beside it."""
    from backend import search

    symbols = {r["symbol"] for r in search._demo_index()}
    assert not symbols & {"^GSPC", "^HSI", "_GSPC", "_HSI"}
    assert (BARS_DIR / "_GSPC.json").exists()


def test_the_search_source_label_says_sec_only_when_it_came_from_sec():
    """`"sec"` is a provenance claim, and in demo mode it would be false.

    This half asserts the live value; the demo value is asserted in the
    subprocess probe above, because the label is fixed at import. An earlier
    version of this test checked only `== "sec"` — true by construction in any
    non-demo process, and therefore no evidence about the case the comment on
    `_INDEX_SOURCE` actually cares about.
    """
    from backend import search

    assert search._INDEX_SOURCE == "sec"
    assert search._demo_index(), "the demo corpus must not be empty"
