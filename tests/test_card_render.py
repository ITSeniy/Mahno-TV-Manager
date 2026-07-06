from datetime import datetime, timedelta, timezone

from director import cards, db
from director.card_render import _split_weather, card_html_pages, is_card_render_valid

T0 = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)  # 10:00 MSK


def make_db(tmp_path):
    return db.connect(tmp_path / "lib.db")


def _reserve(conn, kind, slot_start=T0, target=60):
    cid = cards.reserve_card(conn, kind, slot_start, target, "2026-07-06")
    conn.commit()
    return conn.execute("SELECT * FROM cards WHERE id = ?", (cid,)).fetchone()


def _add_prog(conn, name, title="T"):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))
    sid = conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, 1, 1, ?, ?, 600, datetime('now'))",
        (sid, title, f"/{name}/e"),
    )
    eid = conn.execute("SELECT id FROM episodes WHERE file_path = ?", (f"/{name}/e",)).fetchone()["id"]
    return eid


def _log(conn, start, minutes, item_type, item_id):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) VALUES (?, ?, ?, ?, 'scheduled')",
        (start.isoformat(), (start + timedelta(minutes=minutes)).isoformat(), item_type, item_id),
    )
    conn.commit()


def test_split_weather_separates_city_from_reading():
    assert _split_weather("МОСКВА +19 ЯСНО") == ("МОСКВА", "+19 ЯСНО")
    assert _split_weather("САНКТ-ПЕТЕРБУРГ -5 СНЕГ") == ("САНКТ-ПЕТЕРБУРГ", "-5 СНЕГ")


def test_epg_day_pages_produce_one_html_per_page(tmp_path):
    conn = make_db(tmp_path)
    for i in range(10):
        e = _add_prog(conn, f"Show{i}", title=f"Ep{i}")
        _log(conn, T0 + timedelta(minutes=30 * i), 20, "episode", e)

    card = _reserve(conn, cards.KIND_EPG_DAY, target=120)
    htmls = card_html_pages(conn, card, weather_lines=[])
    assert len(htmls) == 2
    assert "ПРОГРАММА ПЕРЕДАЧ" in htmls[0] and "Show0" in htmls[0]


def test_weather_card_html_uses_supplied_lines(tmp_path):
    conn = make_db(tmp_path)
    card = _reserve(conn, cards.KIND_WEATHER)
    (html,) = card_html_pages(conn, card, weather_lines=["МОСКВА +19 ЯСНО"])
    assert "ПОГОДА" in html and "МОСКВА" in html and "+19 ЯСНО" in html


def test_clock_card_html_shows_the_slot_time(tmp_path):
    conn = make_db(tmp_path)
    card = _reserve(conn, cards.KIND_CLOCK, target=8)
    (html,) = card_html_pages(conn, card, weather_lines=[])
    assert "10:00" in html and "МОСКОВСКОЕ ВРЕМЯ" in html


def test_is_card_render_valid(tmp_path):
    conn = make_db(tmp_path)
    rendered = tmp_path / "c.mp4"
    rendered.write_bytes(b"x")

    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, rendered_path, status) "
        "VALUES ('weather', '2026-07-06', ?, 60, ?, 'rendered')",
        (T0.isoformat(), str(rendered)),
    )
    good = conn.execute("SELECT * FROM cards ORDER BY id DESC LIMIT 1").fetchone()
    assert is_card_render_valid(good)

    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, rendered_path, status) "
        "VALUES ('weather', '2026-07-06', ?, 60, ?, 'rendered')",
        (T0.isoformat(), str(tmp_path / "missing.mp4")),
    )
    gone = conn.execute("SELECT * FROM cards ORDER BY id DESC LIMIT 1").fetchone()
    assert not is_card_render_valid(gone)

    pending = _reserve(conn, cards.KIND_CLOCK)
    assert not is_card_render_valid(pending)
