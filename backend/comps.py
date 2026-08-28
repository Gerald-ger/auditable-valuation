"""Peer comparison (trading comps) and valuation-range (football field) assembly.

Peer suggestions are curated-first: FMP peer discovery is measurably worse than
the hand-curated list where one exists (UPS -> HWM, GD, MMM, WM — generic
industrials rather than freight), but it covers HK and turns "no peers at all"
into "usually usable" for the ~everything else. Users can always edit the peer
list in the UI, so a bad suggestion is visible and correctable.

Below FMP sits a third tier that needs no API key at all — see
`_screener_peers`. It exists because the two tiers above it leave a clone of
this repo with peers for exactly 23 tickers: FMP is the only credential the
platform reads, and without it `suggest_peers` returned an empty list for
everything else.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from statistics import median, quantiles

import yfinance as yf
from yfinance.const import EQUITY_SCREENER_EQ_MAP

from backend import financial_models as fm
from backend import sector_weights
from backend.data_provider import DEMO_MODE, provider

PEER_SUGGESTIONS = {
    # US mega-cap tech
    "AAPL": ["MSFT", "GOOGL", "META", "AMZN"],
    "MSFT": ["AAPL", "GOOGL", "AMZN", "ORCL"],
    "GOOGL": ["META", "MSFT", "AMZN", "AAPL"],
    "META": ["GOOGL", "SNAP", "PINS", "MSFT"],
    "AMZN": ["MSFT", "GOOGL", "WMT", "BABA"],
    "NVDA": ["AMD", "AVGO", "INTC", "QCOM"],
    "AMD": ["NVDA", "INTC", "QCOM", "AVGO"],
    "TSLA": ["BYDDY", "GM", "F", "RIVN"],
    "NFLX": ["DIS", "WBD", "PARA", "ROKU"],
    # US financials / consumer / health / energy
    "JPM": ["BAC", "WFC", "C", "GS"],
    "V": ["MA", "AXP", "PYPL", "FI"],
    "JNJ": ["PFE", "MRK", "ABBV", "LLY"],
    "WMT": ["TGT", "COST", "KR", "AMZN"],
    "KO": ["PEP", "KDP", "MNST", "CELH"],
    "XOM": ["CVX", "COP", "SHEL", "BP"],
    "UPS": ["FDX", "GXO", "CHRW", "EXPD"],
    "FDX": ["UPS", "GXO", "CHRW", "EXPD"],
    # HK
    "0700.HK": ["9988.HK", "3690.HK", "9999.HK", "1024.HK"],
    "9988.HK": ["0700.HK", "3690.HK", "9618.HK", "PDD"],
    "3690.HK": ["9988.HK", "0700.HK", "9618.HK", "1024.HK"],
    "0005.HK": ["2388.HK", "0011.HK", "1398.HK", "3988.HK"],
    "1299.HK": ["2318.HK", "2628.HK", "0966.HK", "PRU"],
    "0941.HK": ["0728.HK", "0762.HK", "T", "VZ"],
}

MULTIPLE_KEYS = ["pe_trailing", "pe_forward", "price_to_book",
                 "ev_to_ebitda", "ev_to_revenue", "peg_ratio"]

# Which peer median each implied value rests on, so the football field can say
# how thin the thinnest one is rather than quoting the peer count and implying
# every multiple had that much support.
IMPLIED_TO_MULTIPLE = {
    "peer_forward_pe": "pe_forward",
    "peer_trailing_pe": "pe_trailing",
    "peer_ev_ebitda": "ev_to_ebitda",
    "peer_ev_revenue": "ev_to_revenue",
    "peer_price_to_book": "price_to_book",
}


MAX_AUTO_PEERS = 4

# How far the target's operating margin may sit from the peer median before a
# peer EV/Revenue multiple stops transferring. See `_ev_revenue_transfers`.
EV_REVENUE_MARGIN_TOLERANCE = 2.0

# Sell-side target ranges below this many contributing analysts are one or two
# opinions wearing the costume of a range. Same threshold as the analyst signal
# in scoring.py, deliberately: one rule, one number.
MIN_ANALYST_OPINIONS = 4

# How far apart the analysts are, as (high - low) / mean.
#
# The target *range* is excluded from the valuation for good reasons — it
# forecasts a price rather than valuing a business — but its *width* answers a
# different question the platform was throwing away: how much do informed
# observers disagree about this company? That is an uncertainty signal, not a
# valuation one, so it is reported beside the conviction grade rather than
# folded into it.
#
# Round thresholds rather than fitted ones, checked against a 20-name panel
# measured 2026-08-13 (min 15.4% on O, median 41.5%, max 105.7% on NVDA) only to
# confirm they discriminate: they split it 6 tight / 11 moderate / 3 wide. They
# are not calibrated against outcomes and no part of the score depends on them.
ANALYST_DISPERSION_TIGHT, ANALYST_DISPERSION_WIDE = 0.30, 0.60

# Method-midpoint spread bands from the reference doc's conviction table
# (§5.2). Above DIVERGENCE_CALLOUT the doc's instruction is explicit: do not
# average into false precision, report both anchors and name the assumption
# that separates them.
CONVICTION_HIGH, CONVICTION_MEDIUM = 0.15, 0.30
DIVERGENCE_CALLOUT = 0.40

# How many rows to ask the screener for. Much larger than MAX_AUTO_PEERS on
# purpose: the filters in `_screener_peers` are aggressive, so the request has
# to carry the wastage. Measured at 50 across the seven fixture industries,
# 2026-08-19 — only 148 of 319 rows survived, and the thinnest case was RIVN's
# 11 (38 of its 50 rows were OTC). It is one request either way.
SCREENER_SIZE = 50

# Yahoo's screener spells an industry with an em-dash ("REIT—Retail") where
# `info['industry']` hands back a spaced hyphen ("REIT - Retail"). This maps one
# onto the other, derived from the pinned yfinance's own list rather than
# hand-written — and derived in that direction rather than rewriting the
# incoming string, so that an industry this build does not know misses the
# lookup and yields no peers instead of being quietly reshaped into a spelling
# the screener would reject anyway.
#
# Measured against yfinance 1.5.2 on 2026-08-19: 145 industries produce 145
# distinct hyphen forms, so nothing collides, and all seven fixtures'
# `info['industry']` values are keys here. `sector` needs no such treatment —
# its 11 values are the same strings on both sides — which is why the query
# below screens on industry alone.
_SCREENER_INDUSTRY = {
    label.replace("—", " - "): label
    for group in EQUITY_SCREENER_EQ_MAP["industry"].values()
    for label in group
}

_FMP_PEER_CACHE: dict[str, list[str]] = {}

# Keyed on (region, industry) rather than on the ticker, because the screen is a
# property of the industry and every name in one shares it. `/api/score/batch`
# fans a whole watchlist across a thread pool (`main.score_batch`), so a
# ticker-keyed cache would put fifty concurrent unauthenticated screens on Yahoo
# for fifty REITs where one will do. The target is removed at read time instead,
# which is the only part of the answer that varies by name.
_SCREENED_INDUSTRY_CACHE: dict[tuple[str, str], list[str]] = {}


# Where OpenBB keeps its credentials. Computed rather than imported from
# `openbb_core.app.constants`, which holds the same value: `requirements-test.txt`
# deliberately does not install OpenBB, so a module-scope import of it aborts
# collection of every test module that reaches this file — five of them, on
# 2026-08-28, found by CI after a local run passed because the dev venv has the
# runtime set installed. Measuring that the import was fast (0.00 s) said nothing
# about whether it was there.
#
# `test_the_settings_path_still_matches_openbbs_own` pins the two together
# wherever OpenBB *is* installed, and skips where it is not.
USER_SETTINGS_PATH = Path.home() / ".openbb_platform" / "user_settings.json"


# How the last real FMP call went: None until one has been made, then "ok" or
# "failed". Reported by /api/health, because until 2026-08-28 a key that was
# present and not working was indistinguishable from no key at all — a bad key,
# an exhausted free quota, an FMP outage and a ticker that genuinely has no
# peers all arrived here as the same `return []` and the same silence.
_FMP_LAST_CALL: str | None = None


def fmp_status() -> dict:
    """Whether an FMP key is configured, and how the last real call went.

    `configured` is resolved the way OpenBB resolves it — `FMP_API_KEY` in the
    environment wins over `credentials.fmp_api_key` in the settings file — but by
    reading both here rather than asking OpenBB, which costs seconds this cannot
    spend: `/health` is polled every 30 s by every open tab.

    A malformed or unreadable settings file reports `False`, which is the useful
    answer: OpenBB would not have got a key out of it either.

    Never returns the key, any part of it, or any message that might carry it.
    This endpoint has no authentication.
    """
    configured = bool(os.environ.get("FMP_API_KEY"))
    if not configured:
        try:
            with open(USER_SETTINGS_PATH, encoding="utf-8") as f:
                configured = bool(json.load(f).get("credentials", {}).get("fmp_api_key"))
        except (OSError, ValueError, AttributeError):
            configured = False
    return {"configured": configured, "last_call": _FMP_LAST_CALL}


class CredentialFileError(RuntimeError):
    """The settings file exists and cannot be edited without losing what is in it."""


# One real call, on an explicit save, to answer "did that work?" while the person
# who typed it is still looking. AAPL because FMP certainly knows it: a probe that
# fails for being obscure would read as a rejected key.
_FMP_PROBE = "AAPL"


def _write_settings(data: dict) -> None:
    """Replace the settings file atomically, keeping one generation behind it.

    `os.replace` is atomic on both POSIX and Windows, so a crash mid-write leaves
    the original intact rather than a truncated file with somebody's credentials
    half in it.

    The `.bak` exists because the first version of this had no undo. On
    2026-08-28 a key typed to try the feature out replaced a real one, and there
    was nothing on disk to restore from — the atomic write had already consumed
    its own temporary file. Everything above this line was careful about the
    *other* fields in the file and careless about the one being changed.
    """
    path = Path(USER_SETTINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(".json.bak")
        backup.write_bytes(path.read_bytes())
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # no-op on Windows; the file holds credentials
    except OSError:
        pass
    os.replace(tmp, path)


def _load_settings() -> dict:
    """The current settings, or {} if there is no file yet.

    Raises rather than returning {} when the file exists and cannot be parsed.
    Returning {} there would mean the next write silently replaces whatever is in
    it — and it is not this app's file. Measured on the development machine
    before this was written: a `tiingo_token` alongside the FMP key, plus
    `preferences` and `defaults`. Losing an unrelated credential to a
    convenience feature is not a trade worth making, so this stops instead.
    """
    path = Path(USER_SETTINGS_PATH)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CredentialFileError(
            f"{path} exists but could not be read as JSON ({type(e).__name__}). "
            "Fix or delete it by hand — refusing to overwrite it, because it may "
            "hold credentials for other providers.") from e
    if not isinstance(data, dict):
        raise CredentialFileError(f"{path} is valid JSON but not an object.")
    return data


def _running_openbb():
    """The `obb` of an already-imported OpenBB, or None. Never imports."""
    mod = sys.modules.get("openbb")
    return getattr(mod, "obb", None) if mod is not None else None


def _import_openbb():
    """Import OpenBB, paying its ~5 s cost. Only for an explicit save.

    Verifying a key needs the credential set on the live object, and the live
    object does not exist until this runs. A save is a button press, not a page
    load, so the wait is the user's own and it buys the answer they asked for.
    """
    try:
        from openbb import obb
        return obb
    except Exception:
        return None


def _apply_to_running_openbb(key: str | None) -> None:
    """Update an already-imported OpenBB, which will not re-read the file.

    Only when it is already in `sys.modules`: importing it here would cost 5 s on
    a request whose work is otherwise a file write. If it has not been imported,
    the first import reads the file. Used by the delete path; `save_fmp_key` sets
    the credential itself, because it has to set it *before* the check.
    """
    obb = _running_openbb()
    if obb is None:
        return
    try:
        obb.user.credentials.fmp_api_key = key
    except Exception:
        pass  # best effort; the file is the source of truth on next start


def save_fmp_key(key: str) -> dict:
    """Verify the key first, and only write it to disk if it works.

    The first version wrote and *then* checked. That order cost a real key on
    2026-08-28: a placeholder typed to see what the tab did replaced a working
    one, the probe correctly said "failed", and by then the working key was gone.
    Reporting a failure accurately is no use if the report arrives after the
    damage.

    So the candidate goes no further than OpenBB's in-memory credential until a
    real call has come back. On a rejection nothing on disk changes, the previous
    in-memory credential is put back, and `_FMP_LAST_CALL` is restored too — that
    verdict belonged to the candidate, and a key that was never adopted should
    not leave its verdict on the one that is still stored.

    Returns `fmp_status()` plus `saved`, because "your key is failing" and "the
    key you just typed was rejected and nothing changed" are different sentences
    and the caller has to be able to tell them apart.
    """
    global _FMP_LAST_CALL
    key = (key or "").strip()
    if not key:
        raise ValueError("An empty key is not a key. Use the delete path to remove one.")

    # Before anything else, so an unreadable file fails without a network call.
    data = _load_settings()

    obb = _running_openbb() or _import_openbb()
    if obb is None:
        raise CredentialFileError(
            "OpenBB is not installed in this environment, so a key cannot be "
            "verified — and this refuses to store one it could not check.")

    previous_key = obb.user.credentials.fmp_api_key
    previous_verdict = _FMP_LAST_CALL
    obb.user.credentials.fmp_api_key = key

    _FMP_PEER_CACHE.pop(_FMP_PROBE, None)
    _fmp_peers(_FMP_PROBE)
    _FMP_PEER_CACHE.pop(_FMP_PROBE, None)

    if _FMP_LAST_CALL != "ok":
        obb.user.credentials.fmp_api_key = previous_key
        _FMP_LAST_CALL = previous_verdict
        return {**fmp_status(), "saved": False}

    data.setdefault("credentials", {})["fmp_api_key"] = key
    _write_settings(data)
    return {**fmp_status(), "saved": True}


def clear_fmp_key() -> dict:
    """Remove the key, leaving the rest of the file as it was."""
    global _FMP_LAST_CALL
    data = _load_settings()
    creds = data.get("credentials")
    if isinstance(creds, dict):
        creds.pop("fmp_api_key", None)
        _write_settings(data)
    _apply_to_running_openbb(None)
    # The verdict belonged to a key that is gone; keeping it would report on
    # something no longer configured.
    _FMP_LAST_CALL = None
    _FMP_PEER_CACHE.pop(_FMP_PROBE, None)
    return fmp_status()


def _fmp_peers(ticker: str) -> list[str]:
    """FMP peer discovery — free tier, no extra key beyond the configured one.

    Successes are cached for the process lifetime; failures are **not**, so a
    transient outage does not permanently blank a ticker's peers (same rule as
    data_provider._us_treasury_10y).

    Also records the outcome in `_FMP_LAST_CALL` for `fmp_status`. A cache hit
    deliberately records nothing: it did not call FMP, so it has no news.
    """
    global _FMP_LAST_CALL
    if ticker in _FMP_PEER_CACHE:
        return _FMP_PEER_CACHE[ticker]

    try:
        # deferred: importing openbb costs ~5 s, so only a request that actually
        # needs discovery pays it, and only once per process
        from openbb import obb
        from openbb_core.provider.utils.errors import EmptyDataError
    except Exception:
        _FMP_LAST_CALL = "failed"
        return []

    try:
        rows = obb.equity.compare.peers(symbol=ticker, provider="fmp").results
        peers = [r.symbol for r in rows if getattr(r, "symbol", None)][:MAX_AUTO_PEERS]
    except EmptyDataError:
        # The call reached FMP and FMP said this ticker has no peers. That is the
        # key working, and recording it as a failure would report a good key as
        # broken — worse than reporting nothing, which is what this replaced.
        _FMP_LAST_CALL = "ok"
        return []
    except Exception:
        # The status only, never the message. FMP takes the key as an `?apikey=`
        # query parameter, so a raised URL can carry it, and this ends up in an
        # unauthenticated /health response.
        _FMP_LAST_CALL = "failed"
        return []

    _FMP_LAST_CALL = "ok"
    if peers:
        _FMP_PEER_CACHE[ticker] = peers
    return peers


def _screener_peers(ticker: str) -> list[str]:
    """Same-industry names from yfinance's screener. No API key of any kind.

    The tier below FMP, and the only one that works on an install carrying no
    credentials — which is every install but the author's. Without it, a ticker
    outside the 23-name curated map gets no peers at all, and that is not a
    degraded comps table but a missing half of the product: no peer medians, no
    "Peer multiples" bar on the football field, and `triangulate` left with one
    method, at which point it declines to report an overlap or a conviction at
    all. A cloned repo is in that state today for everything but those 23.

    Ordered *below* FMP deliberately. Above it, this would change the answer for
    anyone who does hold a key; below it, it can only fill a gap that is
    currently empty — which is what makes the tier shippable without first
    re-measuring FMP's peer quality across a panel.

    The screen itself is cached by industry rather than by ticker — see
    `_screened_industry` — so this is the cheap half: classify the target,
    drop it from its own industry's ranking, take the top few.
    """
    try:
        # The target's own classification, read through the TTL-cached snapshot
        # rather than passed in: `peer_beta_inputs` and the /peers endpoint both
        # reach here with nothing but a ticker.
        industry = _SCREENER_INDUSTRY.get(
            provider.get_peer_snapshot(ticker).get("industry"))
    except Exception:
        return []  # unknown ticker, or the provider is having a bad day
    if industry is None:
        return []
    # Suffix-based, and it inherits the limit `data_provider.home_index` already
    # documents for the same rule: a US-listed ADR of a Hong Kong company still
    # screens as `us`.
    region = "hk" if ticker.upper().endswith(".HK") else "us"
    t = ticker.upper()
    # `O` and `0700.HK` both come back at the top of their own screen. Removed
    # here rather than inside the cached ranking, because it is the one part of
    # the answer that differs between two names in the same industry.
    return [s for s in _screened_industry(region, industry)
            if s.upper() != t][:MAX_AUTO_PEERS]


def _screened_industry(region: str, industry: str) -> list[str]:
    """Symbols in one region and industry, market-cap ranked. Cached per process.

    Successes are cached for the process lifetime and failures are not, the same
    rule as `_fmp_peers` and for the same reason.
    """
    key = (region, industry)
    if key in _SCREENED_INDUSTRY_CACHE:
        return _SCREENED_INDUSTRY_CACHE[key]
    try:
        rows = yf.screen(
            yf.EquityQuery("and", [
                yf.EquityQuery("eq", ["region", region]),
                yf.EquityQuery("eq", ["industry", industry]),
            ]),
            sortField="intradaymarketcap", sortAsc=False, size=SCREENER_SIZE,
        )["quotes"]
    except Exception:
        return []  # network, quota, or a shape change in an unofficial scraper

    # Two filters, each for a row the live screener really returns — measured
    # 2026-08-19 over 50 rows per industry across all seven fixtures.
    #
    # market cap: `SPG-PJ`, a Simon Property preferred, reports
    #   `quoteType=EQUITY` with a null market cap. quoteType cannot separate a
    #   preferred from its common, so the missing cap is the only signal — and
    #   `comps_analysis` discards a capless peer downstream regardless.
    # OTC: where every cross-listing sits — `TOYOF` beside `TM`, `BYDDF` beside
    #   `BYDDY`, `UNBLF` beside `URMCY`. Left in, one company votes two or three
    #   times in a median. Matched on `fullExchangeName` rather than the
    #   `exchange` code on purpose: OTC arrives under **four** codes, and a
    #   filter written against the obvious one (`PNK`) let `WMMVF` and `WMMVY`
    #   — both Walmart de México — through as two of Costco's four peers.
    #   Measured 2026-08-19 over 36 screens — 18 industries x 2 regions,
    #   1,162 rows: PNK 412, OQX 23, OID 9, OQB 3. Every one is named
    #   "OTC Markets ...", and `fullExchangeName` was on all 1,162.
    #
    #   This also drops foreign names that are *not* duplicates (`STGPF`,
    #   Scentre Group, an Australian retail REIT), and that is the intended
    #   answer rather than a side effect: a peer should trade where the target
    #   trades, and judging that case by case is not work a fallback tier
    #   should be doing.
    symbols = [r["symbol"] for r in rows
               if r.get("symbol") and r.get("marketCap")
               and not (r.get("fullExchangeName") or "").startswith("OTC Markets")]
    if symbols:
        _SCREENED_INDUSTRY_CACHE[key] = symbols
    return symbols


def suggest_peers(ticker: str) -> list[str]:
    """Curated list when we have one, then FMP, then the keyless screener."""
    if DEMO_MODE:
        # The only guard that cannot live in `data_provider`, and the only one
        # of the three tiers that is a *judgement* rather than a fetch: the
        # curated dict is static, but `_fmp_peers` is an OpenBB call needing a
        # credential and `_screener_peers` is a live yfinance screen, and three
        # of the eight demo tickers (`O`, `RIVN`, `0002.HK`) carry no curated
        # list, so both live tiers are reachable from an ordinary page load.
        #
        # Returns nothing rather than the curated names. Those are real peers
        # but demo mode holds no data for them, and one resolvable peer out of
        # four — AAPL's list contains MSFT — would draw a median over a single
        # company, which looks like a comparison and is not one. A peer named
        # explicitly through `peer_list` still resolves if it is one of the
        # eight.
        return []
    t = ticker.upper()
    return PEER_SUGGESTIONS.get(t) or _fmp_peers(t) or _screener_peers(t)


def peer_beta_inputs(ticker: str) -> list[dict]:
    """Suggested peers' snapshots, for financial_models.resolve_beta.

    Returns whole snapshots rather than bare betas because resolve_beta unlevers
    each peer beta before taking the median, which needs that peer's own
    `total_debt` and `market_cap` — both already on the snapshot.

    Reads through the TTL-cached peer snapshot, so on a warm cache this costs
    nothing. Callers should only reach for this when the company's own reported
    beta is not credible — see main.py.
    """
    out = []
    for p in suggest_peers(ticker):
        try:
            snap = provider.get_peer_snapshot(p)
        except Exception:
            continue
        if snap.get("beta") is not None:
            out.append(snap)
    return out


def _pct(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.1%}"


def _ev_revenue_transfers(target_margin: float | None,
                          peer_margin: float | None) -> bool:
    """Whether a peer EV/Revenue multiple can be carried onto the target.

    A revenue multiple is a margin assumption wearing a multiple's clothes: two
    businesses on identical revenue and different margins do not deserve the
    same EV/Sales. Measured live 2026-08-12 on 0700.HK, the curated peer set's
    median operating margin was **5.7%** (9988 1.0%, 3690 -7.5%, 1024 10.5%)
    against Tencent's **34.3%**, and the peer median 1.84x revenue multiple
    implied **189.61** a share against a 439-471 cluster from every other
    multiple. That one number stretched the football-field bar to 2.48x wide and
    was the sole reason its verdict still read "in range" — a bar that broad
    contains any price, which is exactly the criticism the DCF bar was already
    fixed for.

    Comparability is *verified rather than assumed*, the same shape as the P/B
    sector gate below: an unknown margin on either side means no multiple. The
    one exception is a peer set and a target that are both loss-making, where
    EV/Sales is the conventional multiple precisely because earnings are not
    available yet — `sector_weights.pre_profit_growth` scores `ev_sales` for the
    same reason.
    """
    if target_margin is None or peer_margin is None:
        return False
    if target_margin <= 0 or peer_margin <= 0:
        return target_margin <= 0 and peer_margin <= 0
    return 1 / EV_REVENUE_MARGIN_TOLERANCE <= target_margin / peer_margin \
        <= EV_REVENUE_MARGIN_TOLERANCE


def comps_analysis(target_fund: dict, peer_tickers: list[str]) -> dict:
    """Comps table + peer-median-implied share values for the target."""
    info = target_fund["info"]
    # Target and peers alike are restated onto one currency before anything is
    # compared or medianed. Correcting only one side would be worse than
    # correcting neither: an all-HK peer set carries the same vendor mismatch,
    # so a corrected target beside uncorrected peers would read 10% cheap purely
    # on FX. See fm.ev_multiple_one_currency.
    target_ev_ebitda, target_ev_revenue = fm.ev_multiples_for(info)
    target_row = {
        "ticker": target_fund["ticker"],
        "name": info.get("longName"),
        "market_cap": info.get("marketCap"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "ev_to_ebitda": target_ev_ebitda,
        "ev_to_revenue": target_ev_revenue,
        "peg_ratio": info.get("pegRatio"),
        "operating_margin": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
    }

    peers, failed = [], []
    for p in peer_tickers[:8]:
        try:
            snap = provider.get_peer_snapshot(p)
            if snap["market_cap"] is None:
                failed.append(p)
            else:
                # Each peer carries its own pair — an HK peer set mixes
                # HKD-reporting and CNY-reporting names, so the rate is per peer
                # and not the target's.
                for key in ("ev_to_ebitda", "ev_to_revenue"):
                    snap[key] = fm.ev_multiple_one_currency(
                        snap.get(key), snap.get("currency"), snap.get("financial_currency"))
                peers.append(snap)
        except Exception:
            failed.append(p)

    # The count behind each median, not just the peer count. They differ: a peer
    # whose multiple is negative or missing is filtered by the positive-only rule
    # below but still counts as a resolved peer, so "4 peers" can mean a median
    # of 3. Measured 2026-08-12, 0700.HK's EV/EBITDA median rested on three of
    # its four peers — 3690.HK reported -12.505.
    medians, median_n = {}, {}
    for key in MULTIPLE_KEYS:
        vals = [p[key] for p in peers if p[key] is not None and p[key] > 0]
        medians[key] = round(median(vals), 2) if vals else None
        median_n[key] = len(vals)

    # apply peer-median multiples to the target's own metrics
    shares = info.get("sharesOutstanding")
    net_debt = (info.get("totalDebt") or 0) - (info.get("totalCash") or 0)
    implied = {}

    # An EV multiple times a statement figure lands in the reporting currency,
    # as does net debt, so the bridged per-share value has to be converted before
    # it can sit on a football field beside a trading-currency price. The
    # earnings multiples below need no conversion: EPS is already trading-currency.
    fx, fx_mismatch = fm.statement_to_market_fx(
        info.get("currency"), info.get("financialCurrency"))

    def ev_implied(mult, metric):
        """Peer-median EV multiple -> implied share price.

        **Net debt only, and deliberately not the DCF's five-term bridge.** This
        looks like an inconsistency beside the Financial Models tab and is not
        one; it was recorded as a defect in TODOLIST until 2026-08-18 and the
        proposed fix would have introduced a real error.

        The multiples on both sides are the vendor's `enterpriseToEbitda` /
        `enterpriseToRevenue`, so the equity conversion has to invert whatever
        definition of enterprise value the vendor used.

        **What is established.** The vendor does not deduct non-operating assets.
        AAPL carries 77.7bn of `Investmentin Financial Assets` while its
        `enterpriseValue` sits 127k -- five orders of magnitude smaller -- from
        `market cap + total debt - total cash`. So adding the bridge's
        `marked_securities` here would double-count: a peer's market cap already
        prices that peer's non-operating assets, so their value is inside the
        median multiple, and adding the target's again on top counts them twice.
        On 0700.HK that term alone is +77.65 per share on a 481 price, 16.1%.
        It is also the dominant term, which is why the decision rests on it.

        **What is not established, and was over-claimed here until 2026-08-18.**
        Whether the vendor also folds in minority interest and preferred stock.
        `enterpriseValue == market cap + debt - cash` holds to the cent on AAPL
        and MSFT and fails by 4.3% on JPM and 2.3% on O. The two names it holds
        on are precisely the two whose balance sheets carry zero minority
        interest and zero preferred -- the only two where "net debt only" and
        "net debt plus those terms" are the same arithmetic, so they cannot
        distinguish the two hypotheses. JPM's 21.04bn residual is within 5% of
        its 20.05bn of preferred stock, which points the other way. The exact
        vendor formula is not recoverable from seven fixtures.

        Net debt only is therefore the right call on the term that dominates and
        the honest default on the terms that are unresolved -- not, as this
        docstring first claimed, a proven inversion in every term.

        The DCF bar may use the full bridge because its enterprise value comes
        from discounted FCFF, which contains *only* operating cash flows. The two
        bars therefore rest on two different definitions of enterprise value, and
        that difference is disclosed on the chart rather than averaged away.
        """
        if mult and metric and shares and fx is not None:
            return round((mult * metric - net_debt) * fx / shares, 2)
        return None

    if medians.get("pe_forward") and info.get("forwardEps"):
        implied["peer_forward_pe"] = round(medians["pe_forward"] * info["forwardEps"], 2)
    if medians.get("pe_trailing") and info.get("trailingEps"):
        implied["peer_trailing_pe"] = round(medians["pe_trailing"] * info["trailingEps"], 2)
    implied["peer_ev_ebitda"] = ev_implied(medians.get("ev_to_ebitda"), info.get("ebitda"))

    # EV/Revenue only where the margins make it a comparison — see
    # `_ev_revenue_transfers`. Suppression is recorded rather than silent,
    # because a missing multiple that nobody explains reads as missing data.
    suppressed: dict[str, str] = {}
    peer_margins = [p["operating_margin"] for p in peers
                    if p.get("operating_margin") is not None]
    peer_margin = median(peer_margins) if peer_margins else None
    if _ev_revenue_transfers(info.get("operatingMargins"), peer_margin):
        implied["peer_ev_revenue"] = ev_implied(medians.get("ev_to_revenue"),
                                                info.get("totalRevenue"))
    elif medians.get("ev_to_revenue"):
        suppressed["peer_ev_revenue"] = (
            "Operating margin "
            f"{_pct(info.get('operatingMargins'))} against a peer median of "
            f"{_pct(peer_margin)} — a revenue multiple does not transfer across "
            "that gap.")

    # P/B-implied value is only meaningful for balance-sheet-driven sectors
    if info.get("sector") in ("Financial Services", "Real Estate") \
            and medians.get("price_to_book") and info.get("bookValue"):
        implied["peer_price_to_book"] = round(medians["price_to_book"] * info["bookValue"], 2)
    implied = {k: v for k, v in implied.items() if v is not None and v > 0}

    return {
        "target": target_row,
        "peers": peers,
        "failed_tickers": failed,
        "peers_used": len(peers),
        "peer_medians": medians,
        "peer_medians_n": median_n,
        "peer_operating_margin": peer_margin,
        "implied_values": implied,
        "suppressed_multiples": suppressed,
        "implied_range": {
            "low": min(implied.values()) if implied else None,
            "high": max(implied.values()) if implied else None,
        },
    }


def _dcf_band(dcf: dict) -> tuple[float, float, str] | None:
    """(low, high, basis) for the DCF bar, or None when the grid is empty.

    The 25th-75th percentile of the sensitivity grid, per the reference doc's
    football-field spec (§5.2), not the grid's min/max. The grid's corners are
    the compounded worst and best case of two assumptions moved together, so
    min/max produced a bar roughly twice as wide as the band the method actually
    supports: measured 2026-08-07, AAPL 55.27 -> 26.73, MSFT 132.95 -> 64.00,
    0700.HK 330.00 -> 149.08.

    The grid alone understates the DCF, though, because it stresses WACC and
    terminal growth — the two *second-order* assumptions — while holding the
    first-order one fixed. `growth_sensitivity` carries the base rate swept
    +/-4pp, and its full span is unioned in rather than pooled into the
    quartiles: five growth points against twenty-five grid cells would barely
    move a quartile, which would hide exactly the driver the band exists to
    show. Measured live 2026-08-12 on 0700.HK, the grid alone gave 606.74-778.12
    and a confident "price below"; growth from 9.38% to 4% alone gives 502.96,
    which is the assumption the verdict actually rests on.
    """
    vals = sorted(v for row in dcf["sensitivity"]["rows"]
                  for v in row["values"] if v is not None)
    if not vals:
        return None
    if len(vals) >= 4:
        low, high = quantiles(vals, n=4)[0], quantiles(vals, n=4)[2]
        basis = "sensitivity 25th–75th"
    else:
        low, high = min(vals), max(vals)
        basis = "sensitivity range"
    growth = [v for v in (dcf.get("growth_sensitivity") or {}).get("values", [])
              if v is not None]
    if growth:
        extended_low, extended_high = min(growth) < low, max(growth) > high
        low, high = min(low, *growth), max(high, *growth)
        # Name only the sides the sweep actually reached. A flat "+ growth" read
        # as a symmetric stress even where the sweep contributed to one end and
        # nothing to the other, which is how a one-sided band used to pass for a
        # balanced one.
        if extended_low and extended_high:
            basis += " + growth"
        elif extended_low:
            basis += " + growth (downside only)"
        elif extended_high:
            basis += " + growth (upside only)"

    # The base year is the third assumption in the bar, and until now the only
    # one it did not carry. Both sweeps above move a *rate* while holding the
    # level they are applied to fixed, so neither can express what the starting
    # year being unrepresentative would do — and a level error in base FCF is
    # undamped, since fair value is homogeneous of degree one in it.
    #
    # This is the union, not a substitution: the tick stays on the reported-year
    # answer, and `enterprise_value(..., base=normalised)` is the other end of a
    # band the platform declines to choose between. Measured on the fixtures
    # (risk-free pinned at 4.3%, CNY/HKD at 1.10) it widens upward for XOM
    # 157.30 -> 221.14 and MSFT 269.64 -> 347.53, and *downward* for 0700.HK
    # 469.48 -> 448.17. That it is not one-directional is the whole reason it
    # can be shown without taking a view: a rule that only ever raised the value
    # would be price tuning wearing a band's clothes.
    #
    # Figures refreshed 2026-08-18. They were 71.75 -> 102.17, 248.51 -> 321.75
    # and 663.32 -> 628.00, measured before beta became a regression on
    # 2026-08-14; that change alone was worth about +105% on XOM. The direction
    # of each — and so the argument above — is unchanged.
    normalised = ((dcf.get("diagnostics") or {}).get("base_year") or {}).get(
        "fair_value_normalised")
    # `> 0` for the same reason price_gap_bridge uses it: a normalised
    # enterprise value below net debt gives a negative per-share figure, and a
    # bar stretched to it would be unreadable rather than merely wide.
    if normalised is not None and normalised > 0:
        # One value can only ever reach one side, so the growth sweep's
        # two-sided wording does not transfer. Naming it only when it actually
        # widened the bar keeps the same rule: the basis lists what moved the
        # edges, and a normalised figure already inside the band moved nothing.
        if normalised < low or normalised > high:
            basis += " + base year"
        low, high = min(low, normalised), max(high, normalised)
    return round(low, 2), round(high, 2), basis


def _clamped_mid(mid, low: float, high: float):
    """A midpoint tick that cannot render outside its own bar.

    `mid` is the model's base-case answer rather than the band's centre, which
    is the right number to show — but nothing guarantees it lands inside a band
    built from quantiles over a grid with dropped cells, and the chart positions
    the tick with no bounds check of its own.
    """
    return None if mid is None else min(max(mid, low), high)


def football_field(target_fund: dict, dcf: dict, comps: dict,
                   classification: str | None = None) -> list[dict]:
    """Valuation ranges from each method, for the range chart.

    `classification` gates the DCF row. Without it the only test available was
    "did the model return a number", which is the test `scoring.dcf_applicable`
    exists to replace: a REIT's `CFO - CapEx` is positive, so its DCF does not
    error, and the chart drew it a confident bar and a verdict of the same
    visual weight as a valid one — while the Financial Models tab, one tab away,
    suppressed the same number. Passing None keeps the old behaviour for callers
    that cannot classify.
    """
    info = target_fund["info"]
    ranges = []

    if classification is not None and not sector_weights.dcf_applies(classification):
        ranges.append({
            "method": "DCF", "not_applicable": True,
            "reason": f"A discounted-cash-flow valuation does not apply to a "
                      f"{classification.replace('_', ' ')}.",
        })
    elif dcf and not dcf.get("error"):
        band = _dcf_band(dcf)
        if band:
            low, high, basis = band
            ranges.append({"method": f"DCF ({basis})", "low": low, "high": high,
                           "mid": _clamped_mid(dcf.get("fair_value_per_share"), low, high),
                           "independent": dcf.get("assumptions", {}).get("growth_source")
                           != "analyst_consensus_fwd"})

    imp = comps.get("implied_values", {})
    if imp:
        # The envelope is min/max across structurally different multiples, so a
        # single one that does not transfer sets the whole width — the same
        # defect the DCF bar was fixed for. The verdict is taken from the
        # interquartile core instead, and the envelope is kept alongside it so a
        # reader can still see the full spread.
        vals = sorted(imp.values())
        core_low, core_high = (
            (quantiles(vals, n=4)[0], quantiles(vals, n=4)[2]) if len(vals) >= 4
            else (min(vals), max(vals)))
        # Only where a DCF bar was actually drawn, because that is the only case
        # in which the chart invites the comparison. For a bank or a REIT there
        # is no second bar and no basis difference to explain. See `ev_implied`
        # for why the two bases are both correct rather than one being a bug.
        dcf_drawn = any(r["method"].startswith("DCF") and r.get("low") is not None
                        for r in ranges)
        ranges.append({
            "method": "Peer multiples (implied)",
            "equity_basis_note": (
                "Converted to equity by subtracting net debt only, because these are "
                "the data vendor's multiples and its enterprise value does not deduct "
                "non-operating assets. The DCF bar uses a fuller bridge, since it "
                "discounts operating cash flows and those assets sit outside them — "
                "applying that same bridge here would count them twice."
            ) if dcf_drawn else None,
            "low": round(core_low, 2), "high": round(core_high, 2),
            "mid": round(median(vals), 2),
            "envelope_low": min(vals), "envelope_high": max(vals),
            "peers_used": comps.get("peers_used"),
            # the weakest median behind any multiple actually plotted
            "peers_min": min((( comps.get("peer_medians_n") or {})
                              .get(IMPLIED_TO_MULTIPLE.get(k), 0) for k in imp),
                             default=None),
            "multiples_used": len(vals),
            "suppressed": comps.get("suppressed_multiples") or {},
            "independent": True,
        })

    if info.get("targetLowPrice") and info.get("targetHighPrice"):
        # Context only, never averaged: the reference doc gives analyst targets
        # 0% weight (§5.2), and a target is where the sell-side thinks the price
        # is going rather than an independent valuation of the business. Below
        # four contributing analysts it is not even a range.
        n = info.get("numberOfAnalystOpinions") or 0
        if n >= MIN_ANALYST_OPINIONS:
            low, high = info["targetLowPrice"], info["targetHighPrice"]
            mean = info.get("targetMeanPrice")
            # The width is kept even though the range itself does not vote:
            # disagreement among n informed forecasters is a measure of how
            # uncertain this company's outlook is, which nothing else here
            # captures. Against the mean rather than the price, so it measures
            # the analysts rather than the market's distance from them.
            dispersion = (high - low) / mean if mean else None
            ranges.append({"method": "Analyst targets",
                           "low": low, "high": high, "mid": mean,
                           "context_only": True, "analysts": n,
                           "dispersion": round(dispersion, 4) if dispersion is not None else None,
                           "dispersion_band": None if dispersion is None
                           else "tight" if dispersion < ANALYST_DISPERSION_TIGHT
                           else "moderate" if dispersion < ANALYST_DISPERSION_WIDE else "wide"})

    # A range whose ends coincide is one estimate, not a range. It has to be
    # drawn at a minimum width to be visible at all, so it is flagged here and
    # labelled there rather than passing for a narrow-but-real band.
    for r in ranges:
        if r.get("low") is not None and r["low"] == r["high"]:
            r["degenerate"] = True

    return ranges


def triangulate(ranges: list[dict]) -> dict:
    """Where the methods agree, and how much that agreement is worth.

    The football field's own spec says the point of the chart is the **overlap
    zone** (reference doc §5.2: "the overlap zone is the defensible fair-value
    band"), and the project's quant review endorses the chart only as "the
    intersection of the three methods". Neither existed: the chart drew bars and
    per-method verdicts, so a reader could not distinguish three methods
    agreeing from three methods that happen to straddle the price.

    Analyst targets are excluded from both the overlap and the conviction score.
    The spec gives them 0% weight, and a target range is a forecast of the price
    rather than a valuation of the business — including it would let the thing
    being tested vote on its own test.

    Returns `overlap: None` when the ranges are disjoint. That is not a failure;
    it is the most informative state the chart has, and the one it previously
    could not express.
    """
    scored = [r for r in ranges if not r.get("not_applicable")
              and not r.get("context_only") and r.get("low") is not None]
    mids = [r["mid"] if r.get("mid") is not None else (r["low"] + r["high"]) / 2
            for r in scored]

    analyst = next((r for r in ranges if r.get("context_only")), None)
    out = {
        "methods_scored": [r["method"] for r in scored],
        "overlap": None,
        "conviction": None,
        "midpoint_spread": None,
        "diverged": False,
        "anchors": None,
        # Carried alongside conviction, never inside it: conviction measures
        # whether the *methods* agree, dispersion whether the *forecasters* do.
        # Wide dispersion with tight method agreement is a real and different
        # state from the reverse, and one number cannot say both.
        "analyst_dispersion": (analyst or {}).get("dispersion"),
        "analyst_dispersion_band": (analyst or {}).get("dispersion_band"),
        "analysts": (analyst or {}).get("analysts"),
    }
    if len(scored) < 2:
        # One method is not a triangulation. The intersection of a single range
        # is that range, which would render as an "agreement zone" nothing
        # agreed on — and a conviction grade off one bar is the false precision
        # the spec warns about. A REIT reaches here by design: its DCF row is
        # not applicable, leaving peer multiples alone.
        return out

    low = max(r["low"] for r in scored)
    high = min(r["high"] for r in scored)
    if low <= high:
        out["overlap"] = {"low": round(low, 2), "high": round(high, 2)}

    lo_i, hi_i = mids.index(min(mids)), mids.index(max(mids))
    spread = (mids[hi_i] - mids[lo_i]) / mids[lo_i] if mids[lo_i] else None
    if spread is None:
        return out
    out["midpoint_spread"] = round(spread, 4)
    out["conviction"] = ("HIGH" if spread <= CONVICTION_HIGH
                         else "MEDIUM" if spread <= CONVICTION_MEDIUM else "LOW")
    out["diverged"] = spread > DIVERGENCE_CALLOUT
    out["anchors"] = {
        "low_method": scored[lo_i]["method"], "low_mid": round(mids[lo_i], 2),
        "high_method": scored[hi_i]["method"], "high_mid": round(mids[hi_i], 2),
    }
    return out


def price_gap_bridge(dcf: dict, price: float | None) -> dict | None:
    """The distance from the DCF to the price, decomposed into named steps.

    Measured across eleven names, the conviction grade came out LOW every time
    and the overlap zone was non-empty once. A grade that never varies carries
    no information, however correctly it is computed — so the chart stopped
    leading with it. What a reader actually needs is not a letter but the
    arithmetic: here is our number, here is what the one adjustment we can
    justify does to it, here is the price, and here is what remains.

    The residual is the point. It is labelled as unexplained rather than
    absorbed into a fudge, because it is not a modelling error — it is the
    market pricing a longer competitive-advantage period, a lower discount rate
    or a higher terminal cash conversion than a ten-year fade at 2.5% can
    express. Naming the size of that bet is the honest output. Closing it by
    tuning the model would make the DCF an expensive way to display the price.

    Only the base-year step appears, because it is the only adjustment the
    platform can compute from filed data today. Rows for non-operating assets or
    for the interest-income double-count are deliberately absent rather than
    stubbed at zero: an empty line implies a check was run.
    """
    if dcf.get("error"):
        return None
    fair_value = dcf.get("fair_value_per_share")
    if not fair_value or not price:
        return None

    steps = [{"label": "Our DCF fair value, on the reported base year",
              "value": fair_value, "kind": "start"}]
    adjusted = fair_value

    base_year = (dcf.get("diagnostics") or {}).get("base_year") or {}
    normalised = base_year.get("fair_value_normalised")
    # `> 0` rather than `is not None`: a normalised enterprise value below net
    # debt gives a negative adjusted figure, and every percentage measured
    # against it afterwards is nonsense — "the market is 340% above a value of
    # -12". A leveraged company whose newest year ran above its own average can
    # reach that. The step is dropped rather than shown, since the bridge would
    # otherwise end in a number the reader cannot interpret.
    if normalised is not None and normalised > 0 and base_year.get("ratio_to_mean"):
        steps.append({
            "label": (f"If the base year ran at this company's own "
                      f"{base_year['periods']}-year average margin "
                      f"({base_year['ratio_to_mean']}x today)"),
            "value": round(normalised - fair_value, 2),
            "kind": "adjustment",
        })
        adjusted = normalised

    residual = round(price - adjusted, 2)
    return {
        "steps": steps,
        "adjusted": round(adjusted, 2),
        "price": price,
        "residual": residual,
        # Against the adjusted value, not against the price: the question is how
        # far our number would have to move, not how far the market's would.
        "residual_pct": round((price / adjusted - 1) * 100, 1) if adjusted else None,
        "residual_direction": "market_above" if residual > 0 else "market_below",
    }


def reconciling_growth(target_fund: dict, target_value: float,
                       peers: list[dict] | None = None) -> float | None:
    """The growth rate at which the DCF would agree with `target_value`.

    This is the answer to "the methods disagree, now what". The reference doc
    forbids averaging two anchors that diverge (§5.2: "do not average into false
    precision — report both anchors and the assumption that separates them"),
    and the project's own quant review ranks back-solving the DCF's assumptions
    as the single most valuable thing the platform does. Naming the growth rate
    that reconciles the two turns an unanswerable question — which bar do I
    believe — into one the reader can actually research.

    Measured live 2026-08-12 on 0700.HK: the DCF's 682.40 sits 52.7% above the
    peer-multiple core, the model is compounding at 9.38% taken from analyst
    consensus, and the two methods meet at roughly 4%.

    None means the target lies outside what any rate in the model's own
    validity range can produce, which is itself worth saying.

    The bisection lives in `financial_models.solve_for_fair_value`, shared with
    the price reconciliation that back-solves the same model against the market
    rather than against the peers.
    """
    return fm.solve_for_fair_value(
        target_fund, target_value, "growth_rate",
        fm.GROWTH_VALIDITY_RANGE[0], fm.GROWTH_VALIDITY_RANGE[1], peers, rising=True)
