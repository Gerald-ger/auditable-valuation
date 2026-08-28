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
    peers = ({"implied_values": implied, "peers_used": 3} if implied
             else comps.comps_analysis(f, []))
    ranges = comps.football_field(f, fm.dcf_valuation(f), peers, cls,
                                  excess_return=er)
    return ranges, cls


BANK_PEERS = {"P/E": 320.0, "P/B": 330.0, "EV/EBITDA": 325.0}


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
    ("real_estate_reit", None),
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
    ranges, _ = field("JPM", BANK_PEERS)
    drawn = [r for r in ranges
             if r["method"].startswith("DCF") and r.get("low") is not None]
    assert drawn == []

    peer = [r for r in ranges if r["method"].startswith("Peer multiples")]
    assert len(peer) == 1, "the row has to exist or this test proves nothing"
    assert peer[0].get("equity_basis_note") is None


@pytest.mark.parametrize("stem", ["O", "RIVN"])
def test_a_type_with_no_model_still_gets_no_bar(stem):
    """The REIT keeps its strike-out until the dividend model lands, and a
    pre-profit company keeps it permanently."""
    ranges, cls = field(stem)
    assert sw.valuation_model_for(cls) is None
    assert [r for r in ranges if r.get("not_applicable")]
    assert not [r for r in ranges if r["method"].startswith("Excess return")]
    assert not [r for r in ranges
                if r["method"].startswith("DCF") and r.get("low") is not None]


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
    ranges, _ = field("JPM", BANK_PEERS)
    t = comps.triangulate(ranges)

    assert len(t["methods_scored"]) == 2
    assert not any(m.startswith("DCF") for m in t["methods_scored"])
    assert t["conviction"] is not None
    # Both ends of the note the frontend renders have to be there to name.
    assert t["anchors"]["low_method"] and t["anchors"]["high_method"]


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
