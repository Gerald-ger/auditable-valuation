"""Which model values which company type, and what the chart does with it.

Before 2026-08-29 there was one intrinsic model and one boolean, and "does a
valuation apply" and "is it a DCF" were the same question asked once. They are
not the same question any more: a bank has an excess return valuation and still
answers False to `dcf_applies`, because everything that flag gates —
`reconcile_to_price`, `price_gap_bridge`, the Financial Models panel — is DCF
machinery that a book-value model has no use for.

These tests exist because splitting that boolean is the kind of change every
existing test keeps passing through. Not one of the seven tests that asserted
the old refusal behaviour needed to change, which is the point of preserving the
semantics — and also the reason the new behaviour needs its own file.
"""
from __future__ import annotations

import pytest

from conftest import load_fundamentals

from backend import comps
from backend import financial_models as fm
from backend import sector_weights as sw
from backend import statements


def classify(stem: str) -> str:
    f = load_fundamentals(stem)
    sfcf = statements.statement_fcf(f["cash_flow"])
    return sw.classify(f["info"], sfcf[1] if sfcf else None)


def field(stem: str, implied: dict | None = None) -> tuple[list[dict], str]:
    """The football field as the endpoint builds it, plus the classification.

    `implied` supplies peer multiples. It has to be passed explicitly because
    `comps_analysis(f, [])` resolves no peers offline and returns
    `implied_values: {}` — so `football_field` never appends the peer row, and
    any assertion that loops over peer rows passes without executing. That is
    exactly how the first version of the equity-basis-note test below passed
    while proving nothing; found in review 2026-08-29.
    """
    f = load_fundamentals(stem)
    cls = classify(stem)
    model = sw.valuation_model_for(cls)
    er = fm.excess_returns_valuation(f) if model == "excess_return" else None
    dd = fm.dividend_discount_valuation(f) if model == "dividend_discount" else None
    peers = ({"implied_values": implied, "peers_used": 3} if implied
             else comps.comps_analysis(f, []))
    ranges = comps.football_field(f, fm.dcf_valuation(f), peers, cls,
                                  excess_return=er, dividend_discount=dd)
    return ranges, cls


STUB_PEERS = {"P/E": 320.0, "P/B": 330.0, "EV/EBITDA": 325.0}


# ── the table, against the derivation it replaced ────────────────────

def test_the_stated_model_table_reproduces_the_old_derivation_exactly():
    """`dcf_applies` used to be `any("dcf_upside_pct" in metrics ...)`.

    Stating the model explicitly decoupled it from the scoring metric list, so
    a bar can be drawn before the metric that scores it exists. That is only
    safe if the new table gives the same answer as the old derivation for every
    classification — this asserts it against the derivation itself rather than
    against a copied list, so a profile edit cannot drift the two apart
    unnoticed.
    """
    for classification in sw.SECTOR_PROFILES:
        derived = any("dcf_upside_pct" in metrics for metrics
                      in sw.get_profile(classification)["metrics"].values())
        assert sw.dcf_applies(classification) is derived, classification


@pytest.mark.parametrize("classification,model", [
    ("technology", "fcff_dcf"),
    ("utilities", "fcff_dcf"),
    ("default", "fcff_dcf"),
    ("financials_bank", "excess_return"),
    ("financials_insurance", "excess_return"),
    ("real_estate_reit", "dividend_discount"),
    ("pre_profit_growth", None),
])
def test_each_type_gets_the_model_that_fits_it(classification, model):
    assert sw.valuation_model_for(classification) == model


def test_an_unknown_classification_falls_back_to_the_dcf():
    assert sw.valuation_model_for("something_new") == "fcff_dcf"


def test_none_is_an_answer_not_a_gap():
    """A pre-profit company has neither positive free cash flow nor a return on
    equity worth compounding, so both models decline. That is a stated result,
    not a missing entry — `VALUATION_MODELS` holds the key with a None value."""
    assert "pre_profit_growth" in sw.VALUATION_MODELS
    assert sw.VALUATION_MODELS["pre_profit_growth"] is None


# ── the chart ────────────────────────────────────────────────────────

def test_a_bank_gets_a_bar_where_it_used_to_get_only_a_strike_out():
    ranges, _ = field("JPM")
    bars = [r for r in ranges if r["method"].startswith("Excess return")]

    assert len(bars) == 1
    bar = bars[0]
    assert bar["low"] < bar["mid"] < bar["high"]
    assert bar["mid"] == pytest.approx(337.55, abs=0.01)
    # The width too, not just the tick. Only the midpoint was pinned until
    # 2026-08-29, and narrowing `EXCESS_ROE_STEPS` to a quarter of its span left
    # every test passing while the bar a reader sees shrank fourfold — the bar
    # *is* the output here, so its edges are the thing to pin.
    assert (bar["low"], bar["high"]) == pytest.approx((290.655, 392.48), abs=0.01)
    cols = fm.excess_returns_valuation(load_fundamentals("JPM"))["sensitivity"]["roe_cols"]
    assert cols[-1] - cols[0] == pytest.approx(
        fm.EXCESS_ROE_STEPS[-1] - fm.EXCESS_ROE_STEPS[0], abs=1e-9)
    assert cols[-1] - cols[0] == pytest.approx(0.04, abs=1e-9)


def test_the_struck_out_dcf_row_survives_and_names_its_replacement():
    """Two different sentences. "A DCF does not apply here" stays true for a
    bank forever; "there is no valuation here" stopped being true. Before this
    change the row could only say the second."""
    ranges, _ = field("JPM")
    struck = [r for r in ranges if r.get("not_applicable")]

    assert len(struck) == 1
    assert struck[0]["method"] == "DCF"
    assert "does not apply to a financials bank" in struck[0]["reason"]
    assert "excess return bar values it instead" in struck[0]["reason"]


def test_the_bar_is_not_named_dcf_so_the_equity_basis_note_stays_off():
    """`comps.py` attaches a note to the peer row explaining that the DCF bridges
    to equity more fully than the vendor's multiples do. An excess return model
    never computes an enterprise value, so that note would be false beside its
    bar. The prefix check that gates it is kept switched off by the bar's name
    rather than by a second condition someone could forget."""
    ranges, _ = field("JPM", STUB_PEERS)
    drawn = [r for r in ranges
             if r["method"].startswith("DCF") and r.get("low") is not None]
    assert drawn == []

    peer = [r for r in ranges if r["method"].startswith("Peer multiples")]
    assert len(peer) == 1, "the row has to exist or this test proves nothing"
    assert peer[0].get("equity_basis_note") is None


def test_a_type_with_no_model_still_gets_no_bar():
    """A pre-profit company keeps its strike-out permanently. It has no positive
    free cash flow, no return on equity worth compounding and no dividend, so
    every model declines — which is a stated answer, not a gap waiting on a
    later phase. RIVN was parametrized here beside O until 2026-08-29; O now
    routes to the dividend discount model and has its own two tests below."""
    ranges, cls = field("RIVN")
    assert sw.valuation_model_for(cls) is None
    assert [r for r in ranges if r.get("not_applicable")]
    assert not [r for r in ranges if r["method"].startswith("Excess return")]
    assert not [r for r in ranges if r["method"].startswith("Dividend discount")]
    assert not [r for r in ranges
                if r["method"].startswith("DCF") and r.get("low") is not None]


def test_a_reit_gets_a_dividend_bar_where_it_used_to_get_only_a_strike_out():
    ranges, _ = field("O")
    bars = [r for r in ranges if r["method"].startswith("Dividend discount")]

    assert len(bars) == 1
    bar = bars[0]
    assert bar["low"] < bar["mid"] < bar["high"]
    assert bar["mid"] == pytest.approx(69.51, abs=0.01)

    struck = [r for r in ranges if r.get("not_applicable")]
    assert len(struck) == 1
    assert "does not apply to a real estate reit" in struck[0]["reason"]
    assert "dividend discount bar values it instead" in struck[0]["reason"]


def test_the_reit_bar_is_not_named_dcf_so_the_equity_basis_note_stays_off():
    """Same construction as the bank's. A model that discounts dividends per
    share never forms an enterprise value, so the peer row's note about the two
    bridges differing would be explaining a difference that does not exist."""
    ranges, _ = field("O", STUB_PEERS)
    assert [r for r in ranges
            if r["method"].startswith("DCF") and r.get("low") is not None] == []

    peer = [r for r in ranges if r["method"].startswith("Peer multiples")]
    assert len(peer) == 1, "the row has to exist or this test proves nothing"
    assert peer[0].get("equity_basis_note") is None


def test_a_dcf_type_is_untouched():
    ranges, _ = field("AAPL")
    dcf_rows = [r for r in ranges if r["method"].startswith("DCF")]
    assert len(dcf_rows) == 1
    assert dcf_rows[0].get("not_applicable") is None
    assert dcf_rows[0]["low"] < dcf_rows[0]["high"]
    assert not [r for r in ranges if r["method"].startswith("Excess return")]


# ── the band ─────────────────────────────────────────────────────────

def test_the_band_does_not_union_a_sweep_that_is_already_in_the_grid():
    """`_dcf_band` unions `growth_sensitivity` in because the DCF's grid holds
    the first-order growth rate fixed outside it. This model's grid sweeps both
    first-order inputs, and `roe_sensitivity` is literally the middle row of it —
    so the union would be a no-op. Asserted rather than assumed, because calling
    `_dcf_band` here would have worked and silently done nothing.
    """
    valuation = fm.excess_returns_valuation(load_fundamentals("JPM"))
    rows = valuation["sensitivity"]["rows"]
    middle = rows[len(rows) // 2]["values"]

    assert valuation["roe_sensitivity"]["values"] == middle

    low, high, basis = comps._excess_return_band(valuation)
    grid = sorted(v for row in rows for v in row["values"] if v is not None)
    assert low >= grid[0] and high <= grid[-1]
    assert "growth" not in basis


def test_an_empty_grid_draws_nothing_rather_than_a_zero_width_bar():
    assert comps._excess_return_band({"sensitivity": {"rows": []}}) is None
    assert comps._excess_return_band({}) is None


def test_the_dividend_band_unions_the_sweep_the_grid_cannot_reach():
    """The opposite decision from `_excess_return_band`, which declines the union
    because that model's grid already contains its one-dimensional sweep.

    On O the union binds on one side: the eligible grid's quartiles are
    58.80-66.73 against a dividend growth sweep of 61.08-78.97, so the ceiling
    moves to 78.97 and the floor does not. That exercises one of the three
    wordings on real data. The other two are unreachable from the only REIT
    fixture in the set, so synthetic grids are fed for each of them below —
    without that, two branches would ship having never run.

    It bound the opposite side until 2026-08-29, when the band stopped counting
    the grid rows whose cost of equity sits below the company's own pre-tax cost
    of debt. Two of the five rows go, the quartiles narrow from 61.49-79.89 to
    58.80-66.73, and the sweep that had been reaching *under* the grid is now
    reaching *over* it. The bar moves 61.08-79.89 to 58.80-78.97.
    """
    valuation = fm.dividend_discount_valuation(load_fundamentals("O"))
    low, high, basis = comps._dividend_discount_band(valuation)
    assert (low, high) == (58.8, 78.97)
    assert basis.endswith("+ dividend growth (upside only)")
    assert max(valuation["growth_sensitivity"]["values"]) == high, \
        "the sweep has to be what moved the ceiling or this proves nothing"

    # And the refused rows are what is missing, rather than the numbers having
    # drifted: every value the band saw comes from a row the model stands behind.
    refused = [r for r in valuation["sensitivity"]["rows"] if r["below_cost_of_debt"]]
    assert len(refused) == 2
    assert max(v for r in refused for v in r["values"]) == 97.76 > high, \
        "the dropped rows reached above the published bar, which is why this matters"

    grid = {"sensitivity": {"rows": [{"values": [90.0, 100.0, 110.0, 120.0]}]}}
    low, high, basis = comps._dividend_discount_band(grid)
    assert (low, high) == (92.5, 117.5) and "dividend growth" not in basis

    both = dict(grid, growth_sensitivity={"values": [80.0, 130.0]})
    assert comps._dividend_discount_band(both) == (80.0, 130.0,
        "cost of equity x terminal growth, 25th-75th + dividend growth")

    down = dict(grid, growth_sensitivity={"values": [80.0, 100.0]})
    assert comps._dividend_discount_band(down)[2].endswith("(downside only)")
    assert comps._dividend_discount_band(down)[0] == 80.0

    up = dict(grid, growth_sensitivity={"values": [100.0, 130.0]})
    assert comps._dividend_discount_band(up)[2].endswith("(upside only)")
    assert comps._dividend_discount_band(up)[1] == 130.0

    # A sweep that lands inside names nothing.
    inside = dict(grid, growth_sensitivity={"values": [100.0, 105.0]})
    assert "dividend growth" not in comps._dividend_discount_band(inside)[2]


def test_an_empty_dividend_grid_draws_nothing_either():
    assert comps._dividend_discount_band({"sensitivity": {"rows": []}}) is None
    assert comps._dividend_discount_band({}) is None


# ── what the endpoint reports ────────────────────────────────────────

def test_full_analysis_carries_both_models_under_separate_keys():
    """Never one in place of the other. The Financial Models tab reads `dcf` for
    a panel built on WACC, terminal growth and an equity bridge; handing it an
    excess-return result under that key would print NaN into the WACC box and
    crash on `sensitivity.terminal_growth_cols`."""
    out = fm.full_analysis(load_fundamentals("JPM"))
    assert "error" not in out["excess_return"]
    # The DCF still runs and still refuses, exactly as before.
    assert "error" in out["dcf"]
    assert "terminal_growth_cols" not in out["excess_return"].get("sensitivity", {})


# ── what the new bar does to everything downstream of it ─────────────

def test_a_banks_triangulation_contains_no_dcf_to_narrate():
    """The bar joins `triangulate`, which is what makes a conviction verdict
    reachable for a bank at all — it never was before, because peer multiples
    were the only method that scored and one method is not a triangulation.

    The Scorecard's LOW-conviction note used to say "a discounted cash flow and
    trading comps measure different things". For a bank there is no DCF in the
    comparison, so it now names the two methods it actually compared.
    """
    ranges, _ = field("JPM", STUB_PEERS)
    t = comps.triangulate(ranges)

    assert len(t["methods_scored"]) == 2
    assert not any(m.startswith("DCF") for m in t["methods_scored"])
    assert t["conviction"] is not None
    # Both ends of the note the frontend renders have to be there to name.
    assert t["anchors"]["low_method"] and t["anchors"]["high_method"]


def test_full_analysis_does_not_ship_a_dividend_discount_for_a_company_it_does_not_fit():
    """The same gate as the one below, needed for the same reason and missed the
    first time round.

    A dividend discount model runs on anything that has ever paid a dividend and
    the answer off its own type is not merely imprecise. Measured 2026-08-29:
    AAPL values at 17.07 against a price of 311, because Apple's dividend is a
    small residual of its earnings rather than the whole of what the business is
    obliged to distribute. The error runs the opposite way from the excess
    return model's 10,249.75 on the same company, which is what makes the pair
    of them a decent test of the routing rather than of one model.

    Nothing renders this key today. That is exactly the argument for gating it
    now: the mutation that removed the gate passed 733 tests on 2026-08-29 and
    was caught by the battery rather than by the suite.
    """
    assert fm.full_analysis(load_fundamentals("AAPL"))["dividend_discount"] is None
    assert fm.full_analysis(load_fundamentals("JPM"))["dividend_discount"] is None
    assert fm.full_analysis(load_fundamentals("RIVN"))["dividend_discount"] is None

    reit = fm.full_analysis(load_fundamentals("O"))["dividend_discount"]
    assert reit is not None and "error" not in reit
    assert 0 < reit["fair_value_per_share"] < 1000
    # And never in place of the other two keys, which stay exactly as they were.
    out = fm.full_analysis(load_fundamentals("O"))
    assert out["excess_return"] is None
    # The REIT's DCF does *not* error — `CFO - CapEx` is positive for a REIT, so
    # the model returns a confident-looking number and only `dcf_applies`
    # suppresses it. That is the whole reason that boolean exists rather than a
    # "did the model return something" test, and it is why the new key had to be
    # added beside `dcf` rather than conditioned on its failure.
    assert "error" not in out["dcf"] and out["dcf"]["equity_value"] > 0
    assert sw.dcf_applies("real_estate_reit") is False


def test_full_analysis_does_not_ship_an_excess_return_for_a_company_it_does_not_fit():
    """The model runs on anything and the answer is nonsense off its own type.

    Buybacks leave AAPL with 73.7bn of book equity against its earnings, so ROE
    reads 167% and the fair value comes out near 10,250 against a price of 311.
    Nothing renders it today, which is precisely why it had to be gated now
    rather than after a panel started reading the key.
    """
    assert fm.full_analysis(load_fundamentals("AAPL"))["excess_return"] is None
    assert fm.full_analysis(load_fundamentals("O"))["excess_return"] is None

    bank = fm.full_analysis(load_fundamentals("JPM"))["excess_return"]
    assert bank is not None and "error" not in bank
    assert 0 < bank["fair_value_per_share"] < 1000
