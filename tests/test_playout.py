from datetime import datetime, timedelta, timezone
from pathlib import Path

from director import db
from director.playout import advance_status, find_current_row, resolve_media_path

T0 = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def add_episode(conn, path="/ep.mkv"):
    conn.execute("INSERT INTO series (name, root_path) VALUES ('S', '/s')")
    sid = conn.execute("SELECT id FROM series WHERE name='S'").fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, 1, 1, 't', ?, 60, datetime('now'))",
        (sid, path),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path=?", (path,)).fetchone()["id"]


def log_row(conn, start, end, item_type="episode", item_id=None, status="scheduled"):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) VALUES (?, ?, ?, ?, ?)",
        (start.isoformat(), end.isoformat(), item_type, item_id, status),
    )
    return conn.execute("SELECT id FROM program_log ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_find_current_row_picks_the_row_covering_now(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn)
    row_a = log_row(conn, T0, T0 + timedelta(minutes=5), item_id=ep_id)
    row_b = log_row(conn, T0 + timedelta(minutes=5), T0 + timedelta(minutes=10), item_id=ep_id)

    assert find_current_row(conn, T0 + timedelta(minutes=2))["id"] == row_a
    # exactly on the boundary -> the row that is starting, not the one that just ended
    assert find_current_row(conn, T0 + timedelta(minutes=5))["id"] == row_b
    assert find_current_row(conn, T0 + timedelta(minutes=9))["id"] == row_b


def test_find_current_row_returns_none_outside_generated_range(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn)
    log_row(conn, T0, T0 + timedelta(minutes=5), item_id=ep_id)

    assert find_current_row(conn, T0 - timedelta(minutes=1)) is None
    assert find_current_row(conn, T0 + timedelta(hours=1)) is None


def test_resolve_media_path_for_each_item_type(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, "/library/ep1.mkv")
    conn.execute("INSERT INTO ads (file_path, duration_seconds, scanned_at) VALUES ('/ads/a.mp4', 30, datetime('now'))")
    ad_id = conn.execute("SELECT id FROM ads WHERE file_path='/ads/a.mp4'").fetchone()["id"]

    ep_row = conn.execute(
        "SELECT ? AS item_type, ? AS item_id", ("episode", ep_id)
    ).fetchone()
    assert resolve_media_path(conn, ep_row) == ("/library/ep1.mkv", False)

    ad_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("ad", ad_id)).fetchone()
    assert resolve_media_path(conn, ad_row) == ("/ads/a.mp4", False)

    off_air_row = conn.execute("SELECT 'off_air' AS item_type, NULL AS item_id").fetchone()
    assert resolve_media_path(conn, off_air_row) == (None, False)


def test_resolve_media_path_prefers_a_valid_ntsc_rs_render(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, "/library/ep1.mkv")

    rendered_path = tmp_path / "rendered.mp4"
    rendered_path.write_bytes(b"fake")
    row = conn.execute("SELECT file_mtime, file_size FROM episodes WHERE id = ?", (ep_id,)).fetchone()
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = ?, rendered_source_size = ? WHERE id = ?",
        (str(rendered_path), row["file_mtime"], row["file_size"], ep_id),
    )

    ep_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("episode", ep_id)).fetchone()
    assert resolve_media_path(conn, ep_row) == (str(rendered_path), True)


def test_resolve_media_path_falls_back_to_raw_when_render_is_stale(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, "/library/ep1.mkv")

    rendered_path = tmp_path / "rendered.mp4"
    rendered_path.write_bytes(b"fake")
    # A stale mtime/size means the source changed since it was last rendered.
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 0, rendered_source_size = 0 WHERE id = ?",
        (str(rendered_path), ep_id),
    )

    ep_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("episode", ep_id)).fetchone()
    assert resolve_media_path(conn, ep_row) == ("/library/ep1.mkv", False)


def _add_card(conn, status, rendered_path=None, kind="weather", target=47):
    conn.execute(
        "INSERT INTO cards (kind, msk_date, slot_start, target_seconds, rendered_path, status) "
        "VALUES (?, '2026-07-06', ?, ?, ?, ?)",
        (kind, T0.isoformat(), target, rendered_path, status),
    )
    return conn.execute("SELECT id FROM cards ORDER BY id DESC LIMIT 1").fetchone()["id"]


def test_resolve_media_path_for_a_reel_and_film_marker(tmp_path):
    conn = make_db(tmp_path)
    conn.execute("INSERT INTO films (title, root_path) VALUES ('K', '/k')")
    fid = conn.execute("SELECT id FROM films WHERE title = 'K'").fetchone()["id"]
    conn.execute(
        "INSERT INTO reels (film_id, reel_number, file_path, duration_seconds, scanned_at) "
        "VALUES (?, 1, '/k/r1.mkv', 1500, datetime('now'))",
        (fid,),
    )
    rid = conn.execute("SELECT id FROM reels").fetchone()["id"]

    # both the 'film' marker and 'reel' rows resolve to the reels table
    reel_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("reel", rid)).fetchone()
    film_row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("film", rid)).fetchone()
    assert resolve_media_path(conn, reel_row) == ("/k/r1.mkv", False)
    assert resolve_media_path(conn, film_row) == ("/k/r1.mkv", False)


def test_resolve_media_path_for_sms_chat_is_none(tmp_path):
    conn = make_db(tmp_path)
    row = conn.execute("SELECT 'sms_chat' AS item_type, NULL AS item_id").fetchone()
    # no file - apply_item switches to the SMS_CHAT scene instead
    assert resolve_media_path(conn, row) == (None, False)


def test_resolve_media_path_for_a_rendered_card(tmp_path):
    conn = make_db(tmp_path)
    rendered = tmp_path / "card.mp4"
    rendered.write_bytes(b"x")
    cid = _add_card(conn, "rendered", str(rendered))

    row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("card", cid)).fetchone()
    # ntsc-rs is baked into the card at render time, so it reports as pre-rendered.
    assert resolve_media_path(conn, row) == (str(rendered), True)


def test_resolve_media_path_card_falls_back_to_interstitial_when_unrendered(tmp_path):
    conn = make_db(tmp_path)
    cid = _add_card(conn, "pending")
    conn.execute(
        "INSERT INTO bumpers (file_path, kind, duration_seconds, scanned_at) "
        "VALUES ('/b/i.mp4', 'interstitial', 8, datetime('now'))"
    )

    row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("card", cid)).fetchone()
    assert resolve_media_path(conn, row) == ("/b/i.mp4", False)


def test_resolve_media_path_card_returns_none_when_unrendered_and_no_fallback(tmp_path):
    conn = make_db(tmp_path)
    cid = _add_card(conn, "pending")

    row = conn.execute("SELECT ? AS item_type, ? AS item_id", ("card", cid)).fetchone()
    assert resolve_media_path(conn, row) == (None, False)


def test_advance_status_marks_elapsed_previous_row_as_played_and_logs_history(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn)
    row_id = log_row(conn, T0, T0 + timedelta(minutes=5), item_id=ep_id)

    advance_status(conn, row_id, T0 + timedelta(minutes=5, seconds=1))

    row = conn.execute("SELECT status FROM program_log WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "played"

    history = conn.execute("SELECT * FROM play_history").fetchall()
    assert len(history) == 1
    assert history[0]["item_type"] == "episode"
    assert history[0]["item_id"] == ep_id


def test_advance_status_does_not_touch_row_that_has_not_elapsed_yet(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn)
    row_id = log_row(conn, T0, T0 + timedelta(minutes=5), item_id=ep_id)

    advance_status(conn, row_id, T0 + timedelta(minutes=2))  # still mid-playback

    row = conn.execute("SELECT status FROM program_log WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "scheduled"
    assert conn.execute("SELECT COUNT(*) AS c FROM play_history").fetchone()["c"] == 0


def test_advance_status_marks_rows_skipped_over_as_skipped_not_played(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn)
    row_a = log_row(conn, T0, T0 + timedelta(minutes=5), item_id=ep_id)
    row_b = log_row(conn, T0 + timedelta(minutes=5), T0 + timedelta(minutes=10), item_id=ep_id)
    row_c = log_row(conn, T0 + timedelta(minutes=10), T0 + timedelta(minutes=15), item_id=ep_id)

    # Controller was "down" and only picks up at minute 12, having last applied row_a.
    advance_status(conn, row_a, T0 + timedelta(minutes=12))

    statuses = {
        r["id"]: r["status"]
        for r in conn.execute("SELECT id, status FROM program_log").fetchall()
    }
    assert statuses[row_a] == "played"  # the one we were actually "on" when we last checked
    assert statuses[row_b] == "skipped"  # fully elapsed but never applied
    assert statuses[row_c] == "scheduled"  # still current/future

    history_item_ids = [r["item_id"] for r in conn.execute("SELECT item_id FROM play_history").fetchall()]
    assert history_item_ids == [ep_id]  # only the played one is logged, not the skipped one


def test_advance_status_handles_no_previous_row(tmp_path):
    conn = make_db(tmp_path)
    add_episode(conn)
    # Should simply not error when nothing has been applied yet (fresh start).
    advance_status(conn, None, T0)
