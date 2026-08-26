"""Market data adapter layer.

The rest of the app only talks to `provider`. To switch to OpenBB later,
implement OpenBBProvider with the same six methods — get_quote, get_history,
get_news, get_peer_snapshot, get_fundamentals, get_filings — and swap the last
line.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from threading import Lock
from urllib.request import urlopen

import yfinance as yf

# Statement-backed data changes quarterly, so a short TTL costs nothing in
# freshness and removes the repeat fetches: one scorecard page load used to call
# get_fundamentals twice for the same ticker (/api/score + /api/stock/../comps)
# plus one get_peer_snapshot per peer. Batch screening multiplies that by N.
# get_quote is deliberately NOT cached — a live tracker must stay live.
CACHE_TTL_S = 900  # 15 minutes

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = Lock()


def _ttl_cached(fn):
    """Cache a provider method keyed on its ticker *and its other arguments*.

    Callers must treat the returned structure as read-only — it is shared
    between requests for the TTL window. Nothing in the app mutates provider
    output today; keep it that way rather than paying for a deep copy per hit.

    The key used to be the ticker alone, which was fine while every cached
    method took nothing else. `get_history` takes `period` and `interval`, so on
    the old key a 5y weekly series and the chart's 1y hourly one would collide
    and whichever landed first would be served to both.
    """
    @wraps(fn)
    def wrapper(self, ticker: str, *args, **kwargs):
        key = (fn.__name__, ticker.upper(), args, tuple(sorted(kwargs.items())))
        now = time.monotonic()
        with _cache_lock:
            hit = _cache.get(key)
            if hit is not None and now - hit[0] < CACHE_TTL_S:
                return hit[1]
        value = fn(self, ticker, *args, **kwargs)
        with _cache_lock:
            _cache[key] = (now, value)
        return value

    return wrapper


def home_index(ticker: str) -> str:
    """The index a ticker's relative performance should be read against.

    One definition, three consumers: the macro news feed, the beta regression
    and the momentum pillar's relative strength. It was inlined in `get_news`
    while it had a single caller; a second copy would be the kind of drift that
    lets news say Hang Seng while scoring says S&P 500 for the same company.

    Suffix-based, like the EDGAR skip below, and it inherits the same limit —
    a US-listed ADR of a Chinese company still reads as `^GSPC`.
    """
    return "^HSI" if ticker.upper().endswith(".HK") else "^GSPC"


def cache_stats() -> dict:
    with _cache_lock:
        return {"entries": len(_cache), "ttl_seconds": CACHE_TTL_S}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# SEC filing types worth marking on a price chart, mapped to the category the
# UI filters on. Anything not listed (144, SC 13G/A, PX14A6G, ...) is dropped —
# it would bury the chart in dots that say nothing about the price.
FILING_CATEGORIES = {
    "10-K": "earnings", "10-Q": "earnings", "20-F": "earnings", "40-F": "earnings",
    "8-K": "material",
    "3": "insider", "4": "insider", "5": "insider",
}
FILINGS_LIMIT = 400  # ~5 years for a large-cap once the noise types are dropped


def _filing_title(report_type: str, row) -> str:
    if report_type in ("10-K", "20-F", "40-F"):
        return "10-K annual report"
    if report_type == "10-Q":
        period = str(getattr(row, "report_date", "") or "")[:10]
        return f"10-Q quarterly report{f' (period {period})' if period else ''}"
    if report_type == "8-K":
        items = (getattr(row, "items", "") or "").strip()
        return f"8-K material event{f' (items {items})' if items else ''}"
    return f"Form {report_type} insider transaction"


def _clean(value):
    """Replace NaN/inf with None so JSON serialization never breaks."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


_RF_CACHE: tuple[str, float] | None = None  # (date, rate) — treasury rates move once a day
_CGB_CACHE: tuple[str, float, bool] | None = None  # (date, rate, was it live?)

# The last good CGB reading, kept between runs. Beside `ticker_index.json` and
# for the same reason — it is a cache of someone else's data, not the user's —
# so it inherits `backend/data/`'s existing exclusion from the repository.
CGB_STORE_PATH = Path(__file__).resolve().parent / "data" / "cgb_10y.json"

# ChinaBond (CCDC) publishes the official China Government Bond curve; the PBOC
# points at it rather than republishing. `qxId=ycqx` selects the government
# curve, but the response still carries the commercial-bank and CP&Note curves
# beside it, so the row has to be matched by name and not by position.
#
# **`gjqx=0` asks for every tenor and the column is then chosen by its own
# header label.** Until 2026-08-20 this sent `gjqx=10` and read the single value
# that came back, which made the tenor a *URL parameter* — change one character
# and ChinaBond returns the 7-year, well-formed and plausible, with nothing able
# to fail. The offline tests supply their own HTML so the URL was not under test
# at all, and a live band cannot separate the tenors: the whole curve sat inside
# 1.1858 (3M) to 2.1509 (30Y) on 2026-08-18, and a floor high enough to exclude
# the 7-year would sit above the 10-year's own record low of 1.59%.
#
# Reading the label instead makes the wrong tenor unrepresentable rather than
# merely detectable, and it moves the choice into the parser where an offline
# test can pin it. Measured 2026-08-20 over ten paired requests: 20,572 bytes
# against 18,892, **+8.9%**, once per calendar day, and no latency difference
# distinguishable from noise (1.79-2.95 s either way).
#
# The cost is a new failure mode, and it is the right trade rather than a free
# one: if the header stops saying "10Y" this degrades to `usd_proxy`, where the
# old code would have gone on quietly serving whatever `gjqx=10` returned. A
# labelled degrade beats an unlabelled wrong number.
CGB_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
CGB_CURVE = "ChinaBond Government Bond Yield Curve"
# The header row opens with these two cells. `Date` is load-bearing: the filter
# form above the table *also* opens with a "Yield Curve Name" cell, so matching
# on that alone picks up the page chrome and reads its dropdown as a tenor list.
CGB_HEADING = "Yield Curve Name"
CGB_HEADING_DATE = "Date"
CGB_TENOR = "10Y"
# Wide enough to clear a Chinese New Year or Golden Week closure — those run to
# nine consecutive days, and a window that lands entirely inside one returns an
# empty table indistinguishable from an outage. Measured 2026-08-19: 20 calendar
# days is 15 trading rows, 19.8 KB, 3.2 s.
CGB_WINDOW_DAYS = 20
# How old the newest published row may be before the feed counts as frozen
# rather than merely quiet. Comfortably past a nine-day holiday closure plus a
# weekend, and far short of the request window above — so a table that stops
# updating is caught rather than served as if it were today's.
CGB_MAX_STALE_DAYS = 14
# Measured 1.3-3.8 s across ~20 calls on 2026-08-19, with one outright miss in
# that run. A hard ceiling because the HKMA endpoint hung for 25 s on two
# separate attempts — a slow day has to degrade the number, never the request.
#
# 10 s is ~2.6x the worst observation rather than a generous margin, and that is
# affordable only because a failure is **not cached**: a miss costs one request
# and the next one retries. Were failures sticky this would need to be far
# longer, since the gap between a Chinese rate and an American one is worth 30%
# of Tencent's fair value.
#
# That sentence is load-bearing and was briefly untrue. Caching the *stored*
# reading alongside the live one — which looks like symmetry — meant one
# transient timeout pinned an old number for the rest of the UTC day and never
# retried, which is precisely the sticky failure this margin is not sized for.
# Only a live reading is cached; see `_cgb_10y`.
#
# What a miss degrades *to* moved on 2026-08-20: the stored CNY reading if there
# is a usable one, and only then the USD proxy.
CGB_TIMEOUT_S = 10


def _cgb_stored() -> tuple[str, float] | None:
    """The last good `(published date, rate)` from an earlier run, or None.

    **The date is parsed, not coerced.** This read `str(raw["published"])`
    until it was pointed out that the staleness check downstream is a
    *lexicographic* comparison, which `str()` turns into a fail-**open**: every
    non-string sorts above an ISO date, so `null` became `"None"`, `true` became
    `"True"` and — the realistic one — a date hand-edited to the integer
    `20260819` became `"20260819"`, all of them permanently fresh. `strptime`
    also pins the *format*, so an upstream switch to `2026/08/20` is rejected
    rather than sailing through on `"/" > "-"`.

    `except Exception` rather than a tuple of the expected types: the contract
    this owes its caller is that a damaged file costs the fallback and never the
    valuation, and enumerating what a damaged file can raise is how that
    contract acquires holes — a deeply nested array raises `RecursionError`,
    which is a `RuntimeError` and was escaping.
    """
    try:
        raw = json.loads(CGB_STORE_PATH.read_text(encoding="utf-8"))
        published, rate = raw["published"], float(raw["rate"])
        datetime.strptime(published, "%Y-%m-%d")
        return published, rate
    except Exception:
        return None


def _cgb_remember(published: str, rate: float) -> None:
    """Keep a good reading for the next run. Never raises.

    A read-only checkout, a full disk or a permissions problem must cost the
    *next* outage its fallback, never this request its valuation — the same rule
    every other optional path in this module follows.

    **Written to a temporary file and moved into place**, because `write_text`
    truncates first: two of uvicorn's threads missing the day cache together
    both fetch and both write, and a process killed mid-write leaves an empty
    file. Neither produces a wrong number — a damaged file reads as no file —
    but both cost exactly the fallback this exists to provide, and the second
    one does it precisely when the process is next starting during an outage,
    which is this store's whole reason to exist. `os.replace` is atomic on
    Windows as well as POSIX.
    """
    try:
        CGB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CGB_STORE_PATH.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"published": published, "rate": rate}), encoding="utf-8")
        os.replace(tmp, CGB_STORE_PATH)
    except OSError:
        pass


def _cgb_10y() -> tuple[float, bool] | None:
    """`(rate, live)` for China's 10-year government yield, or **None**.

    A ratio, not percent. `live` is False when the number came from the store
    rather than from today's fetch, and it exists so the caller can say so —
    serving yesterday's rate is defensible, serving it *silently* is not.

    **Why a stored rate at all.** The in-process day cache already hides an
    outage that starts after one success, so what it cannot cover is the two
    cases that actually bite: a process that starts while ChinaBond is down, and
    the first request of a new calendar day.

    Both are ordinary here rather than hypothetical. Four failure episodes were
    recorded on 2026-08-19 and at least five more on 2026-08-20, with the
    endpoint answering normally in between — once going from a 3.9 s response to
    consecutive 12-second timeouts inside fifteen minutes, and on another
    occasion timing out on this exact query while a hand-issued one had just
    succeeded. The alternative is not a slightly worse rate, it is a **US** rate
    on CNY cash flows, worth 30% of Tencent's fair value. A CNY yield a few days
    old keeps the currency right and costs only freshness: that yield's 12-month
    range is ~22bp, against a ~360bp gap to the US 10-year.

    **The staleness bound is the one that was already here, and it is the same
    bound in both paths** — `CGB_MAX_STALE_DAYS` against the row's *published*
    date, not against when it was fetched. That is deliberate rather than
    convenient: "this yield was published within a fortnight" means exactly the
    same thing whether the fetch happened this morning or last Tuesday, so the
    fallback needs no second constant and no second judgement. Storing the fetch
    date instead would have let the two ages compound to 24 days without anyone
    choosing that.

    A *failed* fetch falls back to the store. A fetch that succeeds and returns
    something out of band does **not** — that means the feed is broken rather
    than absent, and covering it with an older number would hide the breakage.

    **A range wider than a year returns HTTP 200 with an empty table** rather
    than an error, and so does a window containing no trading days. Both parse
    to `None`, which is the same outcome as an outage and the reason the parse is
    checked rather than the status code.

    The tenor is selected by reading the table's own `10Y` header rather than by
    asking for one column — see the note on `CGB_URL` for why, and for what that
    costs.
    """
    global _CGB_CACHE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _CGB_CACHE and _CGB_CACHE[0] == today:
        return _CGB_CACHE[1], _CGB_CACHE[2]
    live = _cgb_fetch()
    published, rate = live if live is not None else (_cgb_stored() or (None, None))
    if published is None or rate is None:
        return None
    # A frozen upstream table is the one failure the parse cannot see: the rows
    # are well-formed and the yield is plausible, it is simply years old. The
    # same check retires a stored reading, for the same reason and by the same
    # measure.
    if published < (datetime.now(timezone.utc)
                    - timedelta(days=CGB_MAX_STALE_DAYS)).strftime("%Y-%m-%d"):
        return None
    # Same sanity band as the treasury feed, for the same reason — the page
    # quotes percent, so a switch to ratios would silently divide by 100.
    if not 0 < rate < 0.25:
        return None
    # **Only a live reading is cached, and that is load-bearing.** Caching the
    # stored one too was the obvious symmetry and it silently reversed the
    # failure contract stated on `CGB_TIMEOUT_S` above: one transient timeout
    # would pin a reading up to a fortnight old for the rest of the UTC day and
    # never retry, so ChinaBond flickering for thirty seconds cost the next
    # twenty-four hours. Measured — six requests after recovery all served the
    # old number and the upstream was contacted **once**.
    #
    # Leaving it uncached restores exactly the pre-store behaviour: a miss costs
    # one request and the next retries. That is not free — during a sustained
    # outage every request pays the timeout — but it is what the platform did
    # before this store existed, so the store adds a better *number* without
    # taking away a retry.
    #
    # The write is guarded for the same reason and not for symmetry: on the
    # fallback path `published` and `rate` came *out* of the store, so writing
    # them back changes nothing but the disk.
    if live is None:
        return rate, False
    _cgb_remember(published, rate)
    _CGB_CACHE = (today, rate, True)
    return rate, True


def _cgb_fetch() -> tuple[str, float] | None:
    """`(published date, rate as a ratio)` from ChinaBond, or None on any failure.

    Split from `_cgb_10y` so the fallback above has one thing to test for. The
    freshness and sanity checks live in the caller, because they apply equally to
    a stored reading.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        start = (datetime.now(timezone.utc)
                 - timedelta(days=CGB_WINDOW_DAYS)).strftime("%Y-%m-%d")
        url = (f"{CGB_URL}?gjqx=0&qxId=ycqx&locale=en_US"
               f"&startDate={start}&endDate={today}")
        with urlopen(url, timeout=CGB_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        rows, tenor_col, width = [], None, None
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [c for c in (re.sub(r"<[^>]+>", "", x).strip()
                                 for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S))
                     if c]
            if (len(cells) > 2 and cells[0] == CGB_HEADING
                    and cells[1] == CGB_HEADING_DATE):
                width = len(cells)
                tenor_col = cells.index(CGB_TENOR) if CGB_TENOR in cells else None
            # `len(cells) == width` rather than `> tenor_col`, because a row
            # missing an *earlier* column would shift every later one left and
            # still be long enough: drop 3M and the cell under the 10Y header is
            # the 30-year. Matching the header's width is the only way to see
            # that from the payload. The CP&Note curve legitimately runs one
            # column short — it publishes no 30-year — which is why this cannot
            # simply require every row to be the same length.
            elif (tenor_col is not None and len(cells) == width
                    and cells[0] == CGB_CURVE):
                rows.append((cells[1], float(cells[tenor_col])))
        # By date rather than by position: the table happens to arrive
        # newest-first, and nothing documents that it always will. Keyed on the
        # date *alone* — a bare `max(rows)` falls through to comparing yields
        # when two rows share a date, which would quietly serve the higher one,
        # and a spurious 9.99% clears the sanity band below. ISO dates make
        # lexicographic order chronological, so no parsing is needed.
        if not rows:
            return None
        newest, rate = max(rows, key=lambda r: r[0])
        return newest, rate / 100
    except Exception:
        return None


# The last good HKGB reading, kept between runs. Beside the CGB store above and
# for the same reason — a cache of someone else's data, not the user's.
HKGB_STORE_PATH = Path(__file__).resolve().parent / "data" / "hkgb_10y.json"

# The HKSAR Government's own daily closing reference pricings for its bonds.
#
# **Not HKMA, and that is a finding rather than a preference.** HKMA's
# `monthly-statistical-bulletin/gov-bond/instit-bond-price-yield-daily` answers
# `success: true` and returns every yield field null at every date sampled on
# 2026-08-26 — alive and empty, so retrying it can never help. Its Exchange Fund
# Bills & Notes series stops at two years in any case: issuance at three years
# and above ceased in 2015. TODOLIST recorded this gap as "HKMA unreachable",
# which was wrong twice over — the host answers in 2.6 s, and the series that
# does carry a ten-year is published somewhere else entirely.
#
# Fetched at runtime and never vendored, which is the same licensing choice made
# for ChinaBond next door: the workbook's own notice asks users to quote the
# Government as owner of the pricings and of the intellectual property in them,
# so committing the file into a public repository is the act that notice
# addresses and calling the endpoint is not.
HKGB_URL = ("https://www.hkgb.gov.hk/en/others/documents/"
            "HKD_DailyClosingReferencePricings_IBPandGSBP.xls")
# The workbook is a grid rather than a table: tenor labels on one row, a
# Price/Yield band beneath them, dates down column 0. All three are matched by
# their own text and never by position — the same discipline `CGB_TENOR`
# follows, for the same reason. The sheet carries 1, 3, 5, 7, 10, 15 and 20-year
# columns, so an off-by-one lands on a real tenor with a plausible yield and
# nothing fails; requiring the neighbouring cell to actually say "Yield" is what
# makes the wrong column unrepresentable instead of merely unlikely.
HKGB_TENOR = "10-year"
HKGB_TENOR_HEADING = "Tenor"
HKGB_YIELD_HEADING = "Yield"
# The same bound the CGB store uses and for the same reason, kept as its own
# constant rather than shared: the two feeds publish on different calendars, and
# a measurement that moves one should not silently move the other.
HKGB_MAX_STALE_DAYS = 14
# Measured 2026-08-26 over six sequential fetches of the 80 KB workbook: 1.98 s
# cold including DNS and TLS, then 0.29-0.35 s warm. 8 s is ~4x the worst
# observation, and affordable for the same reason CGB's ceiling is — a failure
# is never cached, so a miss costs one request and the next one retries.
HKGB_TIMEOUT_S = 8
_HKGB_CACHE: tuple[str, float, bool] | None = None  # (date, rate, was it live?)


def _hkgb_stored() -> tuple[str, float] | None:
    """The last good `(published date, rate)` from an earlier run, or None.

    The CGB store's two hard-won properties, deliberately duplicated rather than
    abstracted over: the date is **parsed** so the lexicographic staleness check
    downstream cannot fail open on a non-string, and the `except` is broad so a
    damaged file costs the fallback and never the valuation. See `_cgb_stored`
    for what each one was written against.
    """
    try:
        raw = json.loads(HKGB_STORE_PATH.read_text(encoding="utf-8"))
        published, rate = raw["published"], float(raw["rate"])
        datetime.strptime(published, "%Y-%m-%d")
        return published, rate
    except Exception:
        return None


def _hkgb_remember(published: str, rate: float) -> None:
    """Keep a good reading for the next run. Never raises.

    Temp file then `os.replace`, because `write_text` truncates first and
    `os.replace` is atomic on Windows as well as POSIX. See `_cgb_remember`.
    """
    try:
        HKGB_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HKGB_STORE_PATH.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"published": published, "rate": rate}), encoding="utf-8")
        os.replace(tmp, HKGB_STORE_PATH)
    except OSError:
        pass


def _hkgb_10y() -> tuple[float, bool] | None:
    """`(rate, live)` for Hong Kong's 10-year government benchmark, or **None**.

    A ratio, not percent. `live` is False when the number came from the store
    rather than from today's fetch, so the caller can say which.

    **The store earns its place differently here than it does for CGB.** That
    one exists because ChinaBond is unreliable; this one exists because the
    workbook is a *rolling window*. Measured 2026-08-26, it held 17 business
    days — 2026-08-03 to 2026-08-25 — so it is a month of history, not an
    archive, and a reading that is not kept is a reading that is gone.

    Everything else is the CGB shape on purpose: the same staleness bound
    applied to the row's own **published** date in both paths, the same sanity
    band, and only a live reading cached — see `_cgb_10y` for why that last one
    is load-bearing rather than an asymmetry.
    """
    global _HKGB_CACHE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _HKGB_CACHE and _HKGB_CACHE[0] == today:
        return _HKGB_CACHE[1], _HKGB_CACHE[2]
    live = _hkgb_fetch()
    published, rate = live if live is not None else (_hkgb_stored() or (None, None))
    if published is None or rate is None:
        return None
    if published < (datetime.now(timezone.utc)
                    - timedelta(days=HKGB_MAX_STALE_DAYS)).strftime("%Y-%m-%d"):
        return None
    # The workbook quotes percent, so a switch to ratios would silently divide
    # by 100 — the same band, and the same reason, as the two feeds above.
    if not 0 < rate < 0.25:
        return None
    if live is None:
        return rate, False
    _hkgb_remember(published, rate)
    _HKGB_CACHE = (today, rate, True)
    return rate, True


def _hkgb_fetch() -> tuple[str, float] | None:
    """`(published date, rate as a ratio)` from the HKGB workbook, or None.

    Split from `_hkgb_10y` so the fallback above has one thing to test for; the
    freshness and sanity checks live in the caller because they apply equally to
    a stored reading.

    **Three anchors, all textual.** The tenor row is found by its own `Tenor`
    label in column 0, the ten-year by its `10-year` header, and the yield by
    the `Yield` cell that must sit beside it.

    The first two are load-bearing and pinned: a hard-coded column index reads
    the right number on today's sheet and the wrong one the moment a tenor is
    added, and a missing `10-year` label would otherwise fall through to a
    neighbour whose yield is equally plausible.

    **The third is defence in depth, and mutation testing said so rather than
    the other way round.** An earlier draft of this paragraph claimed it made a
    mis-read "unrepresentable"; measured 2026-08-26, removing the check changes
    no outcome any caller can see. Swap the Price/Yield pair and the unchecked
    parse returns 99.0 — a price — which the sanity band below rejects anyway,
    so both paths degrade to `usd_proxy`. What the check buys is the *reason*
    arriving at the label rather than at the band, which is worth one line and
    is not worth overstating.

    **The last row is not the newest row.** Rows 37-40 of the sheet as fetched
    are disclaimer prose sitting in the date column, so `iloc[-1]` reads legal
    text where a date should be. Rows are kept only where column 0 really is a
    date and the yield really is a number, and the newest is then chosen by date
    rather than by position — the same rule `_cgb_fetch` follows, and for the
    same reason: nothing documents that the order is stable.
    """
    try:
        # Deferred, and this is the CI contract rather than a micro-optimisation:
        # `xlrd` is absent from `requirements-test.txt`, which is all CI installs,
        # so importing it at module scope would abort pytest collection before a
        # single offline test ran. `_us_treasury_10y` defers `openbb` for the
        # neighbouring reason.
        from io import BytesIO

        import pandas as pd
        with urlopen(HKGB_URL, timeout=HKGB_TIMEOUT_S) as resp:
            book = resp.read()
        for df in pd.read_excel(BytesIO(book), sheet_name=None, header=None).values():
            labels = [str(v).strip() for v in df.iloc[:, 0]]
            if HKGB_TENOR_HEADING not in labels:
                continue
            tenor_row = labels.index(HKGB_TENOR_HEADING)
            tenors = [str(v).strip().lower().replace(" ", "-")
                      for v in df.iloc[tenor_row]]
            if HKGB_TENOR not in tenors:
                continue
            tenor_col = tenors.index(HKGB_TENOR)
            band = next(
                (i for i in range(tenor_row + 1, min(tenor_row + 8, df.shape[0]))
                 if HKGB_YIELD_HEADING in [str(v).strip() for v in df.iloc[i]]), None)
            if band is None:
                continue
            cells = [str(v).strip() for v in df.iloc[band]]
            if (tenor_col + 1 >= len(cells)
                    or cells[tenor_col + 1] != HKGB_YIELD_HEADING):
                continue
            rows = []
            for i in range(band + 1, df.shape[0]):
                day, yld = df.iloc[i, 0], df.iloc[i, tenor_col + 1]
                # `yld == yld` rejects NaN, which is what an unpriced tenor and
                # every blank cell below the table both read as.
                if (isinstance(day, datetime) and isinstance(yld, (int, float))
                        and not isinstance(yld, bool) and yld == yld):
                    rows.append((day.strftime("%Y-%m-%d"), float(yld)))
            if rows:
                newest, rate = max(rows, key=lambda r: r[0])
                return newest, rate / 100
        return None
    except Exception:
        return None


def _us_treasury_10y() -> float | None:
    """The live US 10-year yield, or **None** when it cannot be fetched.

    Split out of `risk_free_rate` below so that the currency branch runs for
    real under test. The offline suite pins *this* function rather than the one
    above it, which is the difference between a fixture that keeps the suite
    offline and a fixture that stubs out the very logic under test.

    Fetched at most once per calendar day. A failure is **not** cached, so a
    transient outage does not pin the fallback for the rest of the process.
    """
    global _RF_CACHE
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _RF_CACHE and _RF_CACHE[0] == today:
        return _RF_CACHE[1]
    try:
        # deferred: importing openbb costs ~4s, so only a request that actually
        # runs a DCF pays it, and only once per process
        from openbb import obb
        rows = obb.fixedincome.government.treasury_rates(provider="federal_reserve").results
        rate = next(r.year_10 for r in reversed(rows) if r.year_10 is not None)
        # sanity band: a provider switching to percent units would wreck every WACC
        if 0 < rate < 0.25:
            _RF_CACHE = (today, rate)
            return rate
    except Exception:
        pass
    return None


def risk_free_rate(fallback: float,
                   currency: str | None = None,
                   sovereign_spread: float = 0.0) -> tuple[float, str]:
    """(rate, source) for the currency the discounted cash flows are in.

    Reads `financialCurrency`, the same *field* and for the same reason as
    `financial_models.equity_risk_premium_for`: a discount rate has to match the
    currency of the cash flows it discounts. Until now only the *premium* half
    of CAPM obeyed that — 0002.HK was priced off Hong Kong's 5.01% equity risk
    premium and a **United States** risk-free rate, which is not a rate in any
    market.

    All three consumers of the currency code — this, `equity_risk_premium_for`
    and `sovereign_default_spread` — match **exactly**, so an unrecognised
    spelling degrades the same way in all three rather than half-resolving in
    one. `None` means the caller did not say; it is treated as USD, which is
    what this function did before the parameter existed.

    Seven sources, mirroring `equity_risk_premium_for`:
      us_treasury_10y              USD cash flows, and the Fed feed answered
      platform_default             USD cash flows, no feed — `fallback` stands in
      cgb_10y_less_spread          CNY cash flows, priced off China's own curve
      cgb_10y_stored_less_spread   the same curve, from the last good reading
                                   rather than today's — ChinaBond did not answer
      hkgb_10y_less_spread         HKD cash flows, priced off Hong Kong's own
                                   government benchmark
      hkgb_10y_stored_less_spread  the same benchmark, from the last good
                                   reading — the workbook holds only a rolling
                                   month, so this is the ordinary case for any
                                   gap longer than that, not a rare one
      usd_proxy                    a non-USD currency with no curve of its own; a
                                   US rate is standing in

    `sovereign_spread` is subtracted from a **local sovereign yield only**, and
    is the caller's to supply because it comes from the same vendored table the
    caller reads the equity premium from. A government bond yield is not
    risk-free: China's 10-year contains China's own default risk, and the
    country-inclusive ERP paired with it contains that spread again. Subtracting
    once removes the double count. It is deliberately *not* applied to the US
    10-year, which is the mature-market base the whole table is built on —
    netting it there would move every USD valuation for no corresponding gain.

    A non-USD currency reports `usd_proxy` whether the US number came from the
    feed or from `fallback`. The distinction the reader needs is that no rate
    for *this* currency was used, and that is identical in both cases. **CNY and
    HKD both degrade to exactly that** when their own curve cannot be reached,
    so a bad day returns the platform to its earlier behaviour rather than to an
    error.
    """
    # `str(...)` because this reads straight off a vendor payload: a non-string
    # here used to be harmless and would now raise inside `_wacc`, which is a
    # fragility this change would have introduced rather than found.
    #
    # Exact match, no case folding, because the other two consumers of this same
    # currency code — `equity_risk_premium_for` and `sovereign_default_spread` —
    # are exact-match dict lookups. Folding here alone was worse than not folding
    # at all: `"cny"` took the CGB branch while the spread lookup missed and
    # returned 0.0 and the premium fell to the mature market, so the rate came
    # back as China's *raw* yield paired with a no-country premium, still
    # labelled `cgb_10y_less_spread`. An unrecognised spelling now degrades to
    # the proxy, which is what it did before the CNY branch existed.
    ccy = str(currency or "USD")
    if ccy == "CNY":
        cgb = _cgb_10y()
        # Re-checked *after* the subtraction. `_cgb_10y`'s band guards the
        # published yield; netting the sovereign spread happens out here, and a
        # low enough print nets to zero or below — 0.60% is the spread, so any
        # CGB under that does it. A negative risk-free rate then caps terminal
        # growth negative through `min(TERMINAL_GROWTH, rf)`, and the model
        # would assert perpetual *shrinkage* for a going concern with no error
        # and no flag. Out of band degrades to the proxy like any other miss.
        if cgb is not None and 0 < cgb[0] - sovereign_spread < 0.25:
            # Two sources rather than one, because a reader deciding what to
            # trust needs to know which. Both are China's own curve and both are
            # therefore the right *currency* — which is why neither is a
            # stand-in — but only one of them is today's.
            return (cgb[0] - sovereign_spread,
                    "cgb_10y_less_spread" if cgb[1] else "cgb_10y_stored_less_spread")
    if ccy == "HKD":
        # The same shape as CNY above, including the band re-check *after* the
        # subtraction: HK's published default spread is 51bp, so a low enough
        # print nets to zero or below, and a negative risk-free rate would cap
        # terminal growth negative through `min(TERMINAL_GROWTH, rf)` — the
        # model asserting perpetual shrinkage for a going concern, with no error
        # and no flag. Out of band degrades to the proxy like any other miss.
        #
        # Why this is a correction and not a preference: an HKD-reporting issuer
        # was discounted at the **US** 10-year, which on 2026-08-26 was 4.70%
        # against Hong Kong's own 3.495% — 120bp of pure currency mismatch, on
        # exactly the reasoning that made the CNY branch above necessary. The
        # peg is not the answer either: it fixes the exchange rate, not the term
        # structure, and the two curves demonstrably differ.
        hkgb = _hkgb_10y()
        if hkgb is not None and 0 < hkgb[0] - sovereign_spread < 0.25:
            return (hkgb[0] - sovereign_spread,
                    "hkgb_10y_less_spread" if hkgb[1] else "hkgb_10y_stored_less_spread")
    rate = _us_treasury_10y()
    if ccy != "USD":
        return (fallback if rate is None else rate), "usd_proxy"
    if rate is None:
        return fallback, "platform_default"
    return rate, "us_treasury_10y"


_FX_CACHE: dict[tuple[str, str], tuple[str, float]] = {}  # (pair) -> (date, rate)


def fx_rate(from_ccy: str | None, to_ccy: str | None) -> float | None:
    """Units of `to_ccy` per 1 `from_ccy`, or **None** when it cannot be fetched.

    Needed because a company's statements and its shares can be denominated
    differently: measured live 2026-08-10, 0700.HK, 9988.HK and 1810.HK all
    trade in HKD and report in CNY. The cash flows a DCF discounts come from the
    statements and the price it compares them against comes from the market, so
    without this the two sides of the comparison are different units.

    Returning None rather than a constant is deliberate, and the opposite of
    `risk_free_rate` above. A stale risk-free rate moves a valuation a little; a
    wrong FX rate rescales all of it, and there is no defensible constant for a
    currency pair. Callers suppress the comparison instead of printing a number
    built on a guess.

    yfinance rather than `obb.currency`: it is already this app's data source,
    the `CNYHKD=X` pair is served on the same client we already construct, and it
    costs no second provider on the valuation path. Cached per calendar day, and
    failures are not cached, so an outage does not pin a ticker for the session.
    """
    if not from_ccy or not to_ccy:
        return None
    if from_ccy == to_ccy:
        return 1.0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (from_ccy, to_ccy)
    hit = _FX_CACHE.get(key)
    if hit and hit[0] == today:
        return hit[1]
    try:
        close = yf.Ticker(f"{from_ccy}{to_ccy}=X").history(period="5d")["Close"]
        rate = float(close.iloc[-1])
    except Exception:
        return None
    if not (math.isfinite(rate) and rate > 0):
        return None
    _FX_CACHE[key] = (today, rate)
    return rate


# ticker -> (monotonic fetch time, price, as_of epoch seconds)
_PRICE_CACHE: dict[str, tuple[float, float, float | None]] = {}
PRICE_TTL_S = 60

# What the vendor states about its own latency, forwarded rather than assumed.
# Measured on 0700.HK 2026-08-14: exchangeDataDelayedBy 15, quoteSourceName
# "Delayed Quote", and regularMarketTime exactly 15.0 minutes behind the clock.
DEFAULT_QUOTE_DELAY_MIN = 15


def live_price(ticker: str) -> tuple[float, float | None] | None:
    """(price, as_of epoch) fresher than the fundamentals cache, or None.

    `get_fundamentals` is cached for 15 minutes because statements do not change
    within a quarter, and the price rides along in the same payload. Stacked on
    the vendor's own 15-minute delay that put the valuation screen up to **30
    minutes** behind the market, while the Tracker — which calls the uncached
    `get_quote` — was half that. Only the second 15 is ours to remove.

    Cached for 60 seconds rather than not at all, which is the whole reason this
    is separate from `get_quote`: a single page view fires several endpoints at
    once (a Scorecard load hits `/score`, `/peers` and `/comps`), so an uncached
    fetch would cost three or four quote calls to answer one question. 60s is far
    inside the vendor's delay, so it costs no freshness that exists to be had.

    `get_quote` stays uncached regardless — a live tracker must stay live.

    Returns None on any failure, and the failure is deliberately not cached (same
    rule as `risk_free_rate` and `fx_rate` above). Callers keep the snapshot
    price: a quote outage should cost freshness, never the valuation.
    """
    now = time.monotonic()
    hit = _PRICE_CACHE.get(ticker.upper())
    if hit and now - hit[0] < PRICE_TTL_S:
        return hit[1], hit[2]
    try:
        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        price = float(price)
    except Exception:
        return None
    if not (math.isfinite(price) and price > 0):
        return None
    as_of = info.get("regularMarketTime")
    _PRICE_CACHE[ticker.upper()] = (now, price, as_of)
    return price, as_of


def with_fresh_price(f: dict) -> dict:
    """`f` with its price refreshed, as a copy.

    Copied rather than mutated because `get_fundamentals` output is TTL-cached
    and shared between requests — its decorator's docstring requires callers to
    treat it as read-only, and writing a price into the shared object would hand
    a later request a payload whose price and statements came from different
    fetches without anything saying so.

    **Only the price moves. `marketCap` deliberately does not.** Market cap feeds
    the WACC weights, so refreshing it would make fair value drift intraday with
    no filing having changed — a valuation that will not reproduce minute to
    minute. Leaving it also keeps every market-cap-derived multiple (P/E, P/B,
    EV/EBITDA, `fcf_yield`) mutually consistent as of one snapshot rather than
    half-refreshed. The cost is that recomputing P/E from the displayed price
    gives a marginally different answer, which is why the age is labelled.
    """
    fresh = live_price(f["ticker"])
    if fresh is None:
        return f
    price, as_of = fresh
    info = {**f["info"], "currentPrice": price, "regularMarketPrice": price}
    if as_of is not None:
        info["regularMarketTime"] = as_of
    return {**f, "info": info}


# The `info` fields `get_fundamentals` forwards to the model layer, and with that
# the contract every committed fixture has to satisfy. At module level rather
# than inline in the method so `tests/test_fixtures.py` can import it and assert
# the two agree: while this list lived inside the function body, two keys were
# added on 2026-08-14 and the fixtures captured on 2026-08-10 went on being a
# 49-key subset of a 51-key contract, with nothing able to notice.
#
# Adding a key here means recapturing the fixtures, or adding it to them as null.
# A fixture missing a field the provider forwards silently reads as "the vendor
# did not report it", which is a different test from the one you think you wrote.
INFO_KEYS = (
    # `currency` is what the shares trade in; `financialCurrency` is
    # what the statements are reported in, and for a China-domiciled
    # HK listing they differ — 0700.HK trades in HKD and reports in
    # CNY (verified live 2026-08-10, same for 9988.HK). Without this
    # field the app cannot tell that the cash flows it discounts and
    # the price it compares them against are different units.
    "longName", "sector", "industry", "currency", "financialCurrency",
    "marketCap",
    "currentPrice", "regularMarketPrice", "sharesOutstanding", "beta",
    # What the vendor says about its own latency. Forwarded so the
    # price can carry its age like every other model input carries
    # its provenance — it is the denominator of the headline upside
    # and was the only input on screen with no label at all.
    "regularMarketTime", "exchangeDataDelayedBy",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseValue",
    "enterpriseToEbitda", "enterpriseToRevenue", "pegRatio",
    "dividendYield", "payoutRatio", "returnOnEquity", "returnOnAssets",
    "profitMargins", "operatingMargins", "grossMargins", "ebitdaMargins",
    "revenueGrowth", "earningsGrowth", "totalDebt", "totalCash",
    "debtToEquity", "currentRatio", "quickRatio", "freeCashflow",
    "operatingCashflow", "totalRevenue", "ebitda", "trailingEps",
    "forwardEps", "bookValue", "targetMeanPrice", "recommendationKey",
    "numberOfAnalystOpinions", "targetLowPrice", "targetHighPrice",
    # momentum pillar inputs (scoring.py pillar M) — omitting any of
    # these drops the pillar below its 40% availability threshold
    "twoHundredDayAverage", "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
    "52WeekChange", "SandP52WeekChange",
)


class YFinanceProvider:
    def get_quote(self, ticker: str) -> dict:
        info = yf.Ticker(ticker).info or {}
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "currency": info.get("currency"),
            "exchange": info.get("fullExchangeName") or info.get("exchange"),
            "price": _clean(info.get("currentPrice") or info.get("regularMarketPrice")),
            "previous_close": _clean(info.get("previousClose")),
            "day_high": _clean(info.get("dayHigh")),
            "day_low": _clean(info.get("dayLow")),
            "market_cap": _clean(info.get("marketCap")),
            "pe_trailing": _clean(info.get("trailingPE")),
            "pe_forward": _clean(info.get("forwardPE")),
            "fifty_two_week_high": _clean(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _clean(info.get("fiftyTwoWeekLow")),
        }

    @_ttl_cached
    def get_history(self, ticker: str, period: str = "1y", interval: str = "1d") -> list[dict]:
        # Cached because the valuation path now asks for a long weekly series
        # per ticker *and* per home index, and a screening run would otherwise
        # refetch the same index bars once per name. Keyed on period and
        # interval as well, so this does not collide with the chart's requests.
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
        # intraday bars need epoch timestamps; daily+ bars use date strings
        intraday = interval.endswith(("m", "h"))
        out = []
        for ts, row in df.iterrows():
            bar = {
                "time": int(ts.timestamp()) if intraday else ts.strftime("%Y-%m-%d"),
                "open": _clean(round(float(row["Open"]), 4)),
                "high": _clean(round(float(row["High"]), 4)),
                "low": _clean(round(float(row["Low"]), 4)),
                "close": _clean(round(float(row["Close"]), 4)),
                "volume": _clean(float(row["Volume"])),
            }
            if bar["close"] is not None:
                out.append(bar)
        return out

    def get_news(self, ticker: str, limit: int = 50) -> list[dict]:
        """Company news blended with macro/policy headlines from the ticker's
        home-market index (full world-news feeds arrive with OpenBB)."""
        items = self._parse_news(yf.Ticker(ticker).news or [], "company", limit)
        macro_symbol = home_index(ticker)
        try:
            seen = {n["title"] for n in items}
            items += [n for n in self._parse_news(yf.Ticker(macro_symbol).news or [], "macro", limit)
                      if n["title"] not in seen]
        except Exception:
            pass  # macro feed is best-effort enrichment
        items.sort(key=lambda n: n["date"] or "", reverse=True)
        return items[:limit]

    @staticmethod
    def _publish_epoch(content: dict, item: dict) -> int | None:
        """Publish time as a UTC epoch, or None when the feed omits it.

        Both yfinance shapes carry a real timestamp — an ISO string or a unix
        epoch — which `date` below throws away by truncating to ten characters.
        The chart uses this to place an intraday marker on the bar the story
        actually landed in rather than on the session open.

        A naive ISO string is read as UTC: `.timestamp()` would otherwise
        interpret it in the server's local zone, which silently shifts every
        marker by the host's offset.
        """
        pub = content.get("pubDate") or content.get("displayTime")
        if pub:
            try:
                parsed = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        stamp = item.get("providerPublishTime")
        return int(stamp) if isinstance(stamp, (int, float)) else None

    @staticmethod
    def _parse_news(raw: list, category: str, limit: int) -> list[dict]:
        items = []
        for item in raw[:limit]:
            # yfinance has shipped two shapes: flat dicts and nested {'content': {...}}
            content = item.get("content", item)
            title = content.get("title")
            if not title:
                continue
            date = None
            pub = content.get("pubDate") or content.get("displayTime")
            if pub:  # ISO string
                date = str(pub)[:10]
            elif item.get("providerPublishTime"):  # unix epoch
                date = datetime.fromtimestamp(
                    item["providerPublishTime"], tz=timezone.utc
                ).strftime("%Y-%m-%d")
            url = content.get("canonicalUrl")
            if isinstance(url, dict):
                url = url.get("url")
            url = url or item.get("link")
            publisher = content.get("provider", item.get("publisher"))
            if isinstance(publisher, dict):
                publisher = publisher.get("displayName")
            items.append({
                "title": title,
                "summary": content.get("summary") or "",
                "date": date,
                # None for feeds that omit it, and absent from SEC filings
                # entirely — the chart falls back to date placement for both.
                "published_at": YFinanceProvider._publish_epoch(content, item),
                "url": url,
                "publisher": publisher,
                "category": category,
            })
        return items

    @_ttl_cached
    def get_peer_snapshot(self, ticker: str) -> dict:
        """Just the multiples/metrics needed for a comps table row."""
        info = yf.Ticker(ticker).info or {}
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "market_cap": _clean(info.get("marketCap")),
            # market_cap is in the trading currency and total_debt in the
            # reporting one, so resolve_beta needs both labels to put a peer's
            # D/E on one basis. Free — same info call.
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency"),
            # Yahoo's own classification, carried so peer *discovery* can filter
            # on the same labels the target is classified by. Free — same info
            # call, no extra request, exactly like the two fields above.
            #
            # `industry` here is Yahoo's display string ("REIT - Retail",
            # hyphen-spaced) and is NOT interchangeable with the spelling
            # yfinance's screener accepts ("REIT—Retail", em-dash):
            # EquityQuery('eq', ['industry', 'REIT - Retail']) raises ValueError
            # with the network unplugged, because the accepted spellings are a
            # literal dict in the pinned yfinance — EQUITY_SCREENER_EQ_MAP
            # ['industry'] in yfinance/const.py.
            #
            # `comps._SCREENER_INDUSTRY` translates between them, derived from
            # that dict. This note used to say the translation "needs a mapping,
            # not a character replace", which overstated the evidence: measured
            # 2026-08-19, a plain replace round-trips all 145 industries. The
            # derived lookup is used for a different reason — an industry the
            # pinned build does not know misses it and yields no peers, where a
            # replace would emit a spelling the screener rejects and look
            # identical to an empty screen.
            #
            # `sector` needs no such treatment: its 11 values are the same
            # display strings on both sides.
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            # beta rides along free on the same info call; financial_models uses
            # the peer median when a company's own reported beta is not credible
            "beta": _clean(info.get("beta")),
            # with market cap, this gives each peer's D/E, which is what lets
            # financial_models.resolve_beta unlever a peer beta before taking the
            # median and re-lever it to the target's own capital structure
            # (reference doc §1.1.2). Free — same info call, no extra request.
            "total_debt": _clean(info.get("totalDebt")),
            "pe_trailing": _clean(info.get("trailingPE")),
            "pe_forward": _clean(info.get("forwardPE")),
            "price_to_book": _clean(info.get("priceToBook")),
            "ev_to_ebitda": _clean(info.get("enterpriseToEbitda")),
            "ev_to_revenue": _clean(info.get("enterpriseToRevenue")),
            "peg_ratio": _clean(info.get("pegRatio")),
            "operating_margin": _clean(info.get("operatingMargins")),
            "revenue_growth": _clean(info.get("revenueGrowth")),
        }

    @_ttl_cached
    def get_filings(self, ticker: str) -> list[dict]:
        """Dated regulatory events from SEC EDGAR, shaped like news items.

        Why this exists: the yfinance news feed carries only ~10 recent stories
        per feed, so a 5-year chart had 2 event markers on it. SEC filings are
        free, need no key, and go back ~5 years — AAPL returns 209 distinct
        dates. They are *events*, not headlines, so they carry their own
        categories and the UI tags them separately.

        US-only: EDGAR has no CIK for HK listings, so those return [] rather
        than paying a guaranteed round-trip to fail.
        """
        if "." in ticker:  # 0700.HK and friends are not in EDGAR
            return []
        try:
            # deferred: importing openbb costs ~5 s, so only a request that
            # actually wants filings pays it, and only once per process
            from openbb import obb
            rows = obb.equity.fundamental.filings(
                symbol=ticker.upper(), provider="sec", limit=FILINGS_LIMIT).results
        except Exception:
            return []  # unknown symbol, network failure, or EDGAR rate limit

        items = []
        for r in rows:
            report_type = (getattr(r, "report_type", "") or "").upper()
            category = FILING_CATEGORIES.get(report_type)
            if category is None:
                continue  # 144, SC 13G/A, PX14A6G ... noise for a price chart
            date = str(getattr(r, "filing_date", "") or "")[:10]
            if not date:
                continue
            items.append({
                "title": _filing_title(report_type, r),
                "summary": "",
                "date": date,
                "url": getattr(r, "filing_detail_url", None)
                       or getattr(r, "report_url", None),
                "publisher": "SEC EDGAR",
                "category": category,
            })
        return items

    @_ttl_cached
    def get_fundamentals(self, ticker: str) -> dict:
        """Raw statement data + key info fields the model layer needs."""
        t = yf.Ticker(ticker)
        info = t.info or {}

        estimates = {"revenue_growth_fwd": None, "earnings_growth_fwd": None}
        try:
            rev_est = t.revenue_estimate
            if rev_est is not None and "+1y" in rev_est.index:
                estimates["revenue_growth_fwd"] = _clean(float(rev_est.loc["+1y", "growth"]))
            gr = t.growth_estimates
            if gr is not None and "+1y" in gr.index:
                estimates["earnings_growth_fwd"] = _clean(float(gr.loc["+1y", "stockTrend"]))
        except Exception:
            pass  # estimates are optional enrichment

        def frame_to_dict(df):
            if df is None or df.empty:
                return {}
            out = {}
            for col in df.columns:  # columns are period-end timestamps
                key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                out[key] = {
                    str(idx): _clean(float(v)) if isinstance(v, (int, float)) else None
                    for idx, v in df[col].items()
                }
            return out

        return {
            "ticker": ticker.upper(),
            "info": {k: _clean(info.get(k)) for k in INFO_KEYS},
            "estimates": estimates,
            "income_statement": frame_to_dict(t.income_stmt),
            "balance_sheet": frame_to_dict(t.balance_sheet),
            "cash_flow": frame_to_dict(t.cash_flow),
        }


provider = YFinanceProvider()
