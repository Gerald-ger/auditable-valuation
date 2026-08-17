"""Persistence contract for score history and positions.

The score history is the calibration record — if it silently drops rows, loses
the price column, or double-counts a day, every future accuracy measurement is
wrong and there is no way to tell after the fact.
"""
from __future__ import annotations

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
