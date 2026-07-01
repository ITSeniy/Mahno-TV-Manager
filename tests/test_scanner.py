from pathlib import Path

import pytest

from director import db
from director.media_probe import MediaInfo
from director.scanner import (
    parse_season_episode,
    parse_season_from_folder,
    scan_flat_root,
    scan_series_root,
)


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
        ("1.01. A Night At The Katz Motel.mp4", (1, 1)),  # season.episode dot notation (Courage)
        ("1.11. Some Title.mp4", (1, 11)),
        ("Wunschpunsch.(01).Plant.Panic.mp4", (1, 1)),  # dot before the paren must not trigger N.NN
        ("1ACV01 «Space Pilot 3000» [LonerD].mp4", (1, 1)),  # Futurama production code
        ("4ACV12 «Some Title».mp4", (4, 12)),
    ],
)
def test_parse_season_episode(filename, expected):
    assert parse_season_episode(filename) == expected


@pytest.mark.parametrize(
    "folder_name,expected",
    [
        ("1 sezon", 1),
        ("2 sezon", 2),
        ("Season 3", 3),
        ("сезон 4", 4),
        ("Random Folder", None),
    ],
)
def test_parse_season_from_folder(folder_name, expected):
    assert parse_season_from_folder(folder_name) == expected


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


def test_scan_series_root_only_scans_active_series(tmp_path, monkeypatch):
    library = tmp_path / "library"
    for name in ("Show A", "Ads", "DaVinci"):
        (library / name).mkdir(parents=True)
        (library / name / "01.mkv").touch()

    monkeypatch.setattr(
        "director.scanner.probe",
        lambda path: MediaInfo(duration_seconds=600.0, width=1920, height=1080),
    )

    conn = db.connect(tmp_path / "data" / "library.db")
    scan_series_root(conn, library, active_series=["Show A"])

    series_names = {r["name"] for r in conn.execute("SELECT name FROM series").fetchall()}
    assert series_names == {"Show A"}


def test_scan_series_root_reads_season_from_parent_folder(tmp_path, monkeypatch):
    series_dir = tmp_path / "library" / "W.I.T.C.H."
    (series_dir / "1 sezon").mkdir(parents=True)
    (series_dir / "2 sezon").mkdir(parents=True)
    (series_dir / "1 sezon" / "01. Istoriya nachinaetsya.avi").touch()
    (series_dir / "2 sezon" / "01. Novaya seriya.avi").touch()

    monkeypatch.setattr(
        "director.scanner.probe",
        lambda path: MediaInfo(duration_seconds=600.0, width=1920, height=1080),
    )

    conn = db.connect(tmp_path / "data" / "library.db")
    stats = scan_series_root(conn, tmp_path / "library")

    assert stats.errors == []
    rows = conn.execute("SELECT season, episode FROM episodes ORDER BY season").fetchall()
    assert [(r["season"], r["episode"]) for r in rows] == [(1, 1), (2, 1)]


def test_scan_flat_root_with_classify_splits_a_shared_folder(tmp_path, monkeypatch):
    shared = tmp_path / "library" / "Bumpers"
    shared.mkdir(parents=True)
    (shared / "ad-block-1.mp4").touch()
    (shared / "ad-in-1.mp4").touch()
    (shared / "ad-out-1.mp4").touch()
    (shared / "Bumper.mp4").touch()

    monkeypatch.setattr(
        "director.scanner.probe",
        lambda path: MediaInfo(duration_seconds=10.0, width=720, height=576),
    )

    def classify_ad(path):
        name = path.stem.lower()
        return None if name.startswith(("ad-in", "ad-out", "bumper")) else "general"

    def classify_bumper(path):
        name = path.stem.lower()
        if name.startswith("ad-in"):
            return "ad_in"
        if name.startswith("ad-out"):
            return "ad_out"
        if name.startswith("ad-block"):
            return None
        return "interstitial"

    conn = db.connect(tmp_path / "data" / "library.db")
    scan_flat_root(conn, shared, "ads", "category", classify=classify_ad)
    scan_flat_root(conn, shared, "bumpers", "kind", classify=classify_bumper)

    ads = [r["file_path"] for r in conn.execute("SELECT file_path FROM ads").fetchall()]
    assert len(ads) == 1
    assert "ad-block-1" in ads[0]

    bumpers = {r["kind"] for r in conn.execute("SELECT kind FROM bumpers").fetchall()}
    assert bumpers == {"ad_in", "ad_out", "interstitial"}


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
