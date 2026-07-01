"""Picks what airs next, the way a syndication rerun rotation works:

Each series is tagged 'sequential' or 'random' (series.rotation_mode) - a
curation call, not something derived from the files themselves. Serialized
shows with story arcs ("premieres") air in (season, episode) order via a
cursor that wraps once exhausted. Shows with no continuity ("random reruns")
draw randomly from whichever episodes have sat unaired longest, so it plays
like a real rerun rotation instead of a fixed loop.

Which SERIES gets the next slot (independent of the mode above) is
round-robin by "longest since last aired", skipping a series that would
break the max-consecutive-same-series rule for the current block.
"""

import random
import sqlite3


def series_episode_order(conn: sqlite3.Connection, series_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM episodes WHERE series_id = ? AND missing = 0 AND duration_seconds IS NOT NULL "
        "ORDER BY season, episode, file_path",
        (series_id,),
    ).fetchall()


def last_aired_episode_id(conn: sqlite3.Connection, series_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT e.id FROM program_log pl
        JOIN episodes e ON e.id = pl.item_id
        WHERE pl.item_type = 'episode' AND e.series_id = ?
        ORDER BY pl.start_time DESC LIMIT 1
        """,
        (series_id,),
    ).fetchone()
    return row["id"] if row else None


def last_aired_time(conn: sqlite3.Connection, series_id: int) -> str:
    row = conn.execute(
        """
        SELECT MAX(pl.start_time) AS t FROM program_log pl
        JOIN episodes e ON e.id = pl.item_id
        WHERE pl.item_type = 'episode' AND e.series_id = ?
        """,
        (series_id,),
    ).fetchone()
    return row["t"] or ""  # empty string sorts before any ISO timestamp -> "never aired" wins ties


def _last_aired_time_for_episode(conn: sqlite3.Connection, episode_id: int) -> str:
    row = conn.execute(
        "SELECT MAX(start_time) AS t FROM program_log WHERE item_type = 'episode' AND item_id = ?",
        (episode_id,),
    ).fetchone()
    return row["t"] or ""


def _next_sequential_episode(order: list[sqlite3.Row], last_id: int | None) -> sqlite3.Row:
    if last_id is None:
        return order[0]
    ids = [row["id"] for row in order]
    idx = ids.index(last_id) if last_id in ids else -1
    return order[(idx + 1) % len(order)]


def _next_random_episode(conn: sqlite3.Connection, order: list[sqlite3.Row]) -> sqlite3.Row:
    """Draws from the stalest half of the catalog (never-aired episodes sort
    first) rather than always picking the single least-recently-aired one, so
    reruns don't fall into a predictable fixed loop."""
    scored = sorted(order, key=lambda ep: _last_aired_time_for_episode(conn, ep["id"]))
    pool_size = max(1, len(scored) // 2)
    return random.choice(scored[:pool_size])


def next_episode_for_series(conn: sqlite3.Connection, series_id: int) -> sqlite3.Row | None:
    order = series_episode_order(conn, series_id)
    if not order:
        return None

    mode_row = conn.execute("SELECT rotation_mode FROM series WHERE id = ?", (series_id,)).fetchone()
    if mode_row is not None and mode_row["rotation_mode"] == "random":
        return _next_random_episode(conn, order)

    last_id = last_aired_episode_id(conn, series_id)
    return _next_sequential_episode(order, last_id)


def _series_allowed(series_id: int, recent_series_window: list[int], max_consecutive: int) -> bool:
    if max_consecutive <= 0 or len(recent_series_window) < max_consecutive:
        return True
    tail = recent_series_window[-max_consecutive:]
    return not (len(set(tail)) == 1 and tail[0] == series_id)


def pick_next_series(
    conn: sqlite3.Connection,
    eligible_series_ids: list[int],
    recent_series_window: list[int],
    max_consecutive: int,
) -> int | None:
    allowed = [s for s in eligible_series_ids if _series_allowed(s, recent_series_window, max_consecutive)]
    pool = allowed or eligible_series_ids  # relax the rule rather than deadlock if everything's excluded
    if not pool:
        return None
    return min(pool, key=lambda sid: (last_aired_time(conn, sid), sid))


def pick_next_episode(
    conn: sqlite3.Connection,
    eligible_series_ids: list[int],
    max_duration_seconds: float,
    recent_series_window: list[int],
    max_consecutive: int,
) -> sqlite3.Row | None:
    """Round-robins across eligible series (oldest-last-aired first) and returns
    the first candidate whose next episode fits max_duration_seconds. Series
    whose next episode doesn't fit, or that have no watchable episodes at
    all, are skipped in favor of the next one in priority order."""
    tried: set[int] = set()
    while len(tried) < len(eligible_series_ids):
        remaining_pool = [s for s in eligible_series_ids if s not in tried]
        series_id = pick_next_series(conn, remaining_pool, recent_series_window, max_consecutive)
        if series_id is None:
            return None
        tried.add(series_id)
        episode = next_episode_for_series(conn, series_id)
        if episode is not None and episode["duration_seconds"] <= max_duration_seconds:
            return episode
    return None
