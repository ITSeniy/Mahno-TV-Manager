"""Read/write helpers for the operator dashboard: what's on air now, the EPG
grid for a day, and manual edits (replace/delete) to program_log rows that
haven't aired yet.

Editing philosophy matches the rest of the scheduler: a replacement keeps
the original start_time/end_time slot exactly as generated rather than
reflowing everything after it - the grid was never meant to line up to the
second (see PROJECT_PLAN.md risk #4), and OBS's own playback isn't
truncated to fit the slot either way, so a duration mismatch from a
replacement is no different from the pre-existing tolerance for drift.
Deleting an item instead pulls the following item's start time backward so
there's no dead-air gap.
"""

import sqlite3
from datetime import date, datetime, timedelta

from director.blocks import OFF_AIR_END
from director.timeutil import combine_msk

_ITEM_TABLES = {"episode": "episodes", "ad": "ads", "bumper": "bumpers"}


def describe_item(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    item_type = row["item_type"]
    item_id = row["item_id"]
    if item_type == "off_air":
        return "ТЕХПЕРЕРЫВ"
    if item_type == "episode":
        ep = conn.execute(
            "SELECT e.season, e.episode, e.title, s.name FROM episodes e "
            "JOIN series s ON s.id = e.series_id WHERE e.id = ?",
            (item_id,),
        ).fetchone()
        return f"{ep['name']} S{ep['season']:02d}E{ep['episode']:02d} - {ep['title']}" if ep else "эпизод (файл не найден)"
    if item_type == "ad":
        ad = conn.execute("SELECT file_path FROM ads WHERE id = ?", (item_id,)).fetchone()
        return f"[РЕКЛАМА] {ad['file_path']}" if ad else "реклама (файл не найден)"
    if item_type == "bumper":
        bumper = conn.execute("SELECT file_path, kind FROM bumpers WHERE id = ?", (item_id,)).fetchone()
        return f"[ЗАСТАВКА:{bumper['kind']}] {bumper['file_path']}" if bumper else "заставка (файл не найден)"
    if item_type == "card":
        card = conn.execute("SELECT kind FROM cards WHERE id = ?", (item_id,)).fetchone()
        return f"[КАРТОЧКА:{card['kind']}]" if card else "карточка (не найдена)"
    return item_type


# Program items = what a viewer would call "a programme": episodes and (later)
# films/reels, i.e. everything the on-screen EPG lists, skipping ads/bumpers/cards.
PROGRAM_ITEM_TYPES = ("episode", "film", "reel")


def program_items_after(conn: sqlite3.Connection, start_iso: str, count: int = 3) -> list[sqlite3.Row]:
    """The next `count` programmes starting after start_iso - the data behind an
    'epg_next' ("Далее") card."""
    placeholders = ", ".join("?" for _ in PROGRAM_ITEM_TYPES)
    return conn.execute(
        f"SELECT * FROM program_log WHERE start_time > ? AND item_type IN ({placeholders}) "
        "ORDER BY start_time LIMIT ?",
        (start_iso, *PROGRAM_ITEM_TYPES, count),
    ).fetchall()


def get_now_and_next(
    conn: sqlite3.Connection, now_utc: datetime, count: int = 6
) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
    """Returns (currently airing row or None, next `count` upcoming rows).
    current is None whenever "now" falls outside whatever's been generated
    (e.g. the schedule only covers future dates so far) - callers must not
    assume the first upcoming row is "on air now"."""
    now_iso = now_utc.isoformat()
    current = conn.execute(
        "SELECT * FROM program_log WHERE start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1",
        (now_iso, now_iso),
    ).fetchone()
    upcoming = conn.execute(
        "SELECT * FROM program_log WHERE start_time > ? ORDER BY start_time LIMIT ?",
        (now_iso, count),
    ).fetchall()
    return current, list(upcoming)


def get_day_schedule(conn: sqlite3.Connection, broadcast_date: date) -> list[sqlite3.Row]:
    day_start = combine_msk(broadcast_date, OFF_AIR_END).isoformat()
    day_end = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_END).isoformat()
    return conn.execute(
        "SELECT * FROM program_log WHERE start_time >= ? AND start_time < ? ORDER BY start_time",
        (day_start, day_end),
    ).fetchall()


def search_catalog(conn: sqlite3.Connection, item_type: str, query: str = "", limit: int = 30) -> list[sqlite3.Row]:
    like = f"%{query}%"
    if item_type == "episode":
        return conn.execute(
            "SELECT e.id, e.season, e.episode, e.title, s.name AS series_name, e.duration_seconds "
            "FROM episodes e JOIN series s ON s.id = e.series_id "
            "WHERE e.missing = 0 AND (s.name LIKE ? OR e.title LIKE ?) "
            "ORDER BY s.name, e.season, e.episode LIMIT ?",
            (like, like, limit),
        ).fetchall()
    table = _ITEM_TABLES.get(item_type)
    if table is None:
        return []
    return conn.execute(
        f"SELECT id, file_path, duration_seconds FROM {table} "
        "WHERE missing = 0 AND file_path LIKE ? ORDER BY file_path LIMIT ?",
        (like, limit),
    ).fetchall()


def replace_item(conn: sqlite3.Connection, program_log_id: int, item_type: str, item_id: int) -> None:
    row = conn.execute("SELECT * FROM program_log WHERE id = ?", (program_log_id,)).fetchone()
    if row is None:
        raise ValueError(f"program_log #{program_log_id} not found")
    if row["status"] != "scheduled":
        raise ValueError("can only edit items that haven't aired yet")
    if row["item_type"] == "off_air" or item_type not in _ITEM_TABLES:
        raise ValueError(f"unsupported item_type: {item_type}")

    table = _ITEM_TABLES[item_type]
    exists = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if exists is None:
        raise ValueError(f"{item_type} #{item_id} not found")

    conn.execute(
        "UPDATE program_log SET item_type = ?, item_id = ? WHERE id = ?",
        (item_type, item_id, program_log_id),
    )
    conn.commit()


def delete_item(conn: sqlite3.Connection, program_log_id: int) -> None:
    row = conn.execute("SELECT * FROM program_log WHERE id = ?", (program_log_id,)).fetchone()
    if row is None:
        raise ValueError(f"program_log #{program_log_id} not found")
    if row["status"] != "scheduled":
        raise ValueError("can only edit items that haven't aired yet")
    if row["item_type"] == "off_air":
        raise ValueError("cannot delete the off-air block")

    next_row = conn.execute(
        "SELECT id FROM program_log WHERE start_time = ? LIMIT 1", (row["end_time"],)
    ).fetchone()
    if next_row is not None:
        conn.execute("UPDATE program_log SET start_time = ? WHERE id = ?", (row["start_time"], next_row["id"]))
    conn.execute("DELETE FROM program_log WHERE id = ?", (program_log_id,))
    conn.commit()
