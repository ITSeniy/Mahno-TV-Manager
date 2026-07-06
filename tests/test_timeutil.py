from datetime import datetime, timezone

from director.timeutil import ceil_quarter_msk, combine_msk, next_quarter_msk, utc_to_msk


def _msk_hm(dt_utc):
    msk = utc_to_msk(dt_utc)
    return (msk.hour, msk.minute, msk.second)


def test_next_quarter_is_strictly_after():
    # 10:00 MSK == 07:00 UTC
    base = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)
    assert _msk_hm(next_quarter_msk(base)) == (10, 15, 0)  # on an anchor -> the next one
    assert _msk_hm(next_quarter_msk(base.replace(minute=7))) == (10, 15, 0)
    assert _msk_hm(next_quarter_msk(base.replace(minute=22, second=30))) == (10, 30, 0)
    assert _msk_hm(next_quarter_msk(base.replace(minute=59, second=59))) == (11, 0, 0)


def test_ceil_quarter_is_at_or_after():
    base = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)  # 10:00 MSK exactly
    assert ceil_quarter_msk(base) == base  # already on an anchor -> unchanged
    assert _msk_hm(ceil_quarter_msk(base.replace(minute=1))) == (10, 15, 0)
    assert _msk_hm(ceil_quarter_msk(base.replace(minute=45))) == (10, 45, 0)
    assert _msk_hm(ceil_quarter_msk(base.replace(minute=46))) == (11, 0, 0)


def test_quarter_helpers_roll_over_midnight_and_stay_utc():
    # 04:52 MSK == 01:52 UTC; next quarter 05:00 MSK == 02:00 UTC
    dt = combine_msk(datetime(2026, 7, 6).date(), datetime(2026, 7, 6, 4, 52).time())
    nxt = next_quarter_msk(dt)
    assert nxt.tzinfo == timezone.utc
    assert _msk_hm(nxt) == (5, 0, 0)
