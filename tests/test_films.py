from datetime import datetime, timedelta, timezone

from director import db
from director.films import film_reels, last_film_airing, pick_next_film

NOW = datetime(2026, 7, 4, 18, 0, tzinfo=timezone.utc)


def make_db(tmp_path):
    return db.connect(tmp_path / "lib.db")


def add_film(conn, title, reel_durations):
    conn.execute("INSERT INTO films (title, root_path) VALUES (?, ?)", (title, f"/{title}"))
    fid = conn.execute("SELECT id FROM films WHERE title = ?", (title,)).fetchone()["id"]
    for i, d in enumerate(reel_durations, start=1):
        conn.execute(
            "INSERT INTO reels (film_id, reel_number, file_path, duration_seconds, scanned_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (fid, i, f"/{title}/r{i}.mkv", d),
        )
    conn.commit()
    return fid


def air_film(conn, fid, when):
    reel = conn.execute("SELECT id FROM reels WHERE film_id = ? ORDER BY reel_number LIMIT 1", (fid,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) VALUES (?, ?, 'film', ?, 'played')",
        (when.isoformat(), (when + timedelta(minutes=90)).isoformat(), reel),
    )
    conn.commit()


def test_film_reels_are_ordered_by_reel_number(tmp_path):
    conn = make_db(tmp_path)
    fid = add_film(conn, "A", [100, 200, 300])
    assert [r["reel_number"] for r in film_reels(conn, fid)] == [1, 2, 3]


def test_pick_next_film_prefers_never_aired(tmp_path):
    conn = make_db(tmp_path)
    a = add_film(conn, "A", [1800, 1800])
    b = add_film(conn, "B", [1800, 1800])
    air_film(conn, a, NOW - timedelta(days=1))  # A aired recently, B never

    picked = pick_next_film(conn, [a, b], NOW, repeat_days=14)
    assert picked is not None and picked[0] == b


def test_pick_next_film_skips_a_recently_aired_film(tmp_path):
    conn = make_db(tmp_path)
    a = add_film(conn, "A", [1800])
    air_film(conn, a, NOW - timedelta(days=3))  # within the 14-day window
    assert pick_next_film(conn, [a], NOW, repeat_days=14) is None


def test_pick_next_film_allows_repeat_after_the_window(tmp_path):
    conn = make_db(tmp_path)
    a = add_film(conn, "A", [1800])
    air_film(conn, a, NOW - timedelta(days=20))
    assert last_film_airing(conn, a) != ""
    picked = pick_next_film(conn, [a], NOW, repeat_days=14)
    assert picked is not None and picked[0] == a


def test_pick_next_film_respects_the_duration_budget(tmp_path):
    conn = make_db(tmp_path)
    a = add_film(conn, "A", [3600, 3600])  # 2h total
    assert pick_next_film(conn, [a], NOW, repeat_days=14, max_total_seconds=3000) is None  # 50min room, doesn't fit
    assert pick_next_film(conn, [a], NOW, repeat_days=14, max_total_seconds=8000) is not None


def test_pick_next_film_returns_none_when_no_films(tmp_path):
    conn = make_db(tmp_path)
    assert pick_next_film(conn, [], NOW, repeat_days=14) is None
