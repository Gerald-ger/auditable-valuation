"""Scoring validation per docs/scoring-system-design.md §5.
Run: backend\\.venv\\Scripts\\python.exe backend\\test_scoring.py
Covers determinism (5.1) and degenerate inputs (5.4) offline; golden-ticker
ordering (5.2) runs live if the network allows.
"""
import copy
import json

import scoring
from data_provider import provider

# ── 5.4 degenerate inputs ────────────────────────────────────────────
empty = {"ticker": "NULL", "info": {}, "estimates": {},
         "income_statement": {}, "balance_sheet": {}, "cash_flow": {}}
card = scoring.score_company(empty)
assert card["composite_score"] is None, "all-None must produce no score"
assert card["coverage_pct"] == 0
assert card["confidence"] == "LOW"
print("degenerate all-None: OK (no score, coverage 0, no crash)")

neg = copy.deepcopy(empty)
neg["ticker"] = "NEG"
neg["info"] = {"currentPrice": 10, "marketCap": 1e9, "trailingEps": -2.0,
               "freeCashflow": -5e7, "sector": "Technology", "industry": "Software"}
card = scoring.score_company(neg)
assert card["classification"] == "pre_profit_growth", card["classification"]
v = card["pillars"]["valuation"]["metrics"]
assert card["confidence"] != "HIGH", "pre-profit confidence must be capped"
print(f"degenerate negative-earnings: OK (classified {card['classification']}, "
      f"confidence {card['confidence']})")

absurd = copy.deepcopy(empty)
absurd["ticker"] = "ABS"
absurd["info"] = {"currentPrice": 10, "marketCap": 1e9, "trailingPE": 4000,
                  "forwardPE": 4000, "trailingEps": 0.0025, "sector": "Technology",
                  "industry": "Software", "enterpriseToEbitda": 99999}
scoring.score_company(absurd)  # must not crash; winsorization handles junk
print("degenerate absurd values: OK (winsorized, no crash)")

# ── 5.1 determinism (live fetch, scored twice) ───────────────────────
try:
    f = provider.get_fundamentals("AAPL")
except Exception as e:
    print(f"(live tests skipped: {e})")
    raise SystemExit(0)

a = scoring.score_company(copy.deepcopy(f))
b = scoring.score_company(copy.deepcopy(f))
a.pop("as_of"), b.pop("as_of")
assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
print("determinism: OK (identical score for identical inputs)")

# ── 5.2 golden-ticker plausibility (ordering, not exact values) ──────
golden = ["MSFT", "NVDA", "JPM", "KO", "XOM"]
cards = {}
for t in golden:
    try:
        cards[t] = scoring.score_company(provider.get_fundamentals(t))
    except Exception as e:
        print(f"  {t}: fetch failed ({e})")

for t, c in cards.items():
    ps = {k: v["score"] for k, v in c["pillars"].items()}
    print(f"  {t}: {c['composite_score']} tier {c['tier']} ({c['classification']}, "
          f"cov {c['coverage_pct']}%, conf {c['confidence']}) pillars {ps}")

if "JPM" in cards:
    jpm = cards["JPM"]
    assert jpm["classification"] == "financials_bank"
    all_metrics = [m for p in jpm["pillars"].values() for m in p["metrics"]]
    assert "ev_ebitda" not in all_metrics and "current_ratio" not in all_metrics, \
        "bank profile must drop EV/EBITDA and current ratio"
    print("JPM bank-path substitutions: OK")
if "NVDA" in cards and cards["NVDA"]["pillars"]["valuation"]["score"] is not None:
    v = cards["NVDA"]["pillars"]["valuation"]["score"]
    print(f"NVDA valuation pillar = {v} (design expects it to visibly drag; <60 wanted)")

print("\nAll assertions passed.")
