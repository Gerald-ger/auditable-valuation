"""Sector weighting library — pillar weights + metric substitutions per company type.

Grounded in docs/scoring-system-design.md §3 and the model-priority matrix of
docs/financial-models-reference.md §7.1. Pillars: V=Valuation, Q=Quality,
H=Financial Health, G=Growth, M=Momentum.
"""
from __future__ import annotations

# Base metric set per pillar (profiles override with add/remove)
#
# `analyst_upside` (target price / price - 1) is **not scored in any pillar**.
# It is still computed and still shown — `scoring.extract_metrics` returns it
# and the card carries it as `analyst_context` — but it no longer moves a grade.
#
# It used to sit in M, where it opposed the other three: a rally raised
# price_vs_200dma, range_52w_pos and rel_52w_change while lowering
# analyst_upside, so the four partly cancelled. It was moved to V to fix that.
# The diagnosis was right and the destination was wrong. The test applied was
# "does this move opposite to price?", but every ratio with price in the
# denominator does — earnings yield, FCF yield, inverted EV/EBITDA all do. That
# identifies the denominator. What separates the metrics is the *numerator*:
# every other V metric divides a reported figure or this platform's own model
# by price, while this one divides **someone's forecast of price** by price.
#
# Three things settled it, each measured rather than argued:
#
#   1. Double counting. `dcf_valuation` takes its growth rate from analyst
#      consensus, so an optimistic sell-side view raises `dcf_upside_pct` *and*
#      `analyst_upside` — two of five V metrics, one source, correlated errors
#      of the same sign.
#   2. An undeclared level bias. The curve in scoring.METRIC_ANCHORS scores 0%
#      upside at 45, i.e. near-neutral, but published targets sit above price
#      structurally. When it was last scored, the seven fixtures came out at
#      96/53/52/72/62/83/65 — mean **69** against a centred 50. Seven names do
#      not settle the size of the bias, but they are consistent with a curve
#      whose neutral point is set well below where published targets actually
#      sit, which handed points to the median company for no informational
#      reason. (Those scores are no longer in golden_scores.json; removing the
#      metric removed them, which is the change this note records.)
#   3. The football field already excludes analyst targets from voting, on
#      exactly these grounds. Excluding them from the valuation *chart* while
#      scoring them in the valuation *pillar* is one platform answering the
#      same question two ways.
#
# Measured cost of removal on the fixtures: composite moves -3 to +1, and no
# fixture changes tier (AAPL lands on the A floor at 65). Moving it back to M
# instead would drop AAPL to B and restore the sign conflict, so removal is
# the only option that resolves the contradiction without creating another.
#
# The DCF still consumes analyst consensus growth. That is opinion counted
# once, through a channel that needs *some* forecast and labels its provenance
# — not opinion counted twice, silently, in a pillar named Valuation.
BASE_METRICS = {
    "V": ["earnings_yield_fwd", "fcf_yield", "ev_ebitda", "dcf_upside_pct"],
    "Q": ["roe", "roic", "operating_margin", "gross_margin", "fcf_conversion"],
    "H": ["net_debt_ebitda", "interest_coverage", "current_ratio", "debt_equity"],
    "G": ["revenue_growth", "revenue_cagr_3y", "earnings_growth", "pe_gap"],
    "M": ["price_vs_200dma", "range_52w_pos", "rel_52w_change"],
}

# Relaxed leverage bands for structurally levered sectors (utilities/REITs/telecom)
RELAXED_ND_EBITDA = [(1.0, 100), (2.5, 90), (4.0, 70), (5.0, 50), (6.0, 25), (8.0, 0)]

SECTOR_PROFILES = {
    "technology": {
        "weights": {"V": 0.20, "Q": 0.25, "H": 0.10, "G": 0.30, "M": 0.15},
    },
    "communication_svcs": {
        "weights": {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15},
    },
    "consumer": {  # discretionary
        "weights": {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15},
    },
    "consumer_staples": {
        "weights": {"V": 0.25, "Q": 0.30, "H": 0.15, "G": 0.15, "M": 0.15},
        "add": {"V": ["dividend_yield"]},
    },
    "healthcare": {
        "weights": {"V": 0.20, "Q": 0.30, "H": 0.15, "G": 0.25, "M": 0.10},
    },
    "energy": {  # cyclical: growth deliberately low — never extrapolate the peak
        "weights": {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15},
    },
    "industrials": {
        "weights": {"V": 0.25, "Q": 0.25, "H": 0.20, "G": 0.15, "M": 0.15},
    },
    "logistics": {  # capital-intensive sub-type: leverage matters more
        "weights": {"V": 0.25, "Q": 0.25, "H": 0.25, "G": 0.10, "M": 0.15},
    },
    "utilities": {
        "weights": {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15},
        "add": {"V": ["dividend_yield"]},
        "anchor_overrides": {"net_debt_ebitda": RELAXED_ND_EBITDA},
    },
    "real_estate_reit": {  # P/E & standard EV/EBITDA logic invalid; FFO + yield focus
        "weights": {"V": 0.30, "Q": 0.20, "H": 0.25, "G": 0.10, "M": 0.15},
        "metrics": {
            "V": ["dividend_yield", "p_b", "ffo_yield"],
            "Q": ["roe", "operating_margin"],
            "H": ["net_debt_ebitda", "interest_coverage", "debt_equity"],
            "G": ["revenue_growth", "revenue_cagr_3y", "earnings_growth"],
            "M": BASE_METRICS["M"],
        },
        "anchor_overrides": {"net_debt_ebitda": RELAXED_ND_EBITDA},
    },
    "financials_bank": {  # EV-, FCF- and working-capital metrics invalid
        "weights": {"V": 0.30, "Q": 0.30, "H": 0.20, "G": 0.10, "M": 0.10},
        "metrics": {
            "V": ["earnings_yield_fwd", "p_b", "dividend_yield"],
            "Q": ["roe", "roa"],
            "H": ["equity_assets"],
            "G": ["revenue_growth", "earnings_growth", "pe_gap"],
            "M": BASE_METRICS["M"],
        },
    },
    "financials_insurance": {
        "weights": {"V": 0.30, "Q": 0.30, "H": 0.20, "G": 0.10, "M": 0.10},
        "metrics": {
            "V": ["earnings_yield_fwd", "p_b", "dividend_yield"],
            "Q": ["roe", "roa"],
            "H": ["equity_assets"],
            "G": ["revenue_growth", "earnings_growth", "pe_gap"],
            "M": BASE_METRICS["M"],
        },
    },
    "pre_profit_growth": {  # survival + path-to-profit; confidence capped MEDIUM
        # Q was 0.15 and G was 0.35, which weighted the pillar these companies
        # fail at a quarter of the pillar they ace. For a pre-profit company
        # "can this become profitable" *is* the quality pillar's question, so
        # burying it under growth measured the wrong thing: RIVN scored quality
        # 10 (gross margin 7.5%, operating margin -50.4%) and growth 98, and
        # came out at 74/Tier A — above AAPL's 67, and two tiers above the
        # "Tier 3-5" that docs/scoring-system-design.md 5.2 specifies for this
        # path. Rebalanced to 0.25/0.25 (2026-08-10), which with the
        # cash_runway_q fix lands RIVN at 60/Tier B.
        #
        # Honest limitation, recorded in CHANGELOG: these curves have never been
        # validated against forward returns, so this is a written expectation
        # being enforced, not a market fact.
        "weights": {"V": 0.15, "Q": 0.25, "H": 0.25, "G": 0.25, "M": 0.10},
        "metrics": {
            # Single-metric pillar. `ev_sales` is the only price-to-fundamentals
            # ratio that means anything before profits exist, and V is weighted
            # 0.15 here for that reason.
            "V": ["ev_sales"],
            "Q": ["gross_margin", "operating_margin"],
            "H": ["cash_runway_q", "debt_equity"],
            "G": ["revenue_growth", "revenue_cagr_3y"],
            "M": BASE_METRICS["M"],
        },
        "confidence_cap": "MEDIUM",
    },
    "default": {
        "weights": {"V": 0.25, "Q": 0.25, "H": 0.15, "G": 0.20, "M": 0.15},
    },
}

LOGISTICS_INDUSTRY_HINTS = ("freight", "logistics", "railroad", "marine", "trucking")

# Classifications where a high equity multiplier is the licence, not a choice.
# `scoring.score_company` caps ROE at 70 when assets/equity exceeds 4, because a
# company manufacturing returns with debt is not a quality company. A bank is the
# exception that breaks the rule: JPM's multiplier is 12.2 because deposit-funded
# intermediation is what a bank *is*, and capping its ROE cost 8 points on the
# single metric its Quality pillar leans hardest on (78.4 -> 70, ~1.3 composite)
# while flagging `dupont_leverage_cap_applied` — which reads to a user as an
# accusation of financial engineering. These profiles already measure capital
# adequacy properly through `equity_assets` in the Health pillar, so the guard is
# both wrong and redundant here.
#
# REITs are deliberately NOT on this list. They are structurally levered too, but
# a REIT lifting ROE with debt is a real concern rather than a regulatory floor,
# and their leverage reaches the score through debt_equity and a relaxed
# net_debt_ebitda curve rather than a capital-adequacy metric.
LEVERAGE_IS_STRUCTURAL = ("financials_bank", "financials_insurance")

SECTOR_MAP = {
    "technology": "technology",
    "communication services": "communication_svcs",
    "consumer cyclical": "consumer",
    "consumer defensive": "consumer_staples",
    "healthcare": "healthcare",
    "energy": "energy",
    "basic materials": "industrials",
    "industrials": "industrials",
    "utilities": "utilities",
    "real estate": "real_estate_reit",
}


def classify(info: dict, free_cash_flow: float | None = None) -> str:
    """Company-type classification; special types override the sector label
    (docs/scoring-system-design.md §3).

    `free_cash_flow` is the caller's annual, period-verified FCF — the same
    figure `statements.statement_fcf` resolves. It matters because this
    function chooses the *profile*, and the profile decides which metrics are
    scored and how they are weighted; a misroute here changes the whole model,
    not one number. `info["freeCashflow"]` is the wrong input for that decision:
    yfinance reports it annually for some issuers and for a single quarter for
    others (measured 2026-08-06: MSFT 16.4B vs 67.0B on the statement, 0.24x),
    so a loss-making company with one positive quarter would fall out of
    `pre_profit_growth`. It stays as the fallback for callers that cannot
    resolve a statement figure, which is how it behaved before.
    """
    industry = (info.get("industry") or "").lower()
    sector = (info.get("sector") or "").lower()

    if "reit" in industry or sector == "real estate":
        return "real_estate_reit"
    if "bank" in industry:
        return "financials_bank"
    if "insurance" in industry:
        return "financials_insurance"

    eps = info.get("trailingEps")
    fcf = free_cash_flow if free_cash_flow is not None else info.get("freeCashflow")
    if eps is not None and eps < 0 and (fcf is None or fcf <= 0):
        return "pre_profit_growth"

    if sector == "industrials" and any(h in industry for h in LOGISTICS_INDUSTRY_HINTS):
        return "logistics"
    return SECTOR_MAP.get(sector, "default")


def get_profile(classification: str) -> dict:
    """Resolved profile: pillar weights + active metric lists + anchor overrides."""
    p = SECTOR_PROFILES.get(classification, SECTOR_PROFILES["default"])
    metrics = dict(p.get("metrics") or BASE_METRICS)
    for pillar, extra in (p.get("add") or {}).items():
        metrics[pillar] = metrics[pillar] + [m for m in extra if m not in metrics[pillar]]
    return {
        "classification": classification,
        "weights": p["weights"],
        "metrics": metrics,
        "anchor_overrides": p.get("anchor_overrides", {}),
        "confidence_cap": p.get("confidence_cap"),
    }


def dcf_applies(classification: str) -> bool:
    """Whether a discounted-cash-flow valuation means anything for this type.

    Decided by the profile, never by whether the model happened to return a
    number: a REIT produces a complete DCF from `CFO - CapEx` and it is
    meaningless, because capex *is* a REIT's acquisitions. `scoring.py` exports
    this as `dcf_applicable` and `comps.football_field` refuses to draw a DCF
    bar without it — one rule, read from one place, so the Scorecard and the
    Financial Models tab cannot disagree about the same company.
    """
    return any("dcf_upside_pct" in metrics
               for metrics in get_profile(classification)["metrics"].values())
