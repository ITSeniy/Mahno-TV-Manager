import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from director import db, ticker_content

T0 = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)  # 13:00 MSK


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def _put_pool(conn, lines):
    conn.execute(
        "INSERT INTO ticker_pools (generated_at, msk_date, source, lines_json) VALUES ('', '2026-07-06', 'gemini', ?)",
        (json.dumps(lines, ensure_ascii=False),),
    )
    conn.commit()


def _air_episode(conn, series_name, start, minutes=10):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (series_name, f"/{series_name}"))
    sid = conn.execute("SELECT id FROM series WHERE name = ?", (series_name,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, 1, 1, 't', ?, 600, datetime('now'))",
        (sid, f"/{series_name}/e"),
    )
    eid = conn.execute("SELECT id FROM episodes WHERE series_id = ?", (sid,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) VALUES (?, ?, 'episode', ?, 'scheduled')",
        (start.isoformat(), (start + timedelta(minutes=minutes)).isoformat(), eid),
    )
    conn.commit()


def test_parse_lines_strips_numbering_bullets_and_wrapping_quotes():
    raw = '1. ПЕРВАЯ СТРОКА\n- "ВТОРАЯ СТРОКА"\n* Третья строка\n\n   \n4) Четвёртая'
    assert ticker_content.parse_lines(raw) == [
        "ПЕРВАЯ СТРОКА",
        "ВТОРАЯ СТРОКА",
        "Третья строка",
        "Четвёртая",
    ]


def test_get_current_pool_returns_static_fallback_when_empty(tmp_path):
    conn = make_db(tmp_path)
    assert ticker_content.get_current_pool(conn) == ticker_content.STATIC_FALLBACK


def test_refresh_pool_uses_gemini_and_caches_by_msk_date(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    calls = []

    def fake_generate(api_keys, prompt):
        calls.append(api_keys)
        return "СТРОКА ОДНА\nСТРОКА ДВА"

    monkeypatch.setattr(ticker_content.gemini_client, "generate_text", fake_generate)

    lines = ticker_content.refresh_pool(conn, ["key1"], T0)
    assert lines == ["СТРОКА ОДНА", "СТРОКА ДВА"]
    assert len(calls) == 1

    row = conn.execute("SELECT source, msk_date FROM ticker_pools").fetchone()
    assert row["source"] == "gemini"
    assert row["msk_date"] == "2026-07-06"

    # Second call same MSK day must not hit Gemini again.
    lines_again = ticker_content.refresh_pool(conn, ["key1"], T0.replace(hour=20))
    assert lines_again == lines
    assert len(calls) == 1


def test_refresh_pool_falls_back_when_gemini_raises(tmp_path, monkeypatch):
    conn = make_db(tmp_path)

    def fake_generate(api_keys, prompt):
        raise RuntimeError("all keys exhausted")

    monkeypatch.setattr(ticker_content.gemini_client, "generate_text", fake_generate)

    lines = ticker_content.refresh_pool(conn, ["key1"], T0)
    assert lines == ticker_content.STATIC_FALLBACK

    row = conn.execute("SELECT source FROM ticker_pools").fetchone()
    assert row["source"] == "fallback"


def test_refresh_pool_falls_back_when_gemini_returns_unusable_text(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    monkeypatch.setattr(ticker_content.gemini_client, "generate_text", lambda keys, prompt: "   \n\n  ")

    lines = ticker_content.refresh_pool(conn, ["key1"], T0)
    assert lines == ticker_content.STATIC_FALLBACK


def test_current_programme_name_returns_the_show_on_air(tmp_path):
    conn = make_db(tmp_path)
    _air_episode(conn, "Avatar", T0)
    assert ticker_content.current_programme_name(conn, T0 + timedelta(minutes=1)) == "Avatar"
    assert ticker_content.current_programme_name(conn, T0 + timedelta(hours=2)) is None


def test_current_ticker_lines_filters_to_the_show_on_air(tmp_path):
    conn = make_db(tmp_path)
    _put_pool(conn, ["Avatar::СМОТРИТЕ АВАТАРА", "::СПАСИБО ЧТО С НАМИ", "Zim::ЗИМ БУДЕТ ПОЗЖЕ"])
    _air_episode(conn, "Avatar", T0)

    lines = ticker_content.current_ticker_lines(conn, T0 + timedelta(minutes=1))
    assert "СМОТРИТЕ АВАТАРА" in lines  # tagged for the current show, prefix stripped
    assert "СПАСИБО ЧТО С НАМИ" in lines  # generic ::text
    assert "ЗИМ БУДЕТ ПОЗЖЕ" not in lines  # tagged for a different show


def test_current_ticker_lines_shows_only_generics_when_nothing_is_on_air(tmp_path):
    conn = make_db(tmp_path)
    _put_pool(conn, ["Avatar::АВАТАР СЕЙЧАС", "::ОБЩАЯ ФРАЗА"])
    lines = ticker_content.current_ticker_lines(conn, T0)  # no program_log
    assert lines == ["ОБЩАЯ ФРАЗА"]


def test_refresh_pool_regenerates_on_a_new_msk_day(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    responses = iter(["DAY ONE LINE", "DAY TWO LINE"])
    monkeypatch.setattr(ticker_content.gemini_client, "generate_text", lambda keys, prompt: next(responses))

    day1 = ticker_content.refresh_pool(conn, ["key1"], T0)
    day2_time = T0.replace(day=7)
    day2 = ticker_content.refresh_pool(conn, ["key1"], day2_time)

    assert day1 == ["DAY ONE LINE"]
    assert day2 == ["DAY TWO LINE"]
    assert conn.execute("SELECT COUNT(*) AS c FROM ticker_pools").fetchone()["c"] == 2
