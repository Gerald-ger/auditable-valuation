"""Persistence contract for score history and positions.

The score history is the calibration record — if it silently drops rows, loses
the price column, or double-counts a day, every future accuracy measurement is
wrong and there is no way to tell after the fact.
"""
from __future__ import annotations

import pytest

from conftest import load_fundamentals

from backend import scoring


def _card(stem="MSFT"):
    f = load_fundamentals(stem)
    return scoring.score_company(f), f["info"]


def test_same_day_rescore_updates_one_row(temp_db):
    card, info = _card()
    temp_db.record_score(card, info)
    temp_db.record_score(card, info)
    history = temp_db.score_history(card["ticker"])
    assert len(history) == 1


def test_price_is_recorded_for_calibration(temp_db):
    card, info = _card()
    temp_db.record_score(card, info)
    row = temp_db.score_history(card["ticker"])[0]
    assert row["price"] == info["currentPrice"] or row["price"] == info["regularMarketPrice"]
    assert row["price"] is not None, "without price, forward returns cannot be computed"
    assert row["currency"] == info["currency"]


def test_pillars_are_recorded(temp_db):
    card, info = _card()
    temp_db.record_score(card, info)
    row = temp_db.score_history(card["ticker"])[0]
    for pillar in temp_db.PILLARS:
        assert row[pillar] == card["pillars"][pillar]["score"]


def test_uncomposable_card_is_not_recorded(temp_db, empty_fundamentals):
    card = scoring.score_company(empty_fundamentals)
    assert card["composite_score"] is None
    temp_db.record_score(card, {})
    assert temp_db.score_history("NULL") == []


def test_history_is_oldest_first(temp_db):
    card, info = _card()
    temp_db.record_score(card, info)
    with temp_db._conn() as c:
        c.execute("INSERT INTO score_history (ticker, as_of_date, composite, recorded_at) "
                  "VALUES (?, ?, ?, ?)", (card["ticker"], "2020-01-01", 40, "x"))
    dates = [r["as_of_date"] for r in temp_db.score_history(card["ticker"])]
    assert dates == sorted(dates)


def test_latest_scores_returns_the_newest_row(temp_db):
    card, info = _card()
    temp_db.record_score(card, info)
    with temp_db._conn() as c:
        c.execute("INSERT INTO score_history (ticker, as_of_date, composite, recorded_at) "
                  "VALUES (?, ?, ?, ?)", (card["ticker"], "2020-01-01", 40, "x"))
    latest = temp_db.latest_scores([card["ticker"]])
    assert latest[card["ticker"]]["composite"] == card["composite_score"]


def test_position_roundtrip_and_upsert(temp_db):
    temp_db.upsert_position("msft", 10, 350.0, "core")
    temp_db.upsert_position("MSFT", 12, 360.0, "added")
    rows = temp_db.list_positions()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MSFT"
    assert rows[0]["shares"] == 12
    assert rows[0]["cost_basis"] == 360.0


def test_watchlist_entry_has_zero_shares(temp_db):
    temp_db.upsert_position("AAPL")
    row = temp_db.list_positions()[0]
    assert row["shares"] == 0
    assert row["cost_basis"] is None


def test_delete_position(temp_db):
    temp_db.upsert_position("AAPL", 1, 100.0)
    temp_db.delete_position("aapl")
    assert temp_db.list_positions() == []


# ── schema migrations ────────────────────────────────────────────────
#
# The machinery, not any particular migration — `_MIGRATIONS` is empty today, so
# without these the first entry anyone appends would be the first time the
# mechanism ever ran. It has to be proven while there is nothing at stake.


def _columns(store, table):
    with store._conn() as c:
        return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


def _version(store):
    with store._conn() as c:
        return c.execute("PRAGMA user_version").fetchone()[0]


def test_a_fresh_database_is_stamped_with_the_current_schema_version(temp_db):
    # `temp_db` has already called init(). A fresh database must come out at the
    # same version as a migrated one, or the next migration runs twice on one of
    # them and not at all on the other.
    assert _version(temp_db) == len(temp_db._MIGRATIONS)


def test_a_migration_upgrades_an_existing_database_without_losing_its_rows(
        temp_db, monkeypatch):
    """The property that matters. A schema change must reach a database that
    already has history in it — `score_history` cannot be backfilled, so
    recreating the table instead of altering it silently restarts the
    calibration record that table exists to accumulate."""
    card, info = _card()
    temp_db.record_score(card, info)
    assert len(temp_db.score_history(card["ticker"])) == 1

    monkeypatch.setattr(
        temp_db, "_MIGRATIONS",
        ["ALTER TABLE score_history ADD COLUMN scoring_engine_version TEXT;"])
    temp_db.init()

    assert "scoring_engine_version" in _columns(temp_db, "score_history")
    assert _version(temp_db) == 1
    assert len(temp_db.score_history(card["ticker"])) == 1, "the row must survive"


def test_a_migration_is_not_applied_twice(temp_db, monkeypatch):
    # `ALTER TABLE ... ADD COLUMN` raises on a column that already exists, so a
    # second init() re-running the same entry would fail loudly here.
    monkeypatch.setattr(
        temp_db, "_MIGRATIONS",
        ["ALTER TABLE positions ADD COLUMN broker TEXT;"])
    temp_db.init()
    temp_db.init()
    assert _version(temp_db) == 1
    assert _columns(temp_db, "positions").count("broker") == 1


def test_migrations_resume_from_the_recorded_version(temp_db, monkeypatch):
    """Appending a second entry must apply only that entry to a database already
    carrying the first — the case that breaks if the version is ignored."""
    monkeypatch.setattr(temp_db, "_MIGRATIONS",
                        ["ALTER TABLE positions ADD COLUMN broker TEXT;"])
    temp_db.init()

    monkeypatch.setattr(temp_db, "_MIGRATIONS",
                        ["ALTER TABLE positions ADD COLUMN broker TEXT;",
                         "ALTER TABLE positions ADD COLUMN account TEXT;"])
    temp_db.init()

    columns = _columns(temp_db, "positions")
    assert "broker" in columns and "account" in columns
    assert _version(temp_db) == 2


# ── chart drawings ───────────────────────────────────────────────────
#
# This table had no test at all until 2026-08-27, and it was carrying two
# defects that no test would have needed to be clever to catch: the endpoints
# take a ticker in their path and did not pass it down, and neither store
# function looked at rowcount. So any ticker's URL could move or delete any
# drawing, and both reported `{"ok": true}` for an id that does not exist.
#
# Nothing noticed because the only client cannot notice: all three call sites in
# PriceChart.jsx discard the result, one of them saying why -- "a failed save
# must not break the gesture". A silent wrong answer and a silent right one look
# identical from there.

def _two_tickers(store):
    """One drawing on each of two tickers, to make cross-ticker reach visible."""
    return (store.add_drawing("AAPL", "hline", 100.0),
            store.add_drawing("MSFT", "hline", 200.0))


def test_a_drawing_moves_only_through_its_own_tickers_url(temp_db):
    aapl, _ = _two_tickers(temp_db)

    assert temp_db.update_drawing(aapl, "MSFT", p1=999.0) is False
    assert temp_db.list_drawings("AAPL")[0]["p1"] == 100.0, "moved through the wrong ticker"

    assert temp_db.update_drawing(aapl, "AAPL", p1=111.0) is True
    assert temp_db.list_drawings("AAPL")[0]["p1"] == 111.0


def test_a_drawing_is_deleted_only_through_its_own_tickers_url(temp_db):
    aapl, msft = _two_tickers(temp_db)

    assert temp_db.delete_drawing(aapl, "MSFT") is False
    assert len(temp_db.list_drawings("AAPL")) == 1, "deleted through the wrong ticker"
    assert len(temp_db.list_drawings("MSFT")) == 1, "deleted the wrong ticker's drawing"

    assert temp_db.delete_drawing(aapl, "AAPL") is True
    assert temp_db.list_drawings("AAPL") == []


def test_an_id_that_does_not_exist_is_reported_rather_than_reported_ok(temp_db):
    """The half that had already shipped: success for work never done."""
    assert temp_db.update_drawing(9999, "AAPL", p1=1.0) is False
    assert temp_db.delete_drawing(9999, "AAPL") is False


def test_a_patch_carrying_nothing_mutable_still_answers_about_the_id(temp_db):
    """Nothing to change is not the same as nothing to change it on.

    `DrawingPatch` has every field optional, so an empty body reaches the store
    with no mutable keys and never runs an UPDATE whose rowcount could answer
    the question. The id still has to be checked, or this one path goes back to
    reporting success for a drawing that does not exist.
    """
    aapl, _ = _two_tickers(temp_db)
    assert temp_db.update_drawing(aapl, "AAPL") is True
    assert temp_db.update_drawing(aapl, "MSFT") is False
    assert temp_db.update_drawing(9999, "AAPL") is False


def test_the_ticker_is_matched_case_insensitively(temp_db):
    """`add_drawing` upper-cases on the way in, so the lookups must too.

    Otherwise a lowercase URL -- which FastAPI passes through verbatim -- would
    404 against a drawing that is plainly there.
    """
    aapl, _ = _two_tickers(temp_db)
    assert temp_db.update_drawing(aapl, "aapl", p1=1.0) is True
    assert temp_db.delete_drawing(aapl, "aapl") is True


def test_the_endpoints_turn_a_miss_into_a_404(temp_db):
    """What the store's new boolean is for.

    Imported inside the test because `backend.main` pulls in the whole
    application; the rest of this module needs none of it.
    """
    from fastapi import HTTPException

    from backend import main

    aapl, _ = _two_tickers(temp_db)
    patch = main.DrawingPatch(p1=42.0)

    assert main.patch_drawing("AAPL", aapl, patch) == {"ok": True}

    for call in (lambda: main.patch_drawing("MSFT", aapl, patch),
                 lambda: main.patch_drawing("AAPL", 9999, patch),
                 lambda: main.remove_drawing("MSFT", aapl),
                 lambda: main.remove_drawing("AAPL", 9999)):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 404

    assert main.remove_drawing("AAPL", aapl) == {"ok": True}
