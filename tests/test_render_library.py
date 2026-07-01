from pathlib import Path
from unittest.mock import MagicMock

from director import db
from director.render_library import _render_table


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def add_episode(conn, path, mtime=100.0, size=1000):
    conn.execute("INSERT OR IGNORE INTO series (name, root_path) VALUES ('S', '/s')")
    sid = conn.execute("SELECT id FROM series WHERE name='S'").fetchone()["id"]
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, "
        "file_mtime, file_size, scanned_at) VALUES (?, 1, 1, 't', ?, 600, ?, ?, datetime('now'))",
        (sid, str(path), mtime, size),
    )


class FakeConfig:
    ntsc_rs_cli_path = Path("cli.exe")
    ntsc_rs_settings_path = Path("settings.json")
    ntsc_render_cache_dir = None  # set per-test


def test_render_table_renders_only_items_needing_it(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    add_episode(conn, tmp_path / "a.mp4")
    add_episode(conn, tmp_path / "b.mp4")

    calls = []

    def fake_ensure_rendered(conn, item_type, row, cli, settings, cache_dir):
        calls.append(row["file_path"])
        return Path("/fake/output.mp4")

    monkeypatch.setattr("director.render_library.ensure_rendered", fake_ensure_rendered)

    config = FakeConfig()
    config.ntsc_render_cache_dir = tmp_path / "cache"
    _render_table(conn, config, "episode")

    assert len(calls) == 2


def test_render_table_skips_items_already_validly_rendered(tmp_path, monkeypatch):
    conn = make_db(tmp_path)
    add_episode(conn, tmp_path / "a.mp4", mtime=100.0, size=1000)

    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"x")
    conn.execute(
        "UPDATE episodes SET rendered_path = ?, rendered_source_mtime = 100.0, rendered_source_size = 1000 WHERE id = 1",
        (str(cached),),
    )

    fake_ensure_rendered = MagicMock()
    monkeypatch.setattr("director.render_library.ensure_rendered", fake_ensure_rendered)

    config = FakeConfig()
    config.ntsc_render_cache_dir = tmp_path / "cache"
    _render_table(conn, config, "episode")

    fake_ensure_rendered.assert_not_called()


def test_render_table_continues_past_a_failed_file(tmp_path, monkeypatch, capsys):
    conn = make_db(tmp_path)
    add_episode(conn, tmp_path / "bad.mp4")
    add_episode(conn, tmp_path / "good.mp4")

    def fake_ensure_rendered(conn, item_type, row, cli, settings, cache_dir):
        if "bad" in row["file_path"]:
            raise RuntimeError("ntsc-rs-cli exploded")
        return Path("/fake/output.mp4")

    monkeypatch.setattr("director.render_library.ensure_rendered", fake_ensure_rendered)

    config = FakeConfig()
    config.ntsc_render_cache_dir = tmp_path / "cache"
    _render_table(conn, config, "episode")  # must not raise

    output = capsys.readouterr().out
    assert "FAILED" in output
    assert "ntsc-rs-cli exploded" in output
    assert "1 rendered, 0 already up to date, 1 failed" in output
