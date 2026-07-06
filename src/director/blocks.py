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

from dataclasses import dataclass, replace
from datetime import date, time

OFF_AIR_START = time(5, 0)
OFF_AIR_END = time(10, 0)

# Adult animation (Futurama et al.) is barred from the regular schedule and airs
# only in the curated Adult Swim night block on Fri/Sat/Sun (see OVERLAYS).
ADULT_ANIMATION = "adult-animation"
_NO_ADULT = [ADULT_ANIMATION]


@dataclass(frozen=True)
class BlockTemplate:
    name: str
    start: time  # MSK wall-clock
    end: time  # MSK wall-clock; if <= start, it's interpreted as the next day (e.g. night block 23:00-05:00)
    series_filter: list[str] | None = None  # None = any series in the catalog (whitelist by name)
    ad_break_every_minutes: int = 25
    ad_break_duration_seconds: int = 150
    max_consecutive_same_series: int = 1
    category_filter: list[str] | None = None  # None = any category; else whitelist (e.g. Adult Swim = adult-animation)
    category_exclude: list[str] | None = None  # categories barred from this block (e.g. adult-animation in daytime)
    content: str = "series"  # 'series' = pack episodes; 'film' = a film tentpole first, then episodes


def block_allows_series(block: BlockTemplate, name: str, category: str) -> bool:
    if block.series_filter is not None and name not in block.series_filter:
        return False
    if block.category_filter is not None and category not in block.category_filter:
        return False
    if block.category_exclude is not None and category in block.category_exclude:
        return False
    return True


DEFAULT_BLOCKS: list[BlockTemplate] = [
    BlockTemplate("утро", time(10, 0), time(13, 0), category_exclude=_NO_ADULT),
    BlockTemplate("день", time(13, 0), time(18, 0), category_exclude=_NO_ADULT),
    BlockTemplate("вечер", time(18, 0), time(23, 0), ad_break_every_minutes=20, category_exclude=_NO_ADULT),
    BlockTemplate("ночь", time(23, 0), time(5, 0), ad_break_every_minutes=40, max_consecutive_same_series=2, category_exclude=_NO_ADULT),
]


# --- Overlays: compose the day from time-of-day slices --------------------
#
# The broadcast day is linearized to "minutes since 10:00" (0..1140, where
# 05:00 next day = 1140). This makes the past-midnight night block a plain
# contiguous range, so overlays that replace a time slice can be spliced
# without any wrap-around special-casing - and several overlays on different
# ranges compose (weekend marathon in the daytime AND Adult Swim at night on
# the same Saturday), unlike the old "first matching event replaces the whole
# day" scheme.

_DAY_START_MIN = 10 * 60  # 10:00 MSK
BROADCAST_DAY_MINUTES = 24 * 60 - _DAY_START_MIN + 5 * 60  # 1140: 10:00 -> 05:00 next day


def _to_bmin(t: time) -> int:
    total = t.hour * 60 + t.minute
    return total - _DAY_START_MIN if total >= _DAY_START_MIN else total + (24 * 60 - _DAY_START_MIN)


def _from_bmin(m: int) -> time:
    total = (m + _DAY_START_MIN) % (24 * 60)
    return time(total // 60, total % 60)


@dataclass(frozen=True)
class Overlay:
    """Replaces the [start, end) slice of the day with its own blocks, leaving
    the rest of the base schedule intact."""
    name: str
    start: time
    end: time
    blocks: list[BlockTemplate]
    day_of_week: set[int] | None = None  # date.weekday(): 0=Mon..6=Sun; None = every day
    applies: callable = None  # optional date -> bool, checked in addition to day_of_week


# Overlay blocks must tile their own [start, end) window. Add holidays,
# premiere weeks, etc. here as further overlays.
OVERLAYS: list[Overlay] = [
    Overlay(
        name="выходной марафон",
        start=time(10, 0),
        end=time(18, 0),
        day_of_week={5, 6},  # Saturday, Sunday
        blocks=[BlockTemplate("марафон", time(10, 0), time(18, 0), ad_break_every_minutes=30, category_exclude=_NO_ADULT)],
    ),
    Overlay(
        name="вечерний фильм",
        start=time(21, 0),
        end=time(23, 0),
        day_of_week={5, 6},  # weekend prime-time film tentpole
        blocks=[
            BlockTemplate(
                "вечерний фильм", time(21, 0), time(23, 0),
                ad_break_every_minutes=30, category_exclude=_NO_ADULT, content="film",
            )
        ],
    ),
    Overlay(
        name="Adult Swim",
        start=time(23, 0),
        end=time(2, 0),
        day_of_week={4, 5, 6},  # Friday, Saturday, Sunday
        blocks=[
            BlockTemplate(
                "Adult Swim", time(23, 0), time(2, 0),
                ad_break_every_minutes=30, max_consecutive_same_series=3,
                category_filter=[ADULT_ANIMATION],
            )
        ],
    ),
]


def _apply_overlay(base: list[BlockTemplate], overlay: Overlay) -> list[BlockTemplate]:
    lo, hi = _to_bmin(overlay.start), _to_bmin(overlay.end)
    result: list[BlockTemplate] = []
    for block in base:
        bs, be = _to_bmin(block.start), _to_bmin(block.end)
        if be <= lo or bs >= hi:
            result.append(block)  # fully outside the overlay window
            continue
        if bs < lo:  # keep the slice before the window
            result.append(replace(block, end=_from_bmin(lo)))
        if be > hi:  # keep the slice after the window
            result.append(replace(block, start=_from_bmin(hi)))
        # the [lo, hi) portion is dropped - overlay.blocks fill it
    result.extend(overlay.blocks)
    result.sort(key=lambda b: _to_bmin(b.start))
    return result


def blocks_for_date(broadcast_date: date) -> tuple[list[BlockTemplate], str | None]:
    """Returns the composed block sequence for a broadcast day and a name for
    any overlays that applied (joined with ' + ' if several)."""
    dow = broadcast_date.weekday()
    blocks = list(DEFAULT_BLOCKS)
    applied: list[str] = []
    for overlay in OVERLAYS:
        day_ok = overlay.day_of_week is None or dow in overlay.day_of_week
        extra_ok = overlay.applies is None or overlay.applies(broadcast_date)
        if day_ok and extra_ok:
            blocks = _apply_overlay(blocks, overlay)
            applied.append(overlay.name)
    return blocks, (" + ".join(applied) or None)
