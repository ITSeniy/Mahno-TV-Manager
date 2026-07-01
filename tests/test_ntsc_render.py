from pathlib import Path
from unittest.mock import MagicMock

import pytest

from director import db
from director.ntsc_render import cache_path_for, ensure_rendered, is_render_valid, render_file


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def add_episode(conn, path, mtime=100.0, size=1000):
    conn.execute("INSERT INTO series (name, root_path) VALUES ('S', '/s')")
    sid = conn.execute("SELECT id FROM series WHERE name='S'").fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, "
        "file_mtime, file_size, scanned_at) VALUES (?, 1, 1, 't', ?, 600, ?, ?, datetime('now'))",
        (sid, str(path), mtime, size),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path=?", (str(path),)).fetchone()["id"]


def get_episode(conn, ep_id):
    return conn.execute("SELECT * FROM episodes WHERE id = ?", (ep_id,)).fetchone()


def test_cache_path_for_is_keyed_by_id_not_filename(tmp_path):
    path = cache_path_for(tmp_path, "episode", 42)
    assert path == tmp_path / "episode" / "42.mp4"


def test_is_render_valid_false_when_never_rendered(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4")
    assert is_render_valid(get_episode(conn, ep_id)) is False


def test_is_render_valid_false_when_cached_file_missing_from_disk(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4")
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 100.0, rendered_source_size = 1000 "
        "WHERE id = ?",
        (str(tmp_path / "does_not_exist.mp4"), ep_id),
    )
    assert is_render_valid(get_episode(conn, ep_id)) is False


def test_is_render_valid_false_when_source_changed_since_render(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4", mtime=200.0, size=2000)
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"x")
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 100.0, rendered_source_size = 1000 "
        "WHERE id = ?",
        (str(cached), ep_id),
    )
    assert is_render_valid(get_episode(conn, ep_id)) is False


def test_is_render_valid_true_when_cache_matches_current_source(tmp_path):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4", mtime=100.0, size=1000)
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"x")
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 100.0, rendered_source_size = 1000 "
        "WHERE id = ?",
        (str(cached), ep_id),
    )
    assert is_render_valid(get_episode(conn, ep_id)) is True


def test_render_file_invokes_the_cli_with_expected_arguments(tmp_path, monkeypatch):
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    monkeypatch.setattr("director.ntsc_render.subprocess.run", fake_run)

    output = tmp_path / "out" / "result.mp4"
    output.parent.mkdir()
    output.touch()  # render_file checks the output actually exists afterward

    render_file(Path("cli.exe"), Path("settings.json"), Path("in.mp4"), output)

    args = fake_run.call_args[0][0]
    assert args[0] == "cli.exe"
    assert "-i" in args and "in.mp4" in args
    assert "-o" in args and str(output) in args
    assert "-p" in args and "settings.json" in args
    assert "-y" in args


def test_render_file_raises_on_nonzero_exit(tmp_path, monkeypatch):
    fake_run = MagicMock(return_value=MagicMock(returncode=1, stderr="boom"))
    monkeypatch.setattr("director.ntsc_render.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        render_file(Path("cli.exe"), Path("settings.json"), Path("in.mp4"), tmp_path / "out.mp4")


def test_render_file_raises_when_output_was_not_actually_produced(tmp_path, monkeypatch):
    # Some failure modes exit 0 but silently don't write anything - treat that as a failure too.
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    monkeypatch.setattr("director.ntsc_render.subprocess.run", fake_run)

    with pytest.raises(RuntimeError):
        render_file(Path("cli.exe"), Path("settings.json"), Path("in.mp4"), tmp_path / "never_created.mp4")


def test_ensure_rendered_skips_actual_rendering_when_already_valid(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4", mtime=100.0, size=1000)
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"x")
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 100.0, rendered_source_size = 1000 "
        "WHERE id = ?",
        (str(cached), ep_id),
    )

    fake_render = MagicMock()
    monkeypatch.setattr("director.ntsc_render.render_file", fake_render)

    result = ensure_rendered(conn, "episode", get_episode(conn, ep_id), Path("cli"), Path("settings"), tmp_path / "cache")
    assert result == cached
    fake_render.assert_not_called()


def test_ensure_rendered_renders_and_updates_the_row_when_needed(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    ep_id = add_episode(conn, tmp_path / "source.mp4", mtime=100.0, size=1000)

    def fake_render(cli_path, settings_path, input_path, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"rendered")

    monkeypatch.setattr("director.ntsc_render.render_file", fake_render)

    cache_dir = tmp_path / "cache"
    result = ensure_rendered(conn, "episode", get_episode(conn, ep_id), Path("cli"), Path("settings"), cache_dir)

    assert result == cache_path_for(cache_dir, "episode", ep_id)
    assert result.exists()

    row = get_episode(conn, ep_id)
    assert row["rendered_path"] == str(result)
    assert row["rendered_source_mtime"] == 100.0
    assert row["rendered_source_size"] == 1000
