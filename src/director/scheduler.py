"""Generates the program log ("traffic") for one or more broadcast days.

A broadcast day starts at 10:00 MSK and runs through 05:00 MSK the next day,
followed by the off-air window 05:00-10:00 MSK. Each block's end time is a
hard stop: an episode is only scheduled if it fits before the block ends, so
the final content block (whichever one covers up to 05:00) can never run
into the off-air window. Anything short of a full episode remaining in a
block is padded with ads/bumpers rather than left as dead air; leftover time
between the last block and 05:00 is padded the same way.

Block start times drift forward (never backward) if an earlier block runs
long - see PROJECT_PLAN.md risk #4 for why exact alignment isn't attempted
here; the playout controller (Phase 3) is where real wall-clock drift
correction belongs.
"""

import random
import sqlite3
from datetime import date, datetime, timedelta

from director.ad_pods import AD_CAP_SECONDS_PER_HOUR, ad_seconds_in_trailing_hour, build_ad_pod, build_filler, pick_bumper
from director.blocks import OFF_AIR_END, OFF_AIR_START, BlockTemplate, blocks_for_date
from director.rotation import pick_next_episode
from director.timeutil import combine_msk

MIN_SEGMENT_SECONDS = 30  # below this, don't bother trying to schedule anything more in a block

# REN TV's early-2000s look occasionally ran two "we'll be right back" bumpers
# back to back instead of one - the traffic manager can lean on that quirk.
DOUBLE_AD_IN_PROBABILITY = 0.25


def _write_log(
    conn: sqlite3.Connection,
    start_time: datetime,
    item_type: str,
    item_row: sqlite3.Row | None,
    block_name: str | None,
    event_name: str | None,
    end_time: datetime | None = None,
) -> datetime:
    if item_type == "off_air":
        item_id = None
        assert end_time is not None
    else:
        item_id = item_row["id"]
        end_time = start_time + timedelta(seconds=item_row["duration_seconds"])

    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, block_name, event_name, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'scheduled')",
        (start_time.isoformat(), end_time.isoformat(), item_type, item_id, block_name, event_name),
    )
    return end_time


def _insert_ad_break(
    conn: sqlite3.Connection,
    current_time: datetime,
    block_end: datetime,
    block: BlockTemplate,
    event_name: str | None,
) -> tuple[datetime, bool]:
    """ad_in (sometimes twice) -> ad pod -> ad_out. Returns the possibly-
    unchanged current_time and whether a break was actually inserted - it's
    skipped if the rolling 7-min/hour budget has no room left, in which case
    the caller should keep the block's "due for a break" state so it retries
    on the next slot rather than waiting a full cadence period again."""
    remaining_after = (block_end - current_time).total_seconds()
    if remaining_after <= MIN_SEGMENT_SECONDS:
        return current_time, False

    budget = AD_CAP_SECONDS_PER_HOUR - ad_seconds_in_trailing_hour(conn, current_time)
    if budget <= MIN_SEGMENT_SECONDS:
        return current_time, False

    pod_target = min(block.ad_break_duration_seconds, remaining_after, budget)

    ad_in_count = 2 if random.random() < DOUBLE_AD_IN_PROBABILITY else 1
    for _ in range(ad_in_count):
        remaining_now = (block_end - current_time).total_seconds()
        ad_in = pick_bumper(conn, kind="ad_in", max_duration=remaining_now)
        if ad_in is None:
            break
        current_time = _write_log(conn, current_time, "bumper", ad_in, block.name, event_name)

    for ad in build_ad_pod(conn, pod_target, current_time):
        current_time = _write_log(conn, current_time, "ad", ad, block.name, event_name)

    remaining_after_ads = max(0.0, (block_end - current_time).total_seconds())
    ad_out = pick_bumper(conn, kind="ad_out", max_duration=remaining_after_ads)
    if ad_out is not None:
        current_time = _write_log(conn, current_time, "bumper", ad_out, block.name, event_name)

    return current_time, True


def _fill_block(
    conn: sqlite3.Connection,
    block: BlockTemplate,
    current_time: datetime,
    block_end: datetime,
    eligible_series_ids: list[int],
    event_name: str | None,
) -> datetime:
    recent_series_window: list[int] = []
    last_ad_break = current_time

    while True:
        remaining = (block_end - current_time).total_seconds()
        if remaining <= MIN_SEGMENT_SECONDS:
            break

        episode = pick_next_episode(conn, eligible_series_ids, remaining, recent_series_window, block.max_consecutive_same_series)
        if episode is None:
            filler = build_filler(conn, remaining, current_time)
            for kind, item in filler:
                current_time = _write_log(conn, current_time, kind, item, block.name, event_name)
            break

        current_time = _write_log(conn, current_time, "episode", episode, block.name, event_name)
        recent_series_window.append(episode["series_id"])

        did_break = False
        elapsed_since_break = (current_time - last_ad_break).total_seconds()
        if elapsed_since_break >= block.ad_break_every_minutes * 60:
            current_time, did_break = _insert_ad_break(conn, current_time, block_end, block, event_name)
            if did_break:
                last_ad_break = current_time

        if not did_break:
            # Generic "you're watching X" bumper between programs, independent
            # of ad breaks - what REN TV's era called a "bezrazmerka".
            remaining_for_bumper = (block_end - current_time).total_seconds()
            if remaining_for_bumper > MIN_SEGMENT_SECONDS:
                interstitial = pick_bumper(conn, kind="interstitial", max_duration=remaining_for_bumper)
                if interstitial is not None:
                    current_time = _write_log(conn, current_time, "bumper", interstitial, block.name, event_name)

    return current_time


def generate_day(conn: sqlite3.Connection, broadcast_date: date) -> int:
    blocks, event_name = blocks_for_date(broadcast_date)

    all_series = conn.execute("SELECT id, name FROM series").fetchall()
    if not all_series:
        raise RuntimeError("No series in the catalog - run the library scanner first")
    series_ids = [row["id"] for row in all_series]
    series_names = {row["id"]: row["name"] for row in all_series}

    rows_before = conn.execute("SELECT COUNT(*) AS c FROM program_log").fetchone()["c"]

    current_time = combine_msk(broadcast_date, OFF_AIR_END)

    for block in blocks:
        end_date = broadcast_date if block.end > block.start else broadcast_date + timedelta(days=1)
        block_end = combine_msk(end_date, block.end)
        if block_end <= current_time:
            continue  # earlier blocks already drifted past this one's window entirely

        eligible = [sid for sid in series_ids if block.series_filter is None or series_names[sid] in block.series_filter]
        current_time = _fill_block(conn, block, current_time, block_end, eligible, event_name)

    off_air_start_nominal = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_START)

    while current_time < off_air_start_nominal:
        remaining = (off_air_start_nominal - current_time).total_seconds()
        if remaining <= MIN_SEGMENT_SECONDS:
            break
        filler = build_filler(conn, remaining, current_time)
        if not filler:
            break  # out of ad/bumper content to pad with; go off-air a bit early rather than loop forever
        for kind, item in filler:
            current_time = _write_log(conn, current_time, kind, item, "техперерыв (докладка)", event_name)

    off_air_end = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_END)
    _write_log(conn, current_time, "off_air", None, "техперерыв", None, end_time=off_air_end)

    conn.commit()
    rows_after = conn.execute("SELECT COUNT(*) AS c FROM program_log").fetchone()["c"]
    return rows_after - rows_before


def generate_schedule(conn: sqlite3.Connection, start_date: date, days: int) -> dict[date, int]:
    results: dict[date, int] = {}
    for i in range(days):
        broadcast_date = start_date + timedelta(days=i)
        day_start = combine_msk(broadcast_date, OFF_AIR_END).isoformat()
        day_end = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_END).isoformat()
        already = conn.execute(
            "SELECT COUNT(*) AS c FROM program_log WHERE start_time >= ? AND start_time < ?",
            (day_start, day_end),
        ).fetchone()["c"]
        if already > 0:
            results[broadcast_date] = 0
            continue
        results[broadcast_date] = generate_day(conn, broadcast_date)
    return results
