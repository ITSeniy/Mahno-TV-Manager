"""Continuity cards - the generated connective tissue between programs.

Unlike episodes/ads/bumpers (scanned from disk), a card is produced by the
director itself: the scheduler reserves a slot with a kind and an exact
`target_seconds` (the "rubber" that pads a block up to a quarter-hour anchor),
and the profilaktika render job (see card_render.py / render_cards.py, added in
a later step) fills `rendered_path`. Reserved cards are played through the same
program_player as any pre-rendered file.

This module owns the kind vocabulary and the reservation call; content
generation and rendering live in card_content.py / card_render.py.
"""

import sqlite3
from datetime import datetime, timedelta

KIND_EPG_DAY = "epg_day"    # detailed program guide for the whole broadcast day (sign-on)
KIND_EPG_NEXT = "epg_next"  # brief "Далее" - the next few programs
KIND_WEATHER = "weather"    # forecast plate
KIND_CLOCK = "clock"        # time/ident plate; also the universal filler for tiny gaps

ALL_KINDS = (KIND_EPG_DAY, KIND_EPG_NEXT, KIND_WEATHER, KIND_CLOCK)


def reserve_card(
    conn: sqlite3.Connection,
    kind: str,
    slot_start: datetime,
    target_seconds: float,
    msk_date: str,
    spec_json: str | None = None,
) -> int:
    """Inserts a pending card row and returns its id. The scheduler pairs this
    with a program_log row of item_type 'card'; the render job later fills in
    rendered_path/duration_seconds/status."""
    cur = conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, spec_json, status) "
        "VALUES (?, ?, ?, ?, ?, 'pending')",
        (kind, msk_date, slot_start.isoformat(), target_seconds, spec_json),
    )
    return cur.lastrowid


def end_time(slot_start: datetime, target_seconds: float) -> datetime:
    return slot_start + timedelta(seconds=target_seconds)
