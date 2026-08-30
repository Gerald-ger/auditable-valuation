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


def market_bars_or_none(ticker: str) -> tuple[list[dict], list[dict]] | None:
    """`main._market_bars` served from the fixtures, **including its None.**

    Takes a ticker rather than a stem, because that is what the function it
    stands in for takes.

    The None matters. `load_market_bars` raises `FileNotFoundError` for a ticker
    with no committed bars, where the real `_market_bars` returns None and lets
    every caller below it degrade. A double that cannot produce its original's
    failure value turns a future "no bars for this ticker" into a collection
    error instead of the fallback it is supposed to be exercising.
    """
    try:
        bars, index_bars = load_market_bars(ticker.replace(".", "_"))
    except FileNotFoundError:
        return None
    # `_market_bars` returns None when *either leg is empty*, not only when the
    # fetch raised (`main.py:135`). No committed bars file is empty today — they
    # run 249 to 262 rows — so this arm is unreachable from the fixtures as they
    # stand, and it is here because "matches the original's contract" has to
    # include the half that is not currently exercised, or it is not a match.
    return (bars, index_bars) if bars and index_bars else None


# China 10-year government yield. A round test constant, not a market quote, for
# the same reason TEST_CNY_HKD below is one: what these tests pin is that a CNY
# filer is discounted at a Chinese rate, not what that rate was on a given day.
# ChinaBond published 1.6864% on 2026-08-19. Net of the vendored CNY default
# spread of 0.60% this leaves a round 1.10% risk-free.
TEST_CGB_10Y = 0.017
# The same idea for Hong Kong, and the same arithmetic: HKD's published
# default spread is 0.51%, so 3.51% leaves a round 3.00% risk-free. Close to
# the 3.495% the HKGB workbook actually carried on 2026-08-26, because a
# fixture rate far from the real one would let a sign or scale error look
# reasonable in the goldens.
TEST_HKGB_10Y = 0.0351


class NetworkLeak(BaseException):
    """Raised when a test reaches yfinance.

    **A `BaseException` on purpose.** Every leak site in the application
    swallows ordinary exceptions and degrades — `live_price` at
    `data_provider.py:786`, `_market_bars` at `main.py:133` — so from a test an
    outage and a success are indistinguishable, and a probe that raises a plain
    `Exception` sees nothing. That is not a hypothetical: it is why the leak
    recorded on 2026-08-19 was written down as two tests and measured on
    2026-08-31 as seventeen.
    """


# The four yfinance entry points that actually go out to the network.
# `EquityQuery` is deliberately absent — it builds a query object locally and
# only `screen` sends it, so guarding it would fail a test that constructs one
# offline. `download` is included though the backend does not currently call
# it, because this is a guard against the leak not yet written.
_YF_NETWORK_ENTRY_POINTS = ("Ticker", "Search", "download", "screen")


@pytest.fixture(autouse=True)
def no_live_yfinance(request, monkeypatch):
    """yfinance is a hard error outside `network`-marked tests.

    The suite calls itself offline in five places — `README.md:31` and `:448`,
    `PROVENANCE.md:65`, and the docstrings of the two endpoint fixtures. Until
    2026-08-31 that was false in seventeen tests, costing 5s of a 17s run and a
    silent dependency on a vendor being reachable. Nothing failed when it was
    false, which is the whole problem: the claim could not be checked by
    running the suite, only by rebuilding a throwaway probe by hand, and
    between 2026-08-19 and 2026-08-31 nobody did.

    So the probe stops being a thing someone remembers to run. A test that
    genuinely needs the vendor carries `pytest.mark.network` and is deselected
    from the default run anyway; a test that reaches it by accident now fails
    on the spot, naming the call.

    **Two things it does not cover, because a guard is worth what it guards.**
    It patches this interpreter's `yfinance` module object, so it does nothing
    inside a child process — `test_demo_mode.py` spawns three, and those are
    safe because they set `DEMO_MODE=1`, which is a different safety net, not
    this one. And it is yfinance only: the FMP tier in `comps._fmp_peers`
    reaches a live vendor through OpenBB and is held off by convention rather
    than by a fixture, which is recorded in TODOLIST.
    """
    if request.node.get_closest_marker("network"):
        return
    import yfinance

    def refuse(*args, **kwargs):
        raise NetworkLeak(
            f"a test reached yfinance: {args!r}. Stub the provider, or mark the "
            f"test `network` if it is meant to go out.")

    for name in _YF_NETWORK_ENTRY_POINTS:
        if hasattr(yfinance, name):
            monkeypatch.setattr(yfinance, name, refuse)


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
    # And `_hkgb_10y`, added 2026-08-26 with the HKD source. Identical hazard
    # for the third time: `0002_HK` reports HKD, so any test running a DCF over
    # it would fetch an 80 KB workbook from hkgb.gov.hk from inside the offline
    # suite. Pinned to a rate rather than `None` for the reason spelled out
    # above — `None` degrades every HKD name to the US proxy, which is the one
    # path production no longer takes, so the goldens would pin the failure
    # case and stay green whatever the real branch did.
    monkeypatch.setattr(data_provider, "_hkgb_10y", lambda: (TEST_HKGB_10Y, True))


@pytest.fixture(autouse=True)
def isolated_rate_stores(tmp_path, monkeypatch):
    """Point both sovereign-rate fallback stores at throwaway paths, every test.

    `_cgb_10y` and `_hkgb_10y` each write a good reading to disk so the next run
    has something to fall back on. The tests that drive the real parse stub the
    fetch rather than the function, so they reach that write — and without this
    they would leave files in `backend/data/`, and, worse, a *later* test would
    find one and pass on a fallback instead of on the path it meant to exercise.

    Autouse and unconditional, the same reasoning as `temp_db`: isolation that
    each test has to remember to ask for is isolation that will be forgotten.

    Renamed from `isolated_cgb_store` when the HKD store arrived on 2026-08-26.
    Safe as a rename because an autouse fixture is never named by a test.
    """
    from backend import data_provider
    monkeypatch.setattr(data_provider, "CGB_STORE_PATH", tmp_path / "cgb_10y.json")
    monkeypatch.setattr(data_provider, "HKGB_STORE_PATH", tmp_path / "hkgb_10y.json")


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
