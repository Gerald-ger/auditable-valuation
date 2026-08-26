"""Live provider contract tests — deselected by default (`-m network`).

yfinance is an unofficial scraper with no API contract: it has already shipped
two different news payload shapes, and the whole site sits on a single provider.
These tests exist to tell you the shape changed *before* the UI does.

    backend\\.venv\\Scripts\\python.exe -m pytest -m network
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
import yfinance as yf

from backend import comps
from backend import data_provider
from backend import financial_models as fm
from backend import main
from backend import statements
from backend.data_provider import fx_rate, provider

pytestmark = pytest.mark.network

REQUIRED_INFO_FIELDS = [
    "marketCap", "currentPrice", "sharesOutstanding",
    # momentum pillar inputs — losing any of these drops the pillar below its
    # 40% availability threshold and silently changes every composite
    "twoHundredDayAverage", "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
    "52WeekChange", "SandP52WeekChange",
]


def test_quote_shape():
    q = provider.get_quote("AAPL")
    assert q["price"] is not None
    assert q["currency"] == "USD"


def test_fundamentals_still_carry_the_fields_scoring_depends_on():
    f = provider.get_fundamentals("AAPL")
    missing = [k for k in REQUIRED_INFO_FIELDS if f["info"].get(k) is None]
    assert not missing, f"yfinance stopped supplying: {missing}"


def test_cash_flow_statement_still_has_both_fcf_legs():
    """The DCF and both FCF scoring metrics depend on this path existing."""
    f = provider.get_fundamentals("AAPL")
    statement = statements.statement_fcf(f["cash_flow"])
    assert statement is not None
    period, fcf = statement
    assert fcf > 0
    # fcf_conversion is dropped unless net income exists for the SAME period
    assert statements.value_at(f["income_statement"], period,
                        "Net Income", "Net Income Common Stockholders") is not None


def test_peer_snapshot_carries_beta():
    """resolve_beta falls back to the peer median; without this field it can't."""
    snap = provider.get_peer_snapshot("MSFT")
    assert snap["beta"] is not None


def test_news_parses_into_the_expected_shape():
    items = provider.get_news("AAPL")
    assert items, "news feed returned nothing"
    assert {"title", "date", "url", "category"} <= set(items[0])
    assert {i["category"] for i in items} <= {"company", "macro"}


def test_filings_give_the_chart_something_to_mark():
    """The yfinance news feed carries ~3 distinct dates; the whole point of the
    SEC source is that a multi-year chart has more than two markers on it."""
    filings = provider.get_filings("AAPL")
    assert len(filings) > 50
    dates = {f["date"] for f in filings}
    assert len(dates) > 25, f"only {len(dates)} distinct dates"
    assert {"title", "date", "url", "category"} <= set(filings[0])
    assert {f["category"] for f in filings} <= {"earnings", "material", "insider"}
    assert all(f["url"] for f in filings), "a marker with no link is not clickable"


def test_filings_are_skipped_for_non_us_listings():
    """EDGAR has no CIK for HK tickers — this must cost nothing, not raise."""
    assert provider.get_filings("0700.HK") == []


def test_history_returns_ordered_bars():
    bars = provider.get_history("AAPL", "1mo", "1d")
    assert len(bars) > 5
    assert [b["time"] for b in bars] == sorted(b["time"] for b in bars)


@pytest.mark.parametrize("period", sorted(main.WARMUP_SOURCE))
def test_every_configured_lead_in_actually_arrives(period):
    """The half of the lead-in contract no offline test can reach.

    `WARMUP_SOURCE` names a longer period and `_lead_in` fetches it at the
    **display** interval — a pairing Yahoo never promised to serve, and one that
    fails *quietly*: an unserved span returns HTTP 200 with zero bars, `_lead_in`
    finds nothing earlier, and the chart silently reverts to MA50 starting a
    third of the way in. Nothing raises and no offline test can see it.

    AAPL because the run-up has to exist to be fetched — the point is Yahoo's
    coverage, not a young listing's, which
    `test_a_company_younger_than_the_window_gets_what_lead_in_exists` covers
    offline.
    """
    out = main.history("AAPL", period=period)
    assert out["warmup_bars"] == main.WARMUP_BARS, (
        f"{period} got {out['warmup_bars']} lead-in bars from "
        f"{main.WARMUP_SOURCE[period]} at {out['interval']}")
    times = [b["time"] for b in out["bars"]]
    assert times == sorted(times), "lead-in and window must splice into one series"
    assert len(times) == len(set(times)), "a bar must not appear in both"


# ── which side of the FX rate each info field sits on ────────────────
#
# The whole currency conversion rests on one empirical claim: yfinance quotes
# *absolute statement figures* in `financialCurrency` and *market and per-share
# figures* in `currency`. That is not documented anywhere by the provider, so it
# is measured here rather than assumed. Determined 2026-08-10 against three
# China-domiciled HK listings; 9988.HK matched its own quarterly balance sheet
# to 1.0000 (totalDebt) and 0.9998 (totalCash), which is what settled it.
#
# If yfinance ever changes this, every HK valuation silently moves by the FX
# rate and nothing else would catch it.

CROSS_CURRENCY_TICKER = "9988.HK"  # trades HKD, reports CNY, and its info fields
                                   # match its quarterly statements exactly
# Same currency pair, but this one reliably produces a DCF — 9988.HK's statement
# free cash flow is not always positive, and a skipped end-to-end test is not a
# passing one.
CROSS_CURRENCY_VALUED = "0700.HK"


def test_the_two_currency_fields_are_both_present():
    """Without `financialCurrency` the app cannot detect a mismatch at all."""
    info = provider.get_fundamentals(CROSS_CURRENCY_TICKER)["info"]
    assert info["currency"] == "HKD"
    assert info["financialCurrency"] == "CNY"


def test_debt_and_cash_are_quoted_in_the_reporting_currency():
    """`totalDebt` / `totalCash` follow the statements, not the share price.

    They are the net-debt bridge, so if they were trading-currency the DCF would
    be subtracting converted debt from unconverted enterprise value.
    """
    t = yf.Ticker(CROSS_CURRENCY_TICKER)
    info = t.info or {}
    quarterly = t.quarterly_balance_sheet
    period = quarterly.columns[0]

    for info_key, row in (("totalDebt", "Total Debt"),
                          ("totalCash", "Cash Cash Equivalents And Short Term Investments")):
        statement_value = float(quarterly.loc[row, period])
        ratio = info[info_key] / statement_value
        assert ratio == pytest.approx(1.0, rel=0.02), (
            f"{info_key} is {ratio:.4f}x its statement value — if that is near the "
            f"CNY/HKD rate rather than 1.0, yfinance has moved it to the trading "
            f"currency and financial_models.statement_to_market_fx is now wrong")


def test_per_share_figures_are_quoted_in_the_trading_currency():
    """`bookValue` and `trailingEps` are ~FX x their statement equivalents.

    This is the other half of the split: convert these too and the conversion
    would be applied twice.
    """
    info = provider.get_fundamentals(CROSS_CURRENCY_TICKER)["info"]
    rate = fx_rate("CNY", "HKD")
    assert rate is not None, "no CNYHKD rate — cannot run this check"

    price = info["currentPrice"]
    # priceToBook and trailingPE are built from these; if the per-share figures
    # were reporting-currency while price is trading, both ratios would be off
    # by the rate and this identity would fail.
    assert price / info["bookValue"] == pytest.approx(info["priceToBook"], rel=0.02)
    assert info["marketCap"] == pytest.approx(price * info["sharesOutstanding"], rel=0.02)


def test_a_cross_currency_valuation_is_reported_in_the_trading_currency():
    """End to end: the fair value a user reads must be in the same unit as the
    price sitting next to it."""
    f = provider.get_fundamentals(CROSS_CURRENCY_VALUED)
    dcf = fm.dcf_valuation(f)
    assert not dcf.get("error"), dcf.get("error")
    assumptions = dcf["assumptions"]
    assert assumptions["fx_basis"] == "converted"
    assert assumptions["currency"] == "HKD"
    assert assumptions["reporting_currency"] == "CNY"
    assert assumptions["fx_rate_used"] > 1.0     # 1 CNY buys more than 1 HKD
    assert dcf["upside_pct"] is not None


def test_a_single_currency_issuer_converts_nothing():
    dcf = fm.dcf_valuation(provider.get_fundamentals("AAPL"))
    assert dcf["assumptions"]["fx_basis"] == "single_currency"
    assert dcf["assumptions"]["fx_rate_used"] is None


def test_fx_rate_round_trips():
    """A pair and its inverse must multiply to 1, or one of them is upside down —
    the failure mode that would scale a whole valuation by rate squared."""
    forward, backward = fx_rate("CNY", "HKD"), fx_rate("HKD", "CNY")
    assert forward and backward
    assert forward * backward == pytest.approx(1.0, rel=0.02)


def test_fx_rate_is_none_for_a_pair_that_does_not_exist():
    """None, not a fallback constant: callers suppress the comparison instead."""
    assert fx_rate("CNY", "NOTACURRENCY") is None


def test_hk_analyst_targets_arrive_in_the_trading_currency():
    """The one number on the football field that gets no FX conversion.

    Every other figure on that chart is converted out of the reporting currency
    — 9988.HK reports CNY and trades HKD — but `comps.football_field` passes
    `targetLowPrice`/`targetHighPrice` through untouched. Nothing in yfinance
    documents which currency those arrive in, so this pins it the same way the
    statement/trading split above is pinned: by measurement.

    Self-calibrating against the US ADR, which sidesteps both the ADR ratio and
    the FX rate. If each line quotes its targets in its own trading currency,
    the target ratio equals the price ratio. A CNY-denominated HK target would
    show up as a ~1.10x discrepancy — the exact error this guards against.
    """
    hk = provider.get_fundamentals("9988.HK")["info"]
    adr = provider.get_fundamentals("BABA")["info"]
    assert hk["financialCurrency"] == "CNY" and hk["currency"] == "HKD"

    price_ratio = hk["currentPrice"] / adr["currentPrice"]
    target_ratio = hk["targetMeanPrice"] / adr["targetMeanPrice"]
    assert target_ratio / price_ratio == pytest.approx(1.0, rel=0.08)


# `conftest.no_live_screener` stubs `comps._screener_peers` for every test in
# the suite, including this one — so hold the real function, bound at import.
_real_screener_peers = comps._screener_peers


def test_the_keyless_peer_screener_still_answers_the_query_the_tier_builds():
    """The third peer tier, end to end and with no credential of any kind.

    Two pieces of undocumented Yahoo taxonomy hold it up — the em-dash industry
    spelling and the `PNK` exchange code marking OTC cross-listings — and
    neither has an API contract. This is what says so before the UI does.

    `SPG` rather than an exact list: Simon Property is the largest US retail
    REIT by roughly 5x, so its rank is stable, while the names below it are not.
    """
    peers = _real_screener_peers("O")
    assert len(peers) == comps.MAX_AUTO_PEERS
    assert "O" not in peers
    assert "SPG" in peers
    assert "SPG-PJ" not in peers  # a Simon preferred, quoteType=EQUITY, null cap

    # The OTC filter, named against the rows it was written for. Asserting only
    # "no `-` in the symbol" left this test unable to fail when the filter was
    # deleted: `URMCY` and `UNBLF` are one Unibail — the duplicate-vote case the
    # filter exists for — and `STGPF` is Scentre Group, the foreign name. All
    # three rank inside the top handful of this screen, so their absence is a
    # live check rather than a coincidence.
    assert not {"URMCY", "UNBLF", "STGPF"} & set(peers)


# `conftest.pinned_risk_free_rate` stubs `_cgb_10y` for every test in the suite,
# including this one — so hold the real function, bound at import.
_real_cgb_10y = data_provider._cgb_10y


def test_chinabond_still_publishes_a_parseable_ten_year():
    """The CNY risk-free rate, live and with no credential.

    Nothing here has an API contract: the response is an HTML table, it carries
    the commercial-bank and CP&Note curves beside the government one, and a
    query wider than a year returns HTTP 200 with an empty table rather than an
    error. A shape change would parse to `None`, degrade every CNY valuation to
    the US proxy, and do it silently — this is what says so first.

    A band rather than a level: China's 10Y has run 1.6%-2.6% over the three
    years to 2026-08, and it was 1.6864% the day this was written. The band is
    wide enough not to fail on a normal market and narrow enough to catch a
    units change, which is the failure that would actually hurt.

    **What this band does not catch, stated because the gap is not obvious.**
    A wrong `gjqx` in the URL returns a different tenor, and the whole Chinese
    curve is a narrow thing — 3M 1.1858 to 30Y 2.1509 on 2026-08-18. The floor
    at 1.4% excludes 3M, 6M, 1Y, 3Y and 5Y, but **7Y (1.5121) and 30Y (2.1509)
    would both pass**, and a floor high enough to exclude the 7Y would sit above
    the 10Y's own record low of 1.59%. Separating those needs a second tenor
    fetched in the same call and compared, which is recorded in TODOLIST; a band
    cannot do it.
    """
    out = _real_cgb_10y()
    assert out is not None, "ChinaBond unreachable or its table changed shape"
    rate, live = out
    assert live is True, "served from the store — this test is about the live feed"
    assert 0.014 < rate < 0.05, rate


def test_the_ten_year_agrees_with_chinabonds_single_tenor_query():
    """The tenor, cross-checked against a *second* ChinaBond query.

    `_cgb_10y` asks for every tenor and picks the column whose header says
    `10Y`. Checking that against the same response would be circular, so this
    fetches the single-tenor form — `gjqx=10`, exactly what the code sent until
    2026-08-19 — and requires the two routes to agree.

    This is the assertion the band could never make. The whole Chinese curve sat
    inside 1.1858 (3M) to 2.1509 (30Y) on 2026-08-18, so no range check can tell
    the ten-year from the seven- or thirty-year; two independent queries can.
    """
    from datetime import datetime, timedelta, timezone
    from urllib.request import urlopen

    today = datetime.now(timezone.utc)
    start = (today - timedelta(days=data_provider.CGB_WINDOW_DAYS)).strftime("%Y-%m-%d")
    url = (f"{data_provider.CGB_URL}?gjqx=10&qxId=ycqx&locale=en_US"
           f"&startDate={start}&endDate={today.strftime('%Y-%m-%d')}")
    with urlopen(url, timeout=data_provider.CGB_TIMEOUT_S) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [c for c in (re.sub(r"<[^>]+>", "", x).strip()
                             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S))
                 if c]
        if len(cells) == 3 and cells[0] == data_provider.CGB_CURVE:
            rows.append((cells[1], float(cells[2])))
    assert rows, "the single-tenor query returned no government row"
    single = max(rows, key=lambda r: r[0])[1] / 100

    out = _real_cgb_10y()
    assert out is not None, "ChinaBond unreachable"
    # unpacked, not compared whole. Written as `_real_cgb_10y() == approx(single)`
    # first, which cannot ever be true — `_cgb_10y` returns `(rate, live)` — and
    # the message would then have reported the two routes as disagreeing when
    # they are identical. It was shipped unrun because ChinaBond was down for
    # every attempt that day, which is exactly how a test gets to be wrong.
    assert out[0] == pytest.approx(single, abs=1e-6), (
        "the labelled 10Y column and gjqx=10 disagree — one of them is not the "
        "ten-year")


def test_hong_kong_still_publishes_a_parseable_ten_year_benchmark():
    """The HKD risk-free rate, live, keyless, and from a real workbook.

    The offline tests for this parse stub `pandas.read_excel` and feed it a
    DataFrame, because neither `xlrd` nor `openpyxl` is in
    `requirements-test.txt` and a test that built a genuine spreadsheet could
    not run in CI. That leaves exactly one claim unpinned offline — that pandas
    can read *this* file, a legacy OLE2 `.xls` served as
    `application/vnd.ms-excel` — and this is the test that makes it.

    A band rather than a level. Hong Kong's ten-year sat at 3.495% on
    2026-08-26; 1%-7% is wide enough not to fail on an ordinary market and
    narrow enough to catch the failure that would actually hurt, which is a
    units change from percent to ratio.

    **What the band does not catch**, stated because the gap is the same one the
    ChinaBond test records: the sheet publishes 1, 3, 5, 7, 10, 15 and 20-year
    columns, and on 2026-08-25 they ran 3.11% to 4.37%. Every one of them clears
    this band, so a column mis-read is invisible here. That is why the parse
    anchors on three separate labels — `Tenor`, `10-year`, and a `Yield` cell
    that must sit beside it — and why those anchors are pinned offline where a
    band cannot reach them.
    """
    out = data_provider._hkgb_fetch()
    assert out is not None, "hkgb.gov.hk unreachable or the workbook changed shape"
    published, rate = out
    assert 0.01 < rate < 0.07, rate
    # The workbook is a rolling month, so a published date far in the past means
    # it has stopped being updated rather than that today is quiet.
    assert published >= (
        datetime.now(timezone.utc)
        - timedelta(days=data_provider.HKGB_MAX_STALE_DAYS)).strftime("%Y-%m-%d"), published


def test_the_hkd_rate_is_materially_different_from_the_us_one():
    """The reason this source exists at all.

    A peg fixes an exchange rate, not a term structure. If the two curves ever
    did sit on top of each other the whole HKD branch would be ceremony — this
    is what would say so. Measured 2026-08-26: 3.495% against 4.70%, a 120bp gap
    worth roughly a doubling of a low-beta utility's fair value.
    """
    hk = data_provider._hkgb_fetch()
    us = data_provider._us_treasury_10y()
    assert hk is not None and us is not None, "one of the two feeds did not answer"
    assert abs(hk[1] - us) > 0.002, (hk[1], us)
