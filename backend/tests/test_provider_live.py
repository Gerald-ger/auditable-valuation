"""Live provider contract tests — deselected by default (`-m network`).

yfinance is an unofficial scraper with no API contract: it has already shipped
two different news payload shapes, and the whole site sits on a single provider.
These tests exist to tell you the shape changed *before* the UI does.

    backend\\.venv\\Scripts\\python.exe -m pytest -m network
"""
from __future__ import annotations

import pytest
import yfinance as yf

from backend import comps
from backend import financial_models as fm
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
