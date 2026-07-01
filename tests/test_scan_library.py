from pathlib import Path

import pytest

from director.scan_library import classify_ad, classify_bumper


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
