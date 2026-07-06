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

from director import cards
from director.ad_pods import AD_CAP_SECONDS_PER_HOUR, ad_seconds_in_trailing_hour, build_ad_pod, build_filler, pick_bumper
from director.blocks import OFF_AIR_END, OFF_AIR_START, BlockTemplate, blocks_for_date
from director.rotation import pick_next_episode
from director.timeutil import ceil_quarter_msk, combine_msk, next_quarter_msk, utc_to_msk

MIN_SEGMENT_SECONDS = 30  # below this, don't bother trying to schedule anything more in a block

# REN TV's early-2000s look occasionally ran two "we'll be right back" bumpers
# back to back instead of one - the traffic manager can lean on that quirk.
DOUBLE_AD_IN_PROBABILITY = 0.25

# Continuity-card padding: the tail of every slot is filled up to the next
# quarter-hour anchor with generated cards of exactly the remaining length.
CARD_MAX_SECONDS = 120.0   # keep any single static plate reasonably short; split longer gaps across cards
CLOCK_MAX_SECONDS = 30.0   # gaps this small just get a clock/ident plate
SIGN_ON_LABEL = "начало эфира"  # block_name for the morning sign-on slate (guide + weather)


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


def _reserve_card(
    conn: sqlite3.Connection,
    start_time: datetime,
    seconds: float,
    block_name: str,
    event_name: str | None,
    msk_date: str,
    kind: str,
) -> datetime:
    card_id = cards.reserve_card(conn, kind, start_time, seconds, msk_date)
    return _write_log(conn, start_time, "card", {"id": card_id, "duration_seconds": seconds}, block_name, event_name)


def _fill_gap_with_cards(
    conn: sqlite3.Connection,
    current_time: datetime,
    target: datetime,
    block_name: str,
    event_name: str | None,
    msk_date: str,
    lead_kinds: tuple[str, ...] = (),
) -> datetime:
    """Fills [current_time, target) exactly with one or more continuity cards,
    each at most CARD_MAX_SECONDS. Because we render these cards ourselves we
    can size the last one to the exact remaining seconds, so the timeline stays
    gap-free while landing precisely on the anchor. `lead_kinds` are emitted
    first (e.g. the detailed guide + weather at sign-on); the rest are chosen by
    gap size and time of day."""
    lead = list(lead_kinds)
    is_morning = utc_to_msk(current_time).hour < 13
    index = 0
    while True:
        gap = (target - current_time).total_seconds()
        if gap <= 0.001:
            break
        chunk = min(gap, CARD_MAX_SECONDS)
        if gap - chunk < 1.0:  # don't strand a sub-second sliver that can't be its own card
            chunk = gap
        if lead:
            kind = lead.pop(0)
        elif chunk <= CLOCK_MAX_SECONDS:
            kind = cards.KIND_CLOCK
        elif is_morning and index % 3 == 0:
            kind = cards.KIND_WEATHER
        else:
            kind = cards.KIND_EPG_NEXT
        current_time = _reserve_card(conn, current_time, chunk, block_name, event_name, msk_date, kind)
        index += 1
    return current_time


def _fill_block(
    conn: sqlite3.Connection,
    block: BlockTemplate,
    current_time: datetime,
    block_end: datetime,
    eligible_series_ids: list[int],
    event_name: str | None,
    day_start_iso: str,
    msk_date: str,
) -> datetime:
    recent_series_window: list[int] = []
    last_ad_break = current_time

    # Align to a quarter anchor if we arrived mid-quarter (only happens right
    # after the day's sign-on slate). Every slot below already lands on one.
    anchor = min(ceil_quarter_msk(current_time), block_end)
    if (anchor - current_time).total_seconds() > MIN_SEGMENT_SECONDS:
        current_time = _fill_gap_with_cards(conn, current_time, anchor, block.name, event_name, msk_date)

    while True:
        remaining = (block_end - current_time).total_seconds()
        if remaining <= MIN_SEGMENT_SECONDS:
            break

        # Pack programs into this anchor slot: the first may run long (a program
        # can span anchors), each subsequent one only if it still fits before
        # the next anchor - that's what lets several short cartoons (Смешарики
        # ~6:30) share one slot instead of each demanding its own.
        placed = 0
        while True:
            if placed == 0:
                room = (block_end - current_time).total_seconds()
            else:
                room = (min(next_quarter_msk(current_time), block_end) - current_time).total_seconds()
            if room <= MIN_SEGMENT_SECONDS:
                break
            episode = pick_next_episode(
                conn, eligible_series_ids, room, recent_series_window, block.max_consecutive_same_series, day_start_iso
            )
            if episode is None:
                break
            current_time = _write_log(conn, current_time, "episode", episode, block.name, event_name)
            recent_series_window.append(episode["series_id"])
            placed += 1

        if placed == 0:
            # Nothing fits at all (or every premiere series has hit today's cap
            # and nothing random is due) - fall back to the ad/interstitial
            # filler for the rest of the block rather than leave dead air.
            filler = build_filler(conn, (block_end - current_time).total_seconds(), current_time)
            for kind, item in filler:
                current_time = _write_log(conn, current_time, kind, item, block.name, event_name)
            break

        # Pad the slot tail up to the next quarter anchor. A large gap first
        # spends an ad break (when the rolling cadence is due), then continuity
        # cards fill the exact remainder so the next program starts on the anchor.
        anchor = min(ceil_quarter_msk(current_time), block_end)
        gap = (anchor - current_time).total_seconds()
        if gap <= 0:
            continue  # content landed exactly on an anchor
        if gap > CLOCK_MAX_SECONDS and (current_time - last_ad_break).total_seconds() >= block.ad_break_every_minutes * 60:
            current_time, did_break = _insert_ad_break(conn, current_time, anchor, block, event_name)
            if did_break:
                last_ad_break = current_time
        if (anchor - current_time).total_seconds() > 0:
            current_time = _fill_gap_with_cards(conn, current_time, anchor, block.name, event_name, msk_date)

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
    day_start_iso = current_time.isoformat()
    msk_date = broadcast_date.isoformat()

    # Sign-on slate: the detailed program guide for the day + weather, filling
    # 10:00 up to the first program anchor (as a real channel opened its day).
    first_anchor = next_quarter_msk(current_time)
    current_time = _fill_gap_with_cards(
        conn, current_time, first_anchor, SIGN_ON_LABEL, event_name, msk_date,
        lead_kinds=(cards.KIND_EPG_DAY, cards.KIND_WEATHER),
    )

    for block in blocks:
        end_date = broadcast_date if block.end > block.start else broadcast_date + timedelta(days=1)
        block_end = combine_msk(end_date, block.end)
        if block_end <= current_time:
            continue  # earlier blocks already drifted past this one's window entirely

        eligible = [sid for sid in series_ids if block.series_filter is None or series_names[sid] in block.series_filter]
        current_time = _fill_block(conn, block, current_time, block_end, eligible, event_name, day_start_iso, msk_date)

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
