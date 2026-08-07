"""Ticker search: local fuzzy index first, live Yahoo lookup second.

Why two sources. Yahoo's own search handles partial names and codes well
("hong kong exchange" -> 0388.HK, "0700" -> 0700.HK) and covers every market,
but it does **not** tolerate typos — measured 2026-08-07, `microsft` and
`teslla` both return zero results. Since the point of the search box is that a
slip does not produce "no data", typo tolerance has to come from matching
locally against a list we hold.

The local list is SEC EDGAR's company_tickers file via
`obb.equity.search(provider="sec")`: 10,398 US symbols with names, free, no API
key. There is no free equivalent for Hong Kong, so HK and other non-US listings
are served by the Yahoo fallback and still need roughly correct spelling.

The index is cached to disk so the ~5 s OpenBB import is paid once, not per
process start, and the whole thing degrades to Yahoo-only if the fetch fails.
"""
from __future__ import annotations

import json
import time
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock

INDEX_PATH = Path(__file__).resolve().parent / "data" / "ticker_index.json"
INDEX_MAX_AGE_S = 30 * 24 * 3600  # symbols change slowly; a month is plenty

# Below this similarity a "match" is noise rather than a typo. Tuned so that
# microsft->MICROSOFT and teslla->TESLA survive while unrelated names do not.
FUZZY_FLOOR = 0.72
# Fuzzy scanning is O(index); skip it entirely once cheap matching has enough.
FUZZY_TRIGGER = 5

# Relevance tiers. Yahoo sits ABOVE local name matches deliberately: the local
# index is US-only, so for "tencent" it can only offer Tencent *Music* (a US
# listing whose name happens to start with the query) while Yahoo returns
# 0700.HK, which is what was asked for. An exact or prefix symbol hit still
# wins outright — typing "aapl" must never be reordered by a remote guess.
SCORE_SYMBOL_EXACT = 1000.0
SCORE_SYMBOL_PREFIX = 900.0
SCORE_YAHOO_TOP = 880.0
SCORE_NAME_PREFIX = 800.0
SCORE_NAME_CONTAINS = 700.0
SCORE_FUZZY_MAX = 600.0

_index: list[dict] | None = None
_buckets: dict[str, list[dict]] = {}
_index_lock = Lock()
# Keystrokes repeat queries constantly; one process-lifetime cache keeps the
# dropdown from issuing the same remote lookup on every backspace.
_remote_cache: dict[str, list[dict]] = {}


def _fetch_index() -> list[dict]:
    """SEC's full symbol/name list. Raises so the caller can fall back."""
    # deferred: importing openbb costs ~5 s, and a warm disk cache never pays it
    from openbb import obb
    rows = obb.equity.search(provider="sec", query="").results
    out = []
    for r in rows:
        symbol = (getattr(r, "symbol", "") or "").strip().upper()
        name = (getattr(r, "name", "") or "").strip()
        if symbol and name:
            out.append({"symbol": symbol, "name": name})
    return out


def load_index(force: bool = False) -> list[dict]:
    """Cached symbol list. Empty list (not an exception) when unavailable."""
    global _index
    with _index_lock:
        if _index is not None and not force:
            return _index
        if not force and INDEX_PATH.exists():
            age = time.time() - INDEX_PATH.stat().st_mtime
            if age < INDEX_MAX_AGE_S:
                try:
                    _index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                    return _index
                except (OSError, ValueError):
                    pass  # corrupt cache is not fatal — refetch below
        try:
            fetched = _fetch_index()
        except Exception:
            # Network down or SEC unreachable: serve a stale cache if there is
            # one, otherwise nothing. Yahoo fallback still answers the query.
            if _index is None and INDEX_PATH.exists():
                try:
                    _index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    _index = []
            elif _index is None:
                _index = []
            return _index
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(fetched), encoding="utf-8")
        _index = fetched
        return _index


def _fuzzy_candidates(first_char: str) -> list[dict]:
    """Index rows whose symbol or name starts with `first_char`.

    Fuzzy matching is the expensive tier, and scanning all 10,398 rows for it
    cost 1.85 s on "microsft". Bucketing by first character cuts that to a few
    hundred candidates. The trade-off is explicit: a typo **in the first
    character** ("nicrosoft") will not be corrected. That is the rarest kind of
    typo and the cheap tiers still catch it whenever the rest of the string is a
    substring match, so the latency is worth more than the coverage.

    Both the symbol's and the name's initial are indexed, so "googel" still
    reaches Alphabet Inc. via the GOOGL symbol.
    """
    index = load_index()  # outside the lock below: load_index takes it too
    with _index_lock:
        if not _buckets:
            for row in index:
                for initial in {row["symbol"][:1], row["name"][:1].upper()}:
                    if initial:
                        _buckets.setdefault(initial, []).append(row)
        return _buckets.get(first_char, [])


def _fuzzy_ratio(matcher: SequenceMatcher, candidate: str) -> float:
    """Similarity with difflib's own cheap upper-bound prefilters.

    `real_quick_ratio` (length only) and `quick_ratio` (character multiset) are
    both upper bounds on `ratio`, so bailing when either falls under the floor
    cannot discard a match. Without them a fuzzy pass over 10,398 rows x 2
    fields took 1.6 s for "microsft" — far too slow for a dropdown that runs
    per keystroke.
    """
    matcher.set_seq1(candidate)
    if matcher.real_quick_ratio() < FUZZY_FLOOR or matcher.quick_ratio() < FUZZY_FLOOR:
        return 0.0
    return matcher.ratio()


def _local_matches(query: str, limit: int) -> list[tuple[float, dict]]:
    """Score the local index: exact, then prefix, then substring, then fuzzy.

    Ranking is tiered rather than one blended score because the tiers mean
    different things to the reader — an exact symbol hit must never sit below a
    company whose name merely contains the query.
    """
    index = load_index()
    if not index or not query:
        return []
    q = query.strip().upper()
    scored: list[tuple[float, dict]] = []

    for row in index:
        symbol, name = row["symbol"], row["name"].upper()
        if symbol == q:
            score = SCORE_SYMBOL_EXACT
        elif symbol.startswith(q):
            score = SCORE_SYMBOL_PREFIX - len(symbol)
        elif name.startswith(q):
            score = SCORE_NAME_PREFIX - len(name) / 100
        elif q in name:
            score = SCORE_NAME_CONTAINS - len(name) / 100
        else:
            continue
        scored.append((score, {"symbol": symbol, "name": row["name"], "source": "sec"}))

    if len(scored) < FUZZY_TRIGGER:
        hit = {row["symbol"] for _, row in scored}
        matcher = SequenceMatcher(None, "", q)
        for row in _fuzzy_candidates(q[:1]):
            if row["symbol"] in hit:
                continue
            best = max(_fuzzy_ratio(matcher, row["symbol"]),
                       _fuzzy_ratio(matcher, row["name"].upper()))
            if best >= FUZZY_FLOOR:
                scored.append((SCORE_FUZZY_MAX * best,
                               {"symbol": row["symbol"], "name": row["name"],
                                "source": "sec"}))

    return scored[:limit * 4]  # trimmed after merging with the remote tier


def _yahoo_matches(query: str, limit: int) -> list[tuple[float, dict]]:
    """Live Yahoo lookup — the only path that reaches HK and other non-US names.

    Yahoo returns its own relevance order; that order is preserved by scoring
    each hit slightly below the one before it.
    """
    key = query.strip().upper()
    if key in _remote_cache:
        quotes = _remote_cache[key]
    else:
        try:
            import yfinance as yf
            # enable_fuzzy_query defaults to False, and with it off Yahoo returns
            # nothing at all for "microsft" or "tencnt". On, it resolves both —
            # and does so *faster* (microsft: 1645 ms -> 278 ms), because the
            # no-match path is the slow one. This is what gives non-US listings
            # typo tolerance, which the local US-only index cannot.
            # timeout: the dropdown runs per keystroke, so a slow lookup must be
            # abandoned rather than allowed to stall the box; local results have
            # already been computed by then and the next keystroke retries.
            quotes = yf.Search(query, max_results=max(limit, 6),
                               enable_fuzzy_query=True, timeout=3).quotes or []
        except Exception:
            return []  # offline, rate-limited, or shape change — local stands
        _remote_cache[key] = quotes

    out = []
    for rank, q in enumerate(quotes[:limit]):
        symbol = (q.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out.append((SCORE_YAHOO_TOP - rank * 10, {
            "symbol": symbol,
            "name": q.get("shortname") or q.get("longname") or symbol,
            "exchange": q.get("exchDisp"),
            "source": "yahoo",
        }))
    return out


def search_tickers(query: str, limit: int = 8) -> list[dict]:
    """Best matches for a partial symbol or company name.

    Both tiers are always consulted and then merged on one scale. Appending
    remote results after local ones instead would bury the right answer for any
    non-US company: "tencent" matches Tencent *Music* in the US-only index, so a
    strict local-first order pushed 0700.HK off the visible list entirely.
    """
    query = (query or "").strip()
    if not query:
        return []
    scored = _local_matches(query, limit) + _yahoo_matches(query, limit)
    scored.sort(key=lambda pair: -pair[0])

    results, seen = [], set()
    for _, row in scored:
        if row["symbol"] in seen:
            continue
        seen.add(row["symbol"])
        results.append(row)
        if len(results) >= limit:
            break
    return results
