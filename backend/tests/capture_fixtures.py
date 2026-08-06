"""Regenerate the golden fixtures used by the offline scoring tests.

Run only when you deliberately want new reference data:
    backend\\.venv\\Scripts\\python.exe backend\\tests\\capture_fixtures.py

Each ticker is chosen because it exercises a distinct classification path in
sector_weights.classify — regenerating with different names would silently stop
testing those branches.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_provider import provider  # noqa: E402

# ticker -> the classification branch it is here to cover
TICKERS = {
    "AAPL": "technology",
    "MSFT": "technology + info.freeCashflow reports a single quarter (FCF-source regression)",
    "JPM": "financials_bank",
    "O": "real_estate_reit",
    "XOM": "energy",
    "RIVN": "pre_profit_growth",
    "0700.HK": "HK listing (non-USD, .HK suffix)",
}

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def main() -> int:
    FIXTURE_DIR.mkdir(exist_ok=True)
    failed = []
    for ticker, why in TICKERS.items():
        try:
            data = provider.get_fundamentals(ticker)
        except Exception as e:
            failed.append(f"{ticker}: {e}")
            continue
        path = FIXTURE_DIR / f"{ticker.replace('.', '_')}.json"
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{ticker:9} -> {path.name:14} {path.stat().st_size // 1024:4} KB  ({why})")
    for f in failed:
        print(f"FAILED  {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
