"""Reconciles wall-clock time against the generated schedule.

The core idea: every poll tick asks "what does the schedule say should be on
air right now?" and compares that to what's currently applied. This is
naturally drift-correcting - there's no accumulated state to compound errors,
each tick re-derives the answer from absolute time. If real playback runs
long or short, the next tick just cuts to whatever the schedule says is
current, which is also exactly the hard-cutover behavior wanted for the
05:00 MSK off-air boundary.
"""

import sqlite3
from datetime import datetime

_ITEM_TABLES = {"episode": "episodes", "ad": "ads", "bumper": "bumpers"}


def find_current_row(conn: sqlite3.Connection, now_utc: datetime) -> sqlite3.Row | None:
    now_iso = now_utc.isoformat()
    return conn.execute(
        "SELECT * FROM program_log WHERE start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1",
        (now_iso, now_iso),
    ).fetchone()


def resolve_media_path(conn: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    table = _ITEM_TABLES.get(row["item_type"])
    if table is None:  # off_air
        return None
    result = conn.execute(f"SELECT file_path FROM {table} WHERE id = ?", (row["item_id"],)).fetchone()
    return result["file_path"] if result else None


def advance_status(conn: sqlite3.Connection, previous_row_id: int | None, now_utc: datetime) -> None:
    """Marks the row we're moving on from as played (and logs it to
    play_history), and anything else that fully elapsed while still
    'scheduled' as skipped - e.g. the controller was down and wall-clock
    jumped over it entirely."""
    now_iso = now_utc.isoformat()

    if previous_row_id is not None:
        row = conn.execute(
            "SELECT * FROM program_log WHERE id = ? AND status = 'scheduled' AND end_time <= ?",
            (previous_row_id, now_iso),
        ).fetchone()
        if row is not None:
            conn.execute("UPDATE program_log SET status = 'played' WHERE id = ?", (previous_row_id,))
            if row["item_type"] in ("episode", "ad", "bumper"):
                conn.execute(
                    "INSERT INTO play_history (item_type, item_id, played_at) VALUES (?, ?, ?)",
                    (row["item_type"], row["item_id"], row["start_time"]),
                )

    conn.execute(
        "UPDATE program_log SET status = 'skipped' WHERE status = 'scheduled' AND end_time <= ?",
        (now_iso,),
    )
    conn.commit()
