from datetime import date, time

from director.blocks import (
    BROADCAST_DAY_MINUTES,
    DEFAULT_BLOCKS,
    BlockTemplate,
    Overlay,
    _apply_overlay,
    _from_bmin,
    _to_bmin,
    block_allows_series,
    blocks_for_date,
)


def _block(**kw):
    return BlockTemplate("b", time(10, 0), time(13, 0), **kw)


def test_no_filters_allows_anything():
    b = _block()
    assert block_allows_series(b, "Smeshariki", "cartoon")
    assert block_allows_series(b, "Futurama", "adult-animation")


def test_series_filter_is_a_name_whitelist():
    b = _block(series_filter=["Avatar"])
    assert block_allows_series(b, "Avatar", "cartoon")
    assert not block_allows_series(b, "Beavers", "cartoon")


def test_category_filter_is_a_category_whitelist():
    b = _block(category_filter=["adult-animation"])
    assert block_allows_series(b, "Futurama", "adult-animation")
    assert not block_allows_series(b, "Smeshariki", "cartoon")


def test_category_exclude_bars_a_category():
    b = _block(category_exclude=["adult-animation"])
    assert block_allows_series(b, "Smeshariki", "cartoon")
    assert not block_allows_series(b, "Futurama", "adult-animation")


def test_filters_combine_as_and():
    b = _block(series_filter=["Futurama", "Smeshariki"], category_exclude=["adult-animation"])
    # Futurama passes the name whitelist but is barred by the category exclude.
    assert not block_allows_series(b, "Futurama", "adult-animation")
    assert block_allows_series(b, "Smeshariki", "cartoon")


# --- overlay composition ---------------------------------------------------

def _spans(blocks):
    return sorted((_to_bmin(b.start), _to_bmin(b.end), b.name) for b in blocks)


def _assert_tiles_day(blocks):
    spans = _spans(blocks)
    assert spans[0][0] == 0
    assert spans[-1][1] == BROADCAST_DAY_MINUTES
    for (s0, e0, _), (s1, e1, _) in zip(spans, spans[1:]):
        assert e0 == s1, f"gap/overlap between {e0} and {s1}"


def test_bmin_key_values_and_roundtrip():
    assert _to_bmin(time(10, 0)) == 0
    assert _to_bmin(time(23, 0)) == 780
    assert _to_bmin(time(2, 0)) == 960
    assert _to_bmin(time(5, 0)) == BROADCAST_DAY_MINUTES  # 1140, end of the broadcast day
    for m in (0, 180, 780, 960, 1140):
        assert _to_bmin(_from_bmin(m)) == m


def test_default_blocks_tile_the_whole_day():
    _assert_tiles_day(DEFAULT_BLOCKS)


def test_weekday_uses_default_blocks():
    blocks, name = blocks_for_date(date(2026, 7, 6))  # Monday
    assert name is None  # routine dayparts, no event label
    assert [b.name for b in blocks] == [
        "утро", "день", "телемагазин", "день", "вечер", "вечерний сериал", "вечер",
        "ночь", "ночной сериал", "ночь", "музыкальный канал", "ночной чат",
    ]


def test_saturday_composes_marathon_film_and_adult_swim_and_still_tiles():
    # Saturday stacks three overlays on different ranges: daytime marathon,
    # a prime-time film slot, and the night Adult Swim block.
    blocks, name = blocks_for_date(date(2026, 7, 4))  # Saturday
    assert name == "выходной марафон + вечерний фильм + Adult Swim"
    assert [b.name for b in blocks] == [
        "марафон", "вечер", "вечерний сериал", "вечерний фильм", "Adult Swim",
        "ночь", "музыкальный канал", "ночной чат",
    ]
    _assert_tiles_day(blocks)


def test_two_overlays_on_different_ranges_compose():
    # A daytime overlay and a night overlay (crossing midnight) must coexist -
    # the old first-match-wins scheme could not express this.
    base = [
        BlockTemplate("день", time(10, 0), time(23, 0)),
        BlockTemplate("ночь", time(23, 0), time(5, 0)),
    ]
    day = Overlay("day-x", time(10, 0), time(13, 0), [BlockTemplate("day-x", time(10, 0), time(13, 0))])
    night = Overlay("Adult Swim", time(23, 0), time(2, 0), [BlockTemplate("Adult Swim", time(23, 0), time(2, 0))])
    composed = _apply_overlay(_apply_overlay(base, day), night)

    names = [b.name for b in sorted(composed, key=lambda b: _to_bmin(b.start))]
    assert names == ["day-x", "день", "Adult Swim", "ночь"]
    _assert_tiles_day(composed)
    night_block = next(b for b in composed if b.name == "ночь")
    assert night_block.start == time(2, 0)  # night block pushed to after Adult Swim


def test_weeknight_night_series_overlay_applies_without_an_event_label():
    blocks, name = blocks_for_date(date(2026, 7, 6))  # Monday
    assert name is None  # ночной сериал is a routine daypart (is_event=False), not an event
    night_series = next(b for b in blocks if b.name == "ночной сериал")
    assert night_series.category_filter == ["adult-drama"]
    _assert_tiles_day(blocks)


def test_weekend_gets_adult_swim_not_the_night_series():
    blocks, _ = blocks_for_date(date(2026, 7, 4))  # Saturday
    assert not any(b.name == "ночной сериал" for b in blocks)
    assert any(b.name == "Adult Swim" for b in blocks)


def test_both_adult_categories_are_barred_from_daytime():
    blocks, _ = blocks_for_date(date(2026, 7, 6))  # Monday
    day = next(b for b in blocks if b.name == "день")
    assert block_allows_series(day, "Смешарики", "cartoon")
    assert not block_allows_series(day, "Sopranos", "adult-drama")
    assert not block_allows_series(day, "Futurama", "adult-animation")


def test_slotted_categories_are_confined_to_their_own_blocks():
    blocks, _ = blocks_for_date(date(2026, 7, 6))  # Monday
    day = next(b for b in blocks if b.name == "день")
    evening_series = next(b for b in blocks if b.name == "вечерний сериал")
    # sitcom/teleshopping/music each have a dedicated slot -> barred from the general schedule
    assert not block_allows_series(day, "Friends", "sitcom")
    assert not block_allows_series(day, "Магазин", "teleshopping")
    assert block_allows_series(evening_series, "Friends", "sitcom")
    # cartoon/edutainment/auto have no dedicated slot -> stay general daytime programming
    assert block_allows_series(day, "Смешарики", "cartoon")
    assert block_allows_series(day, "Галилео", "edutainment")


def test_overlay_can_split_a_block_it_sits_inside():
    base = [BlockTemplate("ночь", time(23, 0), time(5, 0))]
    mid = Overlay("mid", time(1, 0), time(3, 0), [BlockTemplate("mid", time(1, 0), time(3, 0))])
    composed = _apply_overlay(base, mid)

    spans = _spans(composed)
    assert [name for _, _, name in spans] == ["ночь", "mid", "ночь"]  # night split around the inserted slice
    for (s0, e0, _), (s1, e1, _) in zip(spans, spans[1:]):
        assert e0 == s1  # the three pieces stay contiguous
