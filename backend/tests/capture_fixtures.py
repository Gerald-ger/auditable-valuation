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

# Weekly closes behind the computed beta and the relative-strength metric.
# Weekly rather than daily: five years is ~261 rows instead of ~1,260, which
# keeps the committed fixtures small, and weekly returns are the conventional
# beta window anyway. Only `time` and `close` are kept — the regression needs
# nothing else, and carrying OHLCV would quadruple the files for no test value.
BARS_PERIOD, BARS_INTERVAL = "5y", "1wk"
INDICES = ("^GSPC", "^HSI")

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
BARS_DIR = FIXTURE_DIR / "bars"


def _stem(ticker: str) -> str:
    """Filesystem-safe name. `^` is legal on POSIX but awkward everywhere."""
    return ticker.replace(".", "_").replace("^", "_")


def main(argv: list[str]) -> int:
    # Regenerating the fundamentals refetches live statements and moves every
    # pinned figure and golden score with them, so the two halves are separable:
    # bars can be added or refreshed without disturbing the statement fixtures
    # the valuation tests are calibrated against.
    #   --bars-only          just the weekly closes
    #   --fundamentals-only  just the statements
    bars_only = "--bars-only" in argv
    fundamentals_only = "--fundamentals-only" in argv

    FIXTURE_DIR.mkdir(exist_ok=True)
    BARS_DIR.mkdir(exist_ok=True)
    failed = []
    for ticker, why in ({} if bars_only else TICKERS).items():
        try:
            data = provider.get_fundamentals(ticker)
        except Exception as e:
            failed.append(f"{ticker}: {e}")
            continue
        path = FIXTURE_DIR / f"{ticker.replace('.', '_')}.json"
        path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{ticker:9} -> {path.name:14} {path.stat().st_size // 1024:4} KB  ({why})")

    for ticker in ([] if fundamentals_only else list(TICKERS) + list(INDICES)):
        try:
            bars = provider.get_history(ticker, BARS_PERIOD, BARS_INTERVAL)
        except Exception as e:
            failed.append(f"{ticker} bars: {e}")
            continue
        thin = [{"time": b["time"], "close": b["close"]} for b in bars]
        path = BARS_DIR / f"{_stem(ticker)}.json"
        path.write_text(json.dumps(thin, indent=0), encoding="utf-8")
        span = f"{thin[0]['time']}..{thin[-1]['time']}" if thin else "EMPTY"
        print(f"{ticker:9} -> bars/{path.name:14} {len(thin):4} rows  {span}")
        if len(thin) < 100:
            failed.append(f"{ticker} bars: only {len(thin)} rows, expected ~261")

    for f in failed:
        print(f"FAILED  {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
