"""Builds ad breaks ("pods") and picks bumpers to wrap them.

Ads are chosen least-used-first over a lookback window so the same
commercial doesn't hammer every break, then greedily packed to fill as much
of the target duration as possible without exceeding it.
"""

import sqlite3
from datetime import datetime, timedelta

USAGE_LOOKBACK_HOURS = 24


def least_used_ads(conn: sqlite3.Connection, now_utc: datetime) -> list[sqlite3.Row]:
    cutoff = (now_utc - timedelta(hours=USAGE_LOOKBACK_HOURS)).isoformat()
    return conn.execute(
        """
        SELECT a.*, COALESCE(u.cnt, 0) AS recent_uses
        FROM ads a
        LEFT JOIN (
            SELECT item_id, COUNT(*) AS cnt FROM program_log
            WHERE item_type = 'ad' AND start_time >= ?
            GROUP BY item_id
        ) u ON u.item_id = a.id
        WHERE a.missing = 0 AND a.duration_seconds IS NOT NULL
        ORDER BY recent_uses ASC, RANDOM()
        """,
        (cutoff,),
    ).fetchall()


def build_ad_pod(conn: sqlite3.Connection, target_seconds: float, now_utc: datetime) -> list[sqlite3.Row]:
    pool = list(least_used_ads(conn, now_utc))
    pod: list[sqlite3.Row] = []
    total = 0.0
    while pool:
        fit = next((a for a in pool if total + a["duration_seconds"] <= target_seconds), None)
        if fit is None:
            break
        pod.append(fit)
        total += fit["duration_seconds"]
        pool.remove(fit)
    return pod


def pick_bumper(conn: sqlite3.Connection, kind: str | None = None, max_duration: float | None = None) -> sqlite3.Row | None:
    query = "SELECT * FROM bumpers WHERE missing = 0 AND duration_seconds IS NOT NULL"
    params: list = []
    if kind is not None:
        query += " AND kind = ?"
        params.append(kind)
    if max_duration is not None:
        query += " AND duration_seconds <= ?"
        params.append(max_duration)
    query += " ORDER BY RANDOM() LIMIT 1"
    return conn.execute(query, params).fetchone()


def build_filler(conn: sqlite3.Connection, remaining_seconds: float, now_utc: datetime) -> list[tuple[str, sqlite3.Row]]:
    """Pads a gap too small for another episode with ads, falling back to a bumper."""
    pod = build_ad_pod(conn, remaining_seconds, now_utc)
    if pod:
        return [("ad", a) for a in pod]
    bumper = pick_bumper(conn, max_duration=remaining_seconds)
    if bumper:
        return [("bumper", bumper)]
    return []
