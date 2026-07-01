from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from director import db
from director.blocks import OFF_AIR_END, OFF_AIR_START
from director.scheduler import generate_day, generate_schedule
from director.timeutil import combine_msk


def build_rich_library(conn):
    """5 series x 20 episodes (~20 min each), 30 ads (20-40s), 10 bumpers (~10s) -
    comfortably more than a broadcast day needs, so rotation never exhausts."""
    for s in range(5):
        conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (f"Show {s}", f"/show{s}"))
        series_id = conn.execute("SELECT id FROM series WHERE name = ?", (f"Show {s}",)).fetchone()["id"]
        for ep in range(1, 21):
            duration = 1200 + (ep % 3) * 60  # 20-22 min, a bit of variety
            conn.execute(
                "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
                "VALUES (?, 1, ?, ?, ?, ?, datetime('now'))",
                (series_id, ep, f"Episode {ep}", f"/show{s}/e{ep}.mkv", duration),
            )
    for a in range(30):
        duration = 20 + (a % 5) * 5  # 20-40s
        conn.execute(
            "INSERT INTO ads (file_path, duration_seconds, scanned_at) VALUES (?, ?, datetime('now'))",
            (f"/ads/ad{a}.mp4", duration),
        )
    for b in range(10):
        conn.execute(
            "INSERT INTO bumpers (file_path, kind, duration_seconds, scanned_at) VALUES (?, 'id', ?, datetime('now'))",
            (f"/bumpers/b{b}.mp4", 10),
        )
    conn.commit()


def build_sparse_library(conn):
    """Only one series and no ads/bumpers at all. The rotation cursor still
    cycles the same 2 episodes indefinitely (that's correct - a rerun channel
    with a tiny library just repeats what it has), but with no filler content
    available this exercises the path where ad breaks and the final padding
    loop toward 05:00 have nothing to insert."""
    conn.execute("INSERT INTO series (name, root_path) VALUES ('Only Show', '/only')")
    series_id = conn.execute("SELECT id FROM series WHERE name = 'Only Show'").fetchone()["id"]
    for ep in range(1, 3):
        conn.execute(
            "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
            "VALUES (?, 1, ?, ?, ?, 1200, datetime('now'))",
            (series_id, ep, f"Episode {ep}", f"/only/e{ep}.mkv"),
        )
    conn.commit()


def assert_day_is_contiguous(conn, broadcast_date: date):
    day_start = combine_msk(broadcast_date, OFF_AIR_END)
    day_end = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_END)
    rows = conn.execute(
        "SELECT * FROM program_log WHERE start_time >= ? AND start_time < ? ORDER BY start_time",
        (day_start.isoformat(), day_end.isoformat()),
    ).fetchall()
    assert rows, "expected at least one row"

    assert rows[0]["start_time"] == day_start.isoformat()
    assert rows[-1]["end_time"] == day_end.isoformat()
    assert rows[-1]["item_type"] == "off_air"

    for prev, nxt in zip(rows, rows[1:]):
        assert prev["end_time"] == nxt["start_time"], "gap or overlap between consecutive items"

    off_air_boundary = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_START).isoformat()
    for row in rows:
        if row["item_type"] == "episode":
            assert row["end_time"] <= off_air_boundary, "an episode ran past the 05:00 MSK off-air boundary"

    return rows


def test_generate_day_produces_contiguous_24h_timeline(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    build_rich_library(conn)

    broadcast_date = date(2026, 7, 6)  # a Monday, so DEFAULT_BLOCKS apply
    generate_day(conn, broadcast_date)
    rows = assert_day_is_contiguous(conn, broadcast_date)

    item_types = {row["item_type"] for row in rows}
    assert "episode" in item_types
    assert "ad" in item_types  # a 19h day at 20-25 min cadence should trigger multiple ad breaks
    assert "bumper" in item_types


def test_generate_day_handles_library_with_no_ads_or_bumpers(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    build_sparse_library(conn)

    broadcast_date = date(2026, 7, 6)
    generate_day(conn, broadcast_date)
    rows = assert_day_is_contiguous(conn, broadcast_date)

    # No ad/bumper content exists, so ad breaks and end-of-day padding must be
    # skipped gracefully rather than crashing.
    item_types = {row["item_type"] for row in rows}
    assert item_types <= {"episode", "off_air"}

    # The episodes keep cycling right up to (at most one episode short of) the
    # nominal 05:00 MSK cutoff - off-air isn't hours early just because the
    # library is small, only up to the length of the last unfinished gap.
    off_air_row = rows[-1]
    off_air_duration = (
        datetime.fromisoformat(off_air_row["end_time"]) - datetime.fromisoformat(off_air_row["start_time"])
    ).total_seconds()
    assert 5 * 3600 <= off_air_duration <= 5 * 3600 + 1200


def test_generate_schedule_is_idempotent_per_day(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    build_rich_library(conn)

    start = date(2026, 7, 6)
    first = generate_schedule(conn, start, 2)
    assert all(count > 0 for count in first.values())

    second = generate_schedule(conn, start, 2)
    assert all(count == 0 for count in second.values())  # already generated -> skipped, no duplicates

    total_rows = conn.execute("SELECT COUNT(*) AS c FROM program_log").fetchone()["c"]
    # re-running generate_schedule must not have added anything
    third = generate_schedule(conn, start, 2)
    assert all(count == 0 for count in third.values())
    assert conn.execute("SELECT COUNT(*) AS c FROM program_log").fetchone()["c"] == total_rows


def test_weekend_event_override_is_applied(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    build_rich_library(conn)

    saturday = date(2026, 7, 4)
    assert saturday.weekday() == 5
    generate_day(conn, saturday)

    rows = conn.execute(
        "SELECT DISTINCT block_name, event_name FROM program_log WHERE event_name IS NOT NULL"
    ).fetchall()
    assert rows, "weekend generation should have used the marathon event override"
    assert all(r["event_name"] == "выходной марафон" for r in rows)
    assert any(r["block_name"] == "марафон" for r in rows)


def test_raises_when_catalog_is_empty(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    with pytest.raises(RuntimeError):
        generate_day(conn, date(2026, 7, 6))
