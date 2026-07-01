"""Builds ad breaks ("pods") and picks bumpers to wrap them.

Ads are chosen least-used-first over a lookback window so the same
commercial doesn't hammer every break, then greedily packed to fill as much
of the target duration as possible without exceeding it.
"""

import sqlite3
from datetime import datetime, timedelta

USAGE_LOOKBACK_HOURS = 24
AD_CAP_SECONDS_PER_HOUR = 7 * 60  # real-world constraint: no more than 7 minutes of ads per clock hour
MIN_FILLER_AD_SECONDS = 5  # not worth querying for an ad pod under a near-zero remaining budget


def ad_seconds_in_trailing_hour(conn: sqlite3.Connection, now_utc: datetime) -> float:
    """Sum of ad durations already logged in the 60 minutes before now_utc -
    used to cap how much more can be scheduled without breaking the 7
    min/hour rule. Looks at program_log directly so it accounts for
    whatever's already been generated in this pass or a previous one."""
    window_start = (now_utc - timedelta(hours=1)).isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM((julianday(end_time) - julianday(start_time)) * 86400), 0) AS total
        FROM program_log
        WHERE item_type = 'ad' AND start_time >= ? AND start_time < ?
        """,
        (window_start, now_utc.isoformat()),
    ).fetchone()
    return row["total"]


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
    """Pads a gap too small for another episode with ads, falling back to a
    bumper. Ad time is still capped at AD_CAP_SECONDS_PER_HOUR here - this is
    also what fills the run-up to the 05:00 off-air cutoff, and without a cap
    of its own that padding could otherwise blow well past the hourly limit
    that _insert_ad_break enforces for regular in-block breaks."""
    ad_budget = max(0.0, AD_CAP_SECONDS_PER_HOUR - ad_seconds_in_trailing_hour(conn, now_utc))
    pod = build_ad_pod(conn, min(remaining_seconds, ad_budget), now_utc) if ad_budget > MIN_FILLER_AD_SECONDS else []
    if pod:
        return [("ad", a) for a in pod]
    # ad_in/ad_out are meant to bookend an actual ad pod, not serve as generic
    # padding - picking one at random here would look like a broken "we'll be
    # right back" with no ads following. interstitial is the one built for this.
    bumper = pick_bumper(conn, kind="interstitial", max_duration=remaining_seconds)
    if bumper:
        return [("bumper", bumper)]
    return []
