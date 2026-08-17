"""Forensic checks: Altman Z, Piotroski F, accruals, net share issuance.

These are display-only, so the contract under test is *honesty* rather than a
calibrated number: every check must either produce a value with its published
band, or say why it cannot — never a computed-looking figure built on absent or
inapplicable inputs.
"""
from __future__ import annotations

import copy

import pytest

from conftest import FIXTURES, load_fundamentals

from backend import forensics
from backend import scoring
from backend import sector_weights


def _classification(stem: str) -> str:
    f = load_fundamentals(stem)
    return scoring.score_company(f)["classification"]


@pytest.mark.parametrize("stem", sorted(FIXTURES))
def test_every_check_is_either_computed_or_explained(stem):
    """No check may return a value without applicability, or claim
    applicability without one — that is how a placeholder becomes a number."""
    f = load_fundamentals(stem)
    checks = forensics.forensic_checks(f, _classification(stem))
    for name in ("altman_z", "piotroski_f", "accrual_ratio", "net_share_issuance"):
        c = checks[name]
        if c["applicable"]:
            assert c.get("value") is not None, f"{stem}/{name} applicable but empty"
            assert c.get("band"), f"{stem}/{name} has no band"
        else:
            assert c.get("note"), f"{stem}/{name} unavailable without a reason"
            assert "value" not in c


def test_banks_are_excluded_from_z_and_f_with_a_reason():
    """Altman's Z has a working-capital and a sales term; a bank has neither.
    Reporting 'n/a' is correct — reporting a number would not be."""
    f = load_fundamentals("JPM")
    checks = forensics.forensic_checks(f, "financials_bank")
    assert checks["altman_z"]["applicable"] is False
    assert checks["piotroski_f"]["applicable"] is False
    # cash-based checks do not depend on the manufacturer calibration
    assert checks["accrual_ratio"]["applicable"] is True


@pytest.mark.parametrize("stem,expected_band", [("AAPL", "safe"), ("MSFT", "safe")])
def test_altman_z_places_healthy_megacaps_in_the_safe_band(stem, expected_band):
    z = forensics.altman_z(load_fundamentals(stem), _classification(stem))
    assert z["applicable"] is True
    assert z["band"] == expected_band
    assert z["value"] > forensics.Z_SAFE


def test_altman_z_is_the_weighted_sum_of_its_own_reported_terms():
    """The terms are shown so the number is auditable; they must reconstruct it."""
    z = forensics.altman_z(load_fundamentals("AAPL"), "technology")
    weights = {"working_capital_assets": 1.2, "retained_earnings_assets": 1.4,
               "ebit_assets": 3.3, "equity_liabilities": 0.6, "sales_assets": 1.0}
    rebuilt = sum(weights[k] * v for k, v in z["terms"].items())
    assert rebuilt == pytest.approx(z["value"], abs=0.01)


def test_cash_burning_company_scores_worse_than_a_compounder():
    """RIVN burns cash with negative margins; MSFT does not. If the checks
    cannot separate those two, they are not measuring anything."""
    rivn = forensics.piotroski_f(load_fundamentals("RIVN"), "pre_profit_growth")
    msft = forensics.piotroski_f(load_fundamentals("MSFT"), "technology")
    assert rivn["value"] < msft["value"]
    assert forensics.altman_z(load_fundamentals("RIVN"), "pre_profit_growth")["value"] \
        < forensics.altman_z(load_fundamentals("MSFT"), "technology")["value"]


def test_piotroski_never_counts_an_unknown_test_as_passed():
    f = load_fundamentals("AAPL")
    result = forensics.piotroski_f(f, "technology")
    assert result["value"] == sum(1 for v in result["tests"].values() if v is True)
    assert result["out_of"] == sum(1 for v in result["tests"].values() if v is not None)
    assert result["value"] <= result["out_of"] <= 9


def test_one_period_of_statements_cannot_produce_a_change_metric(empty_fundamentals):
    """Every Piotroski delta and the issuance check need two periods. With one,
    they must decline rather than compare a year against itself."""
    f = copy.deepcopy(empty_fundamentals)
    f["info"] = {"marketCap": 1e9}
    f["income_statement"] = {"2025-12-31": {"Total Revenue": 1e9, "Net Income": 1e8,
                                            "Diluted Average Shares": 1e6}}
    f["balance_sheet"] = {"2025-12-31": {"Total Assets": 2e9}}
    assert forensics.piotroski_f(f, "technology")["applicable"] is False
    assert forensics.net_share_issuance(f)["applicable"] is False


def test_share_issuance_direction_is_not_inverted():
    """A falling share count is a buyback. Getting this sign backwards would
    label every repurchase as dilution."""
    f = {"income_statement": {"2025-12-31": {"Diluted Average Shares": 90.0},
                              "2024-12-31": {"Diluted Average Shares": 100.0}}}
    out = forensics.net_share_issuance(f)
    assert out["value"] == pytest.approx(-0.10)
    assert out["band"] == "buyback"

    g = {"income_statement": {"2025-12-31": {"Diluted Average Shares": 110.0},
                              "2024-12-31": {"Diluted Average Shares": 100.0}}}
    assert forensics.net_share_issuance(g)["band"] == "dilution"


def test_accruals_flag_earnings_running_ahead_of_cash():
    """Net income far above operating cash flow is the Sloan signal."""
    f = {"info": {},
         "income_statement": {"2025-12-31": {"Net Income": 500.0}},
         "balance_sheet": {"2025-12-31": {"Total Assets": 1000.0},
                           "2024-12-31": {"Total Assets": 1000.0}},
         "cash_flow": {"2025-12-31": {"Operating Cash Flow": 100.0,
                                      "Capital Expenditure": -10.0}}}
    out = forensics.accrual_ratio(f)
    assert out["value"] == pytest.approx(0.40)
    assert out["band"] == "high"


def test_accruals_pin_net_income_to_the_cash_flow_period():
    """Mixing this year's cash flow with last year's net income is the same
    period-drift bug the FCF metrics were fixed for."""
    f = {"info": {},
         "income_statement": {"2025-12-31": {"Net Income": 900.0},
                              "2024-12-31": {"Net Income": 200.0}},
         "balance_sheet": {"2024-12-31": {"Total Assets": 1000.0}},
         "cash_flow": {"2024-12-31": {"Operating Cash Flow": 100.0}}}
    # cash flow's newest period is 2024, so net income must come from 2024 too
    assert forensics.accrual_ratio(f)["value"] == pytest.approx(0.10)


def test_checks_do_not_mutate_provider_output():
    """The TTL cache shares one dict between requests."""
    import json
    f = load_fundamentals("AAPL")
    before = json.dumps(f, sort_keys=True)
    forensics.forensic_checks(f, "technology")
    assert json.dumps(f, sort_keys=True) == before


def test_reits_are_excluded_from_altman_z_with_a_reason():
    """Measured: the O fixture scores Z = 1.08, Altman's "distress" band, for a
    REIT with an investment-grade rating. Z's sales/assets and working-capital
    terms read the normal shape of an asset-heavy levered business as failure,
    so a number here would be a false signal, not a conservative one."""
    z = forensics.altman_z(load_fundamentals("O"), "real_estate_reit")
    assert z["applicable"] is False
    assert "not implemented" in z["note"]
    # the checks that do not depend on that calibration still report
    checks = forensics.forensic_checks(load_fundamentals("O"), "real_estate_reit")
    assert checks["accrual_ratio"]["applicable"] is True
    assert checks["net_share_issuance"]["applicable"] is True


def test_profiles_referenced_by_the_exclusion_lists_still_exist():
    """Guards against a profile rename silently re-enabling Z where it misleads."""
    for classification in forensics.NOT_FOR_FINANCIALS + forensics.NOT_FOR_ASSET_HEAVY:
        assert classification in sector_weights.SECTOR_PROFILES
