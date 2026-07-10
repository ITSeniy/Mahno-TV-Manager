from datetime import datetime, timedelta, timezone
from pathlib import Path

from director import db
from director.config import Config
from director.render_cards import CARD_KEEP_HOURS, missing_render_config, purge_expired_cards

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


def make_db(tmp_path):
    return db.connect(tmp_path / "lib.db")


def _card(conn, slot_start, rendered_path=None, status="rendered"):
    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, rendered_path, status) "
        "VALUES ('clock', '2026-07-06', ?, 10, ?, ?)",
        (slot_start.isoformat(), rendered_path, status),
    )
    conn.commit()
    return conn.execute("SELECT id FROM cards ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_purge_expired_cards_removes_old_rows_and_their_files(tmp_path):
    conn = make_db(tmp_path)
    old_file = tmp_path / "old.mp4"
    old_file.write_bytes(b"x")
    old = _card(conn, NOW - timedelta(hours=CARD_KEEP_HOURS + 10), str(old_file))

    fresh_file = tmp_path / "fresh.mp4"
    fresh_file.write_bytes(b"y")
    fresh = _card(conn, NOW - timedelta(hours=2), str(fresh_file))
    future = _card(conn, NOW + timedelta(hours=5), None, status="pending")

    removed = purge_expired_cards(conn, NOW)

    assert removed == 1
    assert not old_file.exists()  # the expired card's file is deleted
    assert fresh_file.exists()  # a card from the current day is kept
    ids = {r["id"] for r in conn.execute("SELECT id FROM cards")}
    assert ids == {fresh, future}


def test_purge_tolerates_an_already_missing_file(tmp_path):
    conn = make_db(tmp_path)
    _card(conn, NOW - timedelta(hours=CARD_KEEP_HOURS + 10), str(tmp_path / "gone.mp4"))
    assert purge_expired_cards(conn, NOW) == 1  # no crash on a file that isn't there


def test_missing_render_config_reports_absent_paths():
    cfg = Config(
        series_root=Path("."), ads_root=Path("."), bumpers_root=Path("."), db_path=Path("x"),
        logo_path=None, ticker_port=1, dashboard_port=2, active_series=None, random_rotation_series=[],
        series_categories={}, ntsc_rs_cli_path=None, ntsc_rs_settings_path=Path("s"),
        ntsc_render_cache_dir=Path("c"), card_music_path=None,
        films_root=None, active_films=None, film_categories={}, film_repeat_days=14, test_card_path=None,
        cloth_bg_path=None,
    )
    assert missing_render_config(cfg) == ["ntsc_rs_cli_path"]
