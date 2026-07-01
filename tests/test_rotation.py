from pathlib import Path

from director import db
from director.rotation import pick_next_episode


def make_db(tmp_path: Path):
    conn = db.connect(tmp_path / "lib.db")
    return conn


def add_series(conn, name):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))
    return conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]


def add_episode(conn, series_id, season, episode, duration=600):
    path = f"/fake/{series_id}/{season}/{episode}"
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (series_id, season, episode, f"ep{episode}", path, duration),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path = ?", (path,)).fetchone()["id"]


def log_aired(conn, episode_id, start_time):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) "
        "VALUES (?, ?, 'episode', ?, 'played')",
        (start_time, start_time, episode_id),
    )


def test_sequential_cursor_advances_and_wraps(tmp_path):
    conn = make_db(tmp_path)
    sid = add_series(conn, "Show A")
    ep1 = add_episode(conn, sid, 1, 1)
    ep2 = add_episode(conn, sid, 1, 2)

    first = pick_next_episode(conn, [sid], 9999, [], max_consecutive=5)
    assert first["id"] == ep1

    log_aired(conn, ep1, "2026-07-01T10:00:00+00:00")
    second = pick_next_episode(conn, [sid], 9999, [], max_consecutive=5)
    assert second["id"] == ep2

    log_aired(conn, ep2, "2026-07-01T10:10:00+00:00")
    wrapped = pick_next_episode(conn, [sid], 9999, [], max_consecutive=5)
    assert wrapped["id"] == ep1  # cycled back to the start of the series


def test_round_robin_prefers_longest_since_aired(tmp_path):
    conn = make_db(tmp_path)
    a = add_series(conn, "Show A")
    b = add_series(conn, "Show B")
    ep_a = add_episode(conn, a, 1, 1)
    add_episode(conn, b, 1, 1)

    log_aired(conn, ep_a, "2026-07-01T10:00:00+00:00")
    pick = pick_next_episode(conn, [a, b], 9999, [], max_consecutive=5)
    assert pick["series_id"] == b  # A aired recently, B never aired -> B goes next


def test_max_consecutive_same_series_is_enforced(tmp_path):
    conn = make_db(tmp_path)
    a = add_series(conn, "Show A")
    b = add_series(conn, "Show B")
    add_episode(conn, a, 1, 1)
    add_episode(conn, a, 1, 2)
    add_episode(conn, b, 1, 1)

    # Series A just aired twice in a row; with max_consecutive=2 it must be skipped even
    # though it's otherwise next in the round-robin priority order.
    pick = pick_next_episode(conn, [a, b], 9999, recent_series_window=[a, a], max_consecutive=2)
    assert pick["series_id"] == b


def test_skips_series_whose_episode_does_not_fit_remaining_time(tmp_path):
    conn = make_db(tmp_path)
    a = add_series(conn, "Show A")
    b = add_series(conn, "Show B")
    add_episode(conn, a, 1, 1, duration=1800)  # too long
    add_episode(conn, b, 1, 1, duration=300)

    pick = pick_next_episode(conn, [a, b], max_duration_seconds=600, recent_series_window=[], max_consecutive=5)
    assert pick["series_id"] == b


def test_returns_none_when_nothing_fits(tmp_path):
    conn = make_db(tmp_path)
    a = add_series(conn, "Show A")
    add_episode(conn, a, 1, 1, duration=1800)

    pick = pick_next_episode(conn, [a], max_duration_seconds=60, recent_series_window=[], max_consecutive=5)
    assert pick is None
