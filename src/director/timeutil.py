"""MSK <-> UTC conversions.

Russia has not observed DST since 2014, so MSK is a fixed UTC+3 offset -
no timezone database needed for this.
"""

from datetime import date, datetime, time, timedelta, timezone

MSK_OFFSET = timedelta(hours=3)


def msk_to_utc(dt_msk_naive: datetime) -> datetime:
    return (dt_msk_naive - MSK_OFFSET).replace(tzinfo=timezone.utc)


def utc_to_msk(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return (dt_utc + MSK_OFFSET).replace(tzinfo=None)


def combine_msk(day: date, wall_clock: time) -> datetime:
    """MSK wall-clock time on a given date, returned as UTC."""
    return msk_to_utc(datetime.combine(day, wall_clock))


ANCHOR_MINUTES = 15  # the schedule aligns programs to :00/:15/:30/:45 MSK


def _quarter_floor_msk(dt_msk_naive: datetime) -> datetime:
    return dt_msk_naive.replace(
        minute=(dt_msk_naive.minute // ANCHOR_MINUTES) * ANCHOR_MINUTES, second=0, microsecond=0
    )


def next_quarter_msk(dt_utc: datetime) -> datetime:
    """The nearest :00/:15/:30/:45 MSK wall-clock boundary strictly after
    dt_utc, returned as UTC. Used to bound how far a slot may pack before it
    should round off to an anchor."""
    floor = _quarter_floor_msk(utc_to_msk(dt_utc))
    return msk_to_utc(floor + timedelta(minutes=ANCHOR_MINUTES))


def ceil_quarter_msk(dt_utc: datetime) -> datetime:
    """The nearest :00/:15/:30/:45 MSK wall-clock boundary at or after dt_utc,
    returned as UTC. This is the pad target: if content already ends exactly on
    an anchor the gap is zero and the next program starts right there."""
    msk = utc_to_msk(dt_utc)
    floor = _quarter_floor_msk(msk)
    if floor == msk:
        return msk_to_utc(floor)
    return msk_to_utc(floor + timedelta(minutes=ANCHOR_MINUTES))
