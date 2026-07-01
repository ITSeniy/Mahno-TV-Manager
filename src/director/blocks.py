"""Named time-of-day programming blocks and event overrides.

A broadcast day runs 10:00 MSK -> 05:00 MSK the next day (19h of blocks),
followed by the off-air window 05:00-10:00 MSK. Block templates for a given
day must together cover the full 10:00->05:00 span - the scheduler treats
each block's end as a hard stop (nothing is scheduled that would run past
it), so gaps in coverage just become dead time filled by ad/bumper padding.

This module intentionally keeps templates in code rather than the DB: they
change rarely and reviewing them as a diff beats building admin UI for it
this early. Revisit if/when a web dashboard (Phase 7) needs to edit them
live.
"""

from dataclasses import dataclass
from datetime import date, time

OFF_AIR_START = time(5, 0)
OFF_AIR_END = time(10, 0)


@dataclass(frozen=True)
class BlockTemplate:
    name: str
    start: time  # MSK wall-clock
    end: time  # MSK wall-clock; if <= start, it's interpreted as the next day (e.g. night block 23:00-05:00)
    series_filter: list[str] | None = None  # None = any series in the catalog
    ad_break_every_minutes: int = 25
    ad_break_duration_seconds: int = 150
    max_consecutive_same_series: int = 1


DEFAULT_BLOCKS: list[BlockTemplate] = [
    BlockTemplate("утро", time(10, 0), time(13, 0)),
    BlockTemplate("день", time(13, 0), time(18, 0)),
    BlockTemplate("вечер", time(18, 0), time(23, 0), ad_break_every_minutes=20),
    BlockTemplate("ночь", time(23, 0), time(5, 0), ad_break_every_minutes=40, max_consecutive_same_series=2),
]


@dataclass(frozen=True)
class EventOverride:
    name: str
    blocks: list[BlockTemplate]
    day_of_week: set[int] | None = None  # date.weekday(): 0=Mon .. 6=Sun; None = every day
    applies: callable = None  # optional date -> bool, checked in addition to day_of_week


# Example event demonstrating the override mechanism: weekend marathon block
# instead of the usual утро/день split. Add more entries here for holidays,
# premiere weeks, etc.
EVENTS: list[EventOverride] = [
    EventOverride(
        name="выходной марафон",
        day_of_week={5, 6},  # Saturday, Sunday
        blocks=[
            BlockTemplate("марафон", time(10, 0), time(18, 0), ad_break_every_minutes=30),
            BlockTemplate("вечер", time(18, 0), time(23, 0), ad_break_every_minutes=20),
            BlockTemplate("ночь", time(23, 0), time(5, 0), ad_break_every_minutes=40, max_consecutive_same_series=2),
        ],
    ),
]


def blocks_for_date(broadcast_date: date) -> tuple[list[BlockTemplate], str | None]:
    """Returns the block sequence for a broadcast day and the event name, if any."""
    dow = broadcast_date.weekday()
    for event in EVENTS:
        day_ok = event.day_of_week is None or dow in event.day_of_week
        extra_ok = event.applies is None or event.applies(broadcast_date)
        if day_ok and extra_ok:
            return event.blocks, event.name
    return DEFAULT_BLOCKS, None
