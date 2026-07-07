from datetime import date, datetime, timedelta, timezone

from director import card_content, db
from director.card_content import (
    WEATHER_FALLBACK,
    day_programmes,
    epg_day_pages,
    epg_next_items,
    get_current_weather,
    parse_weather,
    refresh_weather,
)

T0 = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)  # 10:00 MSK on the broadcast day


def make_db(tmp_path):
    return db.connect(tmp_path / "lib.db")


def _add_prog(conn, name, title="T"):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))
    sid = conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, 1, 1, ?, ?, 600, datetime('now'))",
        (sid, title, f"/{name}/e"),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path = ?", (f"/{name}/e",)).fetchone()["id"]


def _log(conn, start, minutes, item_type, item_id=None):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) VALUES (?, ?, ?, ?, 'scheduled')",
        (start.isoformat(), (start + timedelta(minutes=minutes)).isoformat(), item_type, item_id),
    )
    conn.commit()


def test_parse_weather_strips_numbering_and_blanks():
    raw = "1. МОСКВА +19 ЯСНО\n- САНКТ-ПЕТЕРБУРГ +15 ДОЖДЬ\n\n"
    assert parse_weather(raw) == ["МОСКВА +19 ЯСНО", "САНКТ-ПЕТЕРБУРГ +15 ДОЖДЬ"]


def test_refresh_weather_calls_gemini_once_per_msk_day_then_caches(monkeypatch, tmp_path):
    conn = make_db(tmp_path)
    calls = {"n": 0}

    def fake(keys, prompt):
        calls["n"] += 1
        return "МОСКВА +21 ЯСНО\nСОЧИ +27 СОЛНЕЧНО"

    monkeypatch.setattr(card_content.gemini_client, "generate_text", fake)

    first = refresh_weather(conn, ["k"], T0)
    assert first == ["МОСКВА +21 ЯСНО", "СОЧИ +27 СОЛНЕЧНО"]
    second = refresh_weather(conn, ["k"], T0 + timedelta(hours=2))  # same MSK day
    assert second == first
    assert calls["n"] == 1
    assert conn.execute("SELECT source FROM weather_pools").fetchone()["source"] == "gemini"


def test_refresh_weather_falls_back_on_any_error(monkeypatch, tmp_path):
    conn = make_db(tmp_path)

    def boom(keys, prompt):
        raise RuntimeError("no quota")

    monkeypatch.setattr(card_content.gemini_client, "generate_text", boom)
    assert refresh_weather(conn, ["k"], T0) == WEATHER_FALLBACK
    assert conn.execute("SELECT source FROM weather_pools").fetchone()["source"] == "fallback"


def test_get_current_weather_defaults_to_fallback_when_empty(tmp_path):
    assert get_current_weather(make_db(tmp_path)) == WEATHER_FALLBACK


def _boom(*_a, **_k):
    raise RuntimeError("no quota")


def test_refresh_currency_generates_then_caches_per_day(monkeypatch, tmp_path):
    conn = make_db(tmp_path)
    monkeypatch.setattr(card_content.gemini_client, "generate_text", lambda k, p: "ДОЛЛАР США|30 РУБ\nЕВРО|35 РУБ")

    cur = card_content.refresh_currency(conn, ["k"], T0)
    assert cur == ["ДОЛЛАР США|30 РУБ", "ЕВРО|35 РУБ"]
    assert card_content.get_currency(conn) == cur

    monkeypatch.setattr(card_content.gemini_client, "generate_text", _boom)
    assert card_content.refresh_currency(conn, ["k"], T0 + timedelta(hours=1)) == cur  # cached, not regenerated
    assert conn.execute("SELECT source FROM service_pools WHERE kind = 'currency'").fetchone()["source"] == "gemini"


def test_refresh_horoscope_falls_back_on_error(monkeypatch, tmp_path):
    conn = make_db(tmp_path)
    monkeypatch.setattr(card_content.gemini_client, "generate_text", _boom)
    assert card_content.refresh_horoscope(conn, ["k"], T0) == card_content.HOROSCOPE_FALLBACK
    assert conn.execute("SELECT source FROM service_pools WHERE kind = 'horoscope'").fetchone()["source"] == "fallback"


def test_get_currency_defaults_to_fallback_when_empty(tmp_path):
    assert card_content.get_currency(make_db(tmp_path)) == card_content.CURRENCY_FALLBACK


def test_refresh_sms_falls_back_on_error(monkeypatch, tmp_path):
    conn = make_db(tmp_path)
    monkeypatch.setattr(card_content.gemini_client, "generate_text", _boom)
    assert card_content.refresh_sms(conn, ["k"], T0) == card_content.SMS_FALLBACK
    assert card_content.get_sms(conn) == card_content.SMS_FALLBACK


def test_day_programmes_lists_only_shows_with_msk_times(tmp_path):
    conn = make_db(tmp_path)
    e1 = _add_prog(conn, "Avatar")
    _log(conn, T0, 20, "episode", e1)  # 10:00 MSK
    # a continuity card between shows must NOT show up in the printed guide
    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, status) VALUES ('weather', '2026-07-06', ?, 60, 'pending')",
        ((T0 + timedelta(minutes=20)).isoformat(),),
    )
    cid = conn.execute("SELECT id FROM cards ORDER BY id DESC LIMIT 1").fetchone()["id"]
    _log(conn, T0 + timedelta(minutes=20), 1, "card", cid)

    assert day_programmes(conn, date(2026, 7, 6)) == [("10:00", "Avatar S01E01 - T")]


def test_epg_day_pages_paginate(tmp_path):
    conn = make_db(tmp_path)
    for i in range(10):
        e = _add_prog(conn, f"Show{i}", title=f"Ep{i}")
        _log(conn, T0 + timedelta(minutes=30 * i), 20, "episode", e)

    pages = epg_day_pages(conn, date(2026, 7, 6), per_page=8)
    assert len(pages) == 2
    assert len(pages[0]) == 8 and len(pages[1]) == 2


def test_epg_next_items_returns_upcoming_programmes(tmp_path):
    conn = make_db(tmp_path)
    e1 = _add_prog(conn, "A")
    e2 = _add_prog(conn, "B")
    _log(conn, T0, 20, "episode", e1)
    _log(conn, T0 + timedelta(minutes=20), 20, "episode", e2)

    items = epg_next_items(conn, T0.isoformat(), count=3)
    assert items == [("10:20", "B S01E01 - T")]
