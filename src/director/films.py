"""Picks which film airs next - the event-style counterpart to rotation.py.

A film is a tentpole placed in a dedicated film-slot block (weekend prime). It
must not repeat within `repeat_days`, and among eligible films the
least-recently-aired goes first (never-aired films win ties). Which slot a film
fills is the scheduler's call; which film is this module's.
"""

import sqlite3
from datetime import datetime, timedelta


def film_reels(conn: sqlite3.Connection, film_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reels WHERE film_id = ? AND missing = 0 AND duration_seconds IS NOT NULL "
        "ORDER BY reel_number, file_path",
        (film_id,),
    ).fetchall()


def last_film_airing(conn: sqlite3.Connection, film_id: int) -> str:
    """Most recent time any reel of this film aired (empty string = never)."""
    row = conn.execute(
        """
        SELECT MAX(pl.start_time) AS t FROM program_log pl
        JOIN reels r ON r.id = pl.item_id
        WHERE pl.item_type IN ('film', 'reel') AND r.film_id = ?
        """,
        (film_id,),
    ).fetchone()
    return row["t"] or ""  # empty string sorts before any ISO timestamp -> "never aired" wins ties


def _reels_total_seconds(reels: list[sqlite3.Row]) -> float:
    return sum(r["duration_seconds"] for r in reels)


def pick_next_film(
    conn: sqlite3.Connection,
    eligible_film_ids: list[int],
    now_utc: datetime,
    repeat_days: int,
    max_total_seconds: float | None = None,
) -> tuple[int, list[sqlite3.Row]] | None:
    """Least-recently-aired eligible film that has reels, hasn't aired within
    repeat_days, and (if max_total_seconds is given) whose reels fit that
    budget. Returns (film_id, ordered reels) or None."""
    cutoff = (now_utc - timedelta(days=repeat_days)).isoformat()
    candidates: list[tuple[str, int, list[sqlite3.Row]]] = []
    for film_id in eligible_film_ids:
        reels = film_reels(conn, film_id)
        if not reels:
            continue
        if max_total_seconds is not None and _reels_total_seconds(reels) > max_total_seconds:
            continue
        last = last_film_airing(conn, film_id)
        if last and last >= cutoff:
            continue  # aired too recently to repeat
        candidates.append((last, film_id, reels))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))  # never-aired first, then oldest
    _, film_id, reels = candidates[0]
    return film_id, reels
