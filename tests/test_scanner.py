from pathlib import Path

import pytest

from director import db
from director.media_probe import MediaInfo
from director.scanner import parse_season_episode, scan_series_root


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Show.S01E05.mkv", (1, 5)),
        ("Show.S1E5.mkv", (1, 5)),
        ("Show 2x13 - Title.avi", (2, 13)),
        ("07 - Title.mp4", (1, 7)),
        ("Title without numbers.mkv", (1, None)),
        ("Special.mp4", (1, None)),  # digit in the extension must not count as an episode number
        ("Special.m4v", (1, None)),
    ],
)
def test_parse_season_episode(filename, expected):
    assert parse_season_episode(filename) == expected


def test_scan_series_root_assigns_fallback_episode_numbers(tmp_path, monkeypatch):
    series_dir = tmp_path / "library" / "Test Show"
    series_dir.mkdir(parents=True)
    (series_dir / "Intro.mkv").touch()
    (series_dir / "S01E01.mkv").touch()

    monkeypatch.setattr(
        "director.scanner.probe",
        lambda path: MediaInfo(duration_seconds=600.0, width=1920, height=1080),
    )

    conn = db.connect(tmp_path / "data" / "library.db")
    stats = scan_series_root(conn, tmp_path / "library")

    assert stats.added == 2
    assert stats.errors == []

    rows = conn.execute(
        "SELECT season, episode, file_path FROM episodes ORDER BY file_path"
    ).fetchall()
    episodes = {(r["season"], r["episode"]) for r in rows}
    # S01E01.mkv keeps its explicit number; Intro.mkv falls back to the next free slot.
    assert (1, 1) in episodes
    assert (1, 2) in episodes


def test_rescan_marks_deleted_file_as_missing(tmp_path, monkeypatch):
    series_dir = tmp_path / "library" / "Test Show"
    series_dir.mkdir(parents=True)
    ep_path = series_dir / "S01E01.mkv"
    ep_path.touch()

    monkeypatch.setattr(
        "director.scanner.probe",
        lambda path: MediaInfo(duration_seconds=600.0, width=1920, height=1080),
    )

    conn = db.connect(tmp_path / "data" / "library.db")
    scan_series_root(conn, tmp_path / "library")

    ep_path.unlink()
    stats = scan_series_root(conn, tmp_path / "library")

    assert stats.missing == 1
    row = conn.execute("SELECT missing FROM episodes").fetchone()
    assert row["missing"] == 1
