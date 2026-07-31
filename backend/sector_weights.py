"""Sector weighting library — pillar weights + metric substitutions per company type.

Grounded in docs/scoring-system-design.md §3 and the model-priority matrix of
docs/financial-models-reference.md §7.1. Pillars: V=Valuation, Q=Quality,
H=Financial Health, G=Growth, M=Momentum.
"""
from __future__ import annotations

# Base metric set per pillar (profiles override with add/remove)
BASE_METRICS = {
    "V": ["earnings_yield_fwd", "fcf_yield", "ev_ebitda", "dcf_upside_pct"],
    "Q": ["roe", "roic", "operating_margin", "gross_margin", "fcf_conversion"],
    "H": ["net_debt_ebitda", "interest_coverage", "current_ratio", "debt_equity"],
    "G": ["revenue_growth", "revenue_cagr_3y", "earnings_growth", "pe_gap"],
    "M": ["price_vs_200dma", "range_52w_pos", "rel_52w_change", "analyst_upside"],
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
        "weights": {"V": 0.15, "Q": 0.15, "H": 0.25, "G": 0.35, "M": 0.10},
        "metrics": {
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


def classify(info: dict) -> str:
    """Company-type classification; special types override the sector label
    (docs/scoring-system-design.md §3)."""
    industry = (info.get("industry") or "").lower()
    sector = (info.get("sector") or "").lower()

    if "reit" in industry or sector == "real estate":
        return "real_estate_reit"
    if "bank" in industry:
        return "financials_bank"
    if "insurance" in industry:
        return "financials_insurance"

    eps = info.get("trailingEps")
    fcf = info.get("freeCashflow")
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
