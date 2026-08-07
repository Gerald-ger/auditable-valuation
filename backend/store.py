"""Local persistence: score history and watchlist/positions.

Why this exists: without it every page load was amnesiac. Nothing recorded what
a company scored last month, so the scoring engine could never be calibrated
against forward returns — the anchor tables in scoring.py stayed unfalsifiable
by construction (docs/scoring-system-design.md §5 admits validation covers
consistency, not forward returns).

Each row therefore stores the **price at scoring time** alongside the score.
That single column is what makes "did an S tier actually outperform a C tier?"
answerable later; the scores alone would not be.

SQLite, one file, no server. A fresh connection per call keeps this safe across
uvicorn's threadpool without any global connection state.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"

PILLARS = ("valuation", "quality", "health", "growth", "momentum")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS score_history (
    ticker         TEXT    NOT NULL,
    as_of_date     TEXT    NOT NULL,          -- UTC date, one row per ticker per day
    composite      INTEGER,
    tier           TEXT,
    tier_label     TEXT,
    confidence     TEXT,
    coverage_pct   INTEGER,
    classification TEXT,
    valuation      INTEGER,
    quality        INTEGER,
    health         INTEGER,
    growth         INTEGER,
    momentum       INTEGER,
    price          REAL,                      -- price when scored: the calibration anchor
    currency       TEXT,
    flags          TEXT,                      -- JSON array
    recorded_at    TEXT    NOT NULL,
    PRIMARY KEY (ticker, as_of_date)
);

CREATE TABLE IF NOT EXISTS drawings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT    NOT NULL,
    kind       TEXT    NOT NULL,          -- 'trendline' | 'hline'
    -- true UTC epochs, never chart-space time: the chart shifts for display
    -- (GMT+8) but a drawing must survive a change of display timezone
    t1         INTEGER,
    p1         REAL    NOT NULL,
    t2         INTEGER,
    p2         REAL,
    label      TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS drawings_ticker ON drawings(ticker);

CREATE TABLE IF NOT EXISTS positions (
    ticker     TEXT PRIMARY KEY,
    shares     REAL NOT NULL DEFAULT 0,       -- 0 = watchlist-only entry
    cost_basis REAL,                          -- per share, in the listing currency
    note       TEXT,
    added_at   TEXT NOT NULL
);
"""


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")  # batch writes must not block UI reads
        c.executescript(_SCHEMA)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── score history ────────────────────────────────────────────────────

def record_score(card: dict, info: dict) -> None:
    """Upsert one row per ticker per UTC day. Re-scoring the same day overwrites.

    Cards with no composite (all pillars insufficient) are not recorded — an
    empty score is not an observation, and it would pollute the calibration set.
    """
    if card.get("composite_score") is None:
        return
    pillars = card.get("pillars", {})
    row = {
        "ticker": card["ticker"],
        "as_of_date": card["as_of"][:10],
        "composite": card["composite_score"],
        "tier": card.get("tier"),
        "tier_label": card.get("tier_label"),
        "confidence": card.get("confidence"),
        "coverage_pct": card.get("coverage_pct"),
        "classification": card.get("classification"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "currency": info.get("currency"),
        "flags": json.dumps(card.get("flags", [])),
        "recorded_at": _utc_now(),
    }
    for p in PILLARS:
        row[p] = (pillars.get(p) or {}).get("score")

    cols = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row if k not in ("ticker", "as_of_date"))
    with _conn() as c:
        c.execute(
            f"INSERT INTO score_history ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(ticker, as_of_date) DO UPDATE SET {updates}",
            row,
        )


def score_history(ticker: str, limit: int = 365) -> list[dict]:
    """Oldest-first, so the frontend can plot it directly."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM score_history WHERE ticker = ? "
            "ORDER BY as_of_date DESC LIMIT ?",
            (ticker.upper(), limit),
        ).fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


def latest_scores(tickers: list[str] | None = None) -> dict[str, dict]:
    """Most recent row per ticker, keyed by ticker."""
    sql = ("SELECT s.* FROM score_history s JOIN "
           "(SELECT ticker, MAX(as_of_date) AS d FROM score_history GROUP BY ticker) m "
           "ON s.ticker = m.ticker AND s.as_of_date = m.d")
    params: tuple = ()
    if tickers:
        sql += f" WHERE s.ticker IN ({', '.join('?' * len(tickers))})"
        params = tuple(t.upper() for t in tickers)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return {r["ticker"]: _row_to_dict(r) for r in rows}


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["flags"] = json.loads(d["flags"]) if d.get("flags") else []
    return d


# ── watchlist / positions ────────────────────────────────────────────

def upsert_position(ticker: str, shares: float = 0.0,
                    cost_basis: float | None = None, note: str | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO positions (ticker, shares, cost_basis, note, added_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "shares=excluded.shares, cost_basis=excluded.cost_basis, note=excluded.note",
            (ticker.upper(), shares, cost_basis, note, _utc_now()),
        )


def delete_position(ticker: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM positions WHERE ticker = ?", (ticker.upper(),))


def list_positions() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
    return [dict(r) for r in rows]


# ── chart drawings ───────────────────────────────────────────────────
#
# Stored server-side rather than in the browser so the AI can read them without
# the page posting its canvas state on every request, and so they follow the
# analysis rather than the machine it was drawn on.

def add_drawing(ticker: str, kind: str, p1: float, t1: int | None = None,
                t2: int | None = None, p2: float | None = None,
                label: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO drawings (ticker, kind, t1, p1, t2, p2, label, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker.upper(), kind, t1, p1, t2, p2, label, _utc_now()),
        )
        return cur.lastrowid


def list_drawings(ticker: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM drawings WHERE ticker = ? ORDER BY id", (ticker.upper(),)
        ).fetchall()
    return [dict(r) for r in rows]


def update_drawing(drawing_id: int, **fields) -> None:
    """Move an endpoint. Only geometry and the label are mutable."""
    allowed = {k: v for k, v in fields.items() if k in ("t1", "p1", "t2", "p2", "label")}
    if not allowed:
        return
    sets = ", ".join(f"{k} = :{k}" for k in allowed)
    with _conn() as c:
        c.execute(f"UPDATE drawings SET {sets} WHERE id = :id", {**allowed, "id": drawing_id})


def delete_drawing(drawing_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM drawings WHERE id = ?", (drawing_id,))


def clear_drawings(ticker: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM drawings WHERE ticker = ?", (ticker.upper(),))
