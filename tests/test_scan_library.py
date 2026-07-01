from pathlib import Path

import pytest

from director import db
from director.scan_library import apply_rotation_modes, classify_ad, classify_bumper


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("ad-block-1.mp4", "general"),
        ("ad-block-2.mp4", "general"),
        ("ad-in-1.mp4", None),
        ("ad-out-1.mp4", None),
        ("Bumper.mp4", None),
    ],
)
def test_classify_ad(filename, expected):
    assert classify_ad(Path(filename)) == expected


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("ad-in-1.mp4", "ad_in"),
        ("ad-out-1.mp4", "ad_out"),
        ("ad-block-1.mp4", None),
        ("Bumper.mp4", "interstitial"),
        ("some-other-clip.mp4", "interstitial"),
    ],
)
def test_classify_bumper(filename, expected):
    assert classify_bumper(Path(filename)) == expected


def test_apply_rotation_modes_marks_only_named_series_as_random(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    for name in ("Avatar", "Beavers", "Cats"):
        conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))

    apply_rotation_modes(conn, ["Beavers", "Cats"])

    modes = {r["name"]: r["rotation_mode"] for r in conn.execute("SELECT name, rotation_mode FROM series")}
    assert modes == {"Avatar": "sequential", "Beavers": "random", "Cats": "random"}


def test_apply_rotation_modes_is_idempotent_and_resets_on_rerun(tmp_path):
    conn = db.connect(tmp_path / "lib.db")
    conn.execute("INSERT INTO series (name, root_path) VALUES ('Avatar', '/Avatar')")

    apply_rotation_modes(conn, ["Avatar"])
    assert conn.execute("SELECT rotation_mode FROM series").fetchone()["rotation_mode"] == "random"

    # Re-running with an updated (now empty) list must flip it back, not just leave stale state.
    apply_rotation_modes(conn, [])
    assert conn.execute("SELECT rotation_mode FROM series").fetchone()["rotation_mode"] == "sequential"
