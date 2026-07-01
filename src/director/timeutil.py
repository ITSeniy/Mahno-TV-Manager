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
