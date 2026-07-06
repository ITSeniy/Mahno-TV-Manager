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
from pathlib import Path

from director.ad_pods import pick_bumper
from director.ntsc_render import is_render_valid

_ITEM_TABLES = {"episode": "episodes", "ad": "ads", "bumper": "bumpers"}


def _resolve_card(conn: sqlite3.Connection, item_id: int) -> tuple[str | None, bool]:
    """Cards are generated, not scanned, so validity is simply 'the render job
    finished and the file is on disk' rather than the source-mtime check used
    for library files. If a card hasn't been rendered yet (the profilaktika job
    hasn't caught up, or it failed), fall back to a static interstitial bumper
    so the slot isn't dead air - the program_log stays authoritative either way."""
    card = conn.execute("SELECT rendered_path, status FROM cards WHERE id = ?", (item_id,)).fetchone()
    if card is not None and card["status"] == "rendered" and card["rendered_path"] and Path(card["rendered_path"]).exists():
        return card["rendered_path"], True  # ntsc-rs already baked in, live filters stay off

    fallback = pick_bumper(conn, kind="interstitial")
    if fallback is not None:
        if is_render_valid(fallback):
            return fallback["rendered_path"], True
        return fallback["file_path"], False
    return None, False


def find_current_row(conn: sqlite3.Connection, now_utc: datetime) -> sqlite3.Row | None:
    now_iso = now_utc.isoformat()
    return conn.execute(
        "SELECT * FROM program_log WHERE start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1",
        (now_iso, now_iso),
    ).fetchone()


def resolve_media_path(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str | None, bool]:
    """Returns (path_to_play, is_ntsc_rendered). This is a read-only lookup -
    it never triggers a render itself (see ntsc_render.py for why: a single
    render can take minutes, far too slow for the live poll loop). If
    nothing's been pre-rendered yet, it just returns the raw source path
    with is_ntsc_rendered=False, so the caller can fall back to the live
    obs-retro-effects filters for that item instead."""
    if row["item_type"] == "card":
        return _resolve_card(conn, row["item_id"])

    table = _ITEM_TABLES.get(row["item_type"])
    if table is None:  # off_air
        return None, False

    result = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row["item_id"],)).fetchone()
    if result is None:
        return None, False

    if is_render_valid(result):
        return result["rendered_path"], True
    return result["file_path"], False


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
