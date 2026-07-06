from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from director import db
from director.blocks import OFF_AIR_END
from director.dashboard_data import (
    delete_item,
    describe_item,
    get_day_schedule,
    get_now_and_next,
    program_items_after,
    replace_item,
    search_catalog,
)
from director.timeutil import combine_msk

T0 = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def add_series(conn, name):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))
    return conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]


def add_episode(conn, series_id, season, episode, duration=600, title="Title"):
    path = f"/fake/{series_id}/{season}/{episode}"
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (series_id, season, episode, title, path, duration),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path = ?", (path,)).fetchone()["id"]


def add_ad(conn, path, duration=30):
    conn.execute(
        "INSERT INTO ads (file_path, duration_seconds, scanned_at) VALUES (?, ?, datetime('now'))",
        (path, duration),
    )
    return conn.execute("SELECT id FROM ads WHERE file_path = ?", (path,)).fetchone()["id"]


def log_row(conn, start, end, item_type="episode", item_id=None, status="scheduled", block_name=None):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status, block_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (start.isoformat(), end.isoformat(), item_type, item_id, status, block_name),
    )
    return conn.execute("SELECT id FROM program_log ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_describe_item_for_each_type(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep_id = add_episode(conn, sid, 1, 3, title="Ep Title")
    ad_id = add_ad(conn, "/ads/a.mp4")

    ep_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("episode", ep_id)).fetchone()
    assert describe_item(conn, ep_row) == "Show S01E03 - Ep Title"

    ad_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("ad", ad_id)).fetchone()
    assert "/ads/a.mp4" in describe_item(conn, ad_row)

    off_air_row = conn.execute("SELECT 'off_air' AS item_type, NULL AS item_id").fetchone()
    assert describe_item(conn, off_air_row) == "ТЕХПЕРЕРЫВ"


def test_describe_item_for_a_card(tmp_path):
    conn = make_db(tmp_path)
    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, status) "
        "VALUES ('epg_next', '2026-07-06', ?, 60, 'pending')",
        (T0.isoformat(),),
    )
    cid = conn.execute("SELECT id FROM cards ORDER BY id DESC LIMIT 1").fetchone()["id"]
    row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("card", cid)).fetchone()
    assert describe_item(conn, row) == "[КАРТОЧКА:epg_next]"


def test_program_items_after_returns_only_upcoming_programmes(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)
    ad_id = add_ad(conn, "/ads/a.mp4")
    log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)
    log_row(conn, T0 + timedelta(minutes=10), T0 + timedelta(minutes=12), item_type="ad", item_id=ad_id)
    log_row(conn, T0 + timedelta(minutes=12), T0 + timedelta(minutes=22), item_id=ep2)

    nxt = program_items_after(conn, T0.isoformat(), count=3)
    # ep1 isn't strictly after T0, the ad is not a programme -> only ep2 qualifies.
    assert [r["item_id"] for r in nxt] == [ep2]


def test_get_now_and_next_returns_current_plus_upcoming(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)
    log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)
    log_row(conn, T0 + timedelta(minutes=10), T0 + timedelta(minutes=20), item_id=ep2)

    current, upcoming = get_now_and_next(conn, T0 + timedelta(minutes=5), count=5)
    assert current["item_id"] == ep1
    assert [r["item_id"] for r in upcoming] == [ep2]


def test_get_now_and_next_current_is_none_when_nothing_is_airing(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)

    # Query for a time before the schedule even starts.
    current, upcoming = get_now_and_next(conn, T0 - timedelta(hours=1), count=5)
    assert current is None
    assert [r["item_id"] for r in upcoming] == [ep1]


def test_get_day_schedule_matches_broadcast_day_boundaries(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep = add_episode(conn, sid, 1, 1)
    d = date(2026, 7, 6)
    inside = combine_msk(d, OFF_AIR_END)
    log_row(conn, inside, inside + timedelta(minutes=10), item_id=ep)
    outside = combine_msk(d - timedelta(days=1), OFF_AIR_END) - timedelta(minutes=1)
    log_row(conn, outside, outside + timedelta(minutes=1), item_id=ep)

    rows = get_day_schedule(conn, d)
    assert len(rows) == 1
    assert rows[0]["start_time"] == inside.isoformat()


def test_search_catalog_filters_episodes_by_series_or_title(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Avatar")
    add_episode(conn, sid, 1, 1, title="The Boy in the Iceberg")
    other = add_series(conn, "Zim")
    add_episode(conn, other, 1, 1, title="Nightmare")

    results = search_catalog(conn, "episode", query="Avatar")
    assert len(results) == 1
    assert results[0]["series_name"] == "Avatar"


def test_replace_item_swaps_content_but_keeps_the_time_slot(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)
    row_id = log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)

    replace_item(conn, row_id, "episode", ep2)

    row = conn.execute("SELECT * FROM program_log WHERE id = ?", (row_id,)).fetchone()
    assert row["item_id"] == ep2
    assert row["start_time"] == T0.isoformat()
    assert row["end_time"] == (T0 + timedelta(minutes=10)).isoformat()


def test_replace_item_rejects_already_aired_rows(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)
    row_id = log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1, status="played")

    with pytest.raises(ValueError):
        replace_item(conn, row_id, "episode", ep2)


def test_replace_item_rejects_unknown_target(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    row_id = log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)

    with pytest.raises(ValueError):
        replace_item(conn, row_id, "episode", 99999)


def test_delete_item_pulls_the_next_rows_start_time_back(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)
    row1 = log_row(conn, T0, T0 + timedelta(minutes=10), item_id=ep1)
    row2 = log_row(conn, T0 + timedelta(minutes=10), T0 + timedelta(minutes=20), item_id=ep2)

    delete_item(conn, row1)

    remaining = conn.execute("SELECT * FROM program_log").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["id"] == row2
    assert remaining[0]["start_time"] == T0.isoformat()  # pulled back, no gap


def test_delete_item_refuses_off_air(tmp_path):
    conn = make_db(tmp_path)
    row_id = log_row(conn, T0, T0 + timedelta(hours=5), item_type="off_air")

    with pytest.raises(ValueError):
        delete_item(conn, row_id)
