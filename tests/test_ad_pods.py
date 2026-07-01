from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from director import db
from director.ad_pods import ad_seconds_in_trailing_hour, build_ad_pod, build_filler, pick_bumper


NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def make_db(tmp_path: Path):
    return db.connect(tmp_path / "lib.db")


def add_ad(conn, path, duration, category=None):
    conn.execute(
        "INSERT INTO ads (file_path, category, duration_seconds, scanned_at) VALUES (?, ?, ?, datetime('now'))",
        (path, category, duration),
    )
    return conn.execute("SELECT id FROM ads WHERE file_path = ?", (path,)).fetchone()["id"]


def add_bumper(conn, path, duration, kind=None):
    conn.execute(
        "INSERT INTO bumpers (file_path, kind, duration_seconds, scanned_at) VALUES (?, ?, ?, datetime('now'))",
        (path, kind, duration),
    )


def test_ad_pod_fills_without_exceeding_target(tmp_path):
    conn = make_db(tmp_path)
    add_ad(conn, "/ads/a30", 30)
    add_ad(conn, "/ads/b45", 45)
    add_ad(conn, "/ads/c60", 60)

    pod = build_ad_pod(conn, target_seconds=100, now_utc=NOW)
    total = sum(a["duration_seconds"] for a in pod)
    assert total <= 100
    assert total > 0


def test_ad_pod_prefers_least_recently_used(tmp_path):
    conn = make_db(tmp_path)
    used_id = add_ad(conn, "/ads/used", 30)
    fresh_id = add_ad(conn, "/ads/fresh", 30)

    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) "
        "VALUES (?, ?, 'ad', ?, 'played')",
        (NOW.isoformat(), NOW.isoformat(), used_id),
    )

    # Target only fits one ad, so the pick reveals the ordering.
    pod = build_ad_pod(conn, target_seconds=30, now_utc=NOW)
    assert len(pod) == 1
    assert pod[0]["id"] == fresh_id


def test_pick_bumper_respects_kind_and_duration_filters(tmp_path):
    conn = make_db(tmp_path)
    add_bumper(conn, "/b/intro-long", 20, kind="intro")
    add_bumper(conn, "/b/intro-short", 5, kind="intro")
    add_bumper(conn, "/b/outro-short", 5, kind="outro")

    picked = pick_bumper(conn, kind="intro", max_duration=10)
    assert picked["kind"] == "intro"
    assert picked["duration_seconds"] <= 10


def test_build_filler_falls_back_to_bumper_when_no_ad_fits(tmp_path):
    conn = make_db(tmp_path)
    add_ad(conn, "/ads/toolong", 120)
    add_bumper(conn, "/b/short", 10, kind="interstitial")

    filler = build_filler(conn, remaining_seconds=15, now_utc=NOW)
    assert len(filler) == 1
    kind, item = filler[0]
    assert kind == "bumper"
    assert item["duration_seconds"] <= 15


def test_build_filler_ignores_non_interstitial_bumpers_for_padding(tmp_path):
    conn = make_db(tmp_path)
    add_ad(conn, "/ads/toolong", 120)
    add_bumper(conn, "/b/ad-in", 10, kind="ad_in")  # must not be used as generic padding

    filler = build_filler(conn, remaining_seconds=15, now_utc=NOW)
    assert filler == []


def test_build_filler_returns_empty_when_nothing_fits(tmp_path):
    conn = make_db(tmp_path)
    add_ad(conn, "/ads/toolong", 120)
    add_bumper(conn, "/b/toolong", 60, kind="interstitial")

    filler = build_filler(conn, remaining_seconds=10, now_utc=NOW)
    assert filler == []


def log_ad(conn, start_time, duration):
    end_time = start_time + timedelta(seconds=duration)
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) "
        "VALUES (?, ?, 'ad', NULL, 'scheduled')",
        (start_time.isoformat(), end_time.isoformat()),
    )


def test_ad_seconds_in_trailing_hour_sums_only_the_last_60_minutes(tmp_path):
    conn = make_db(tmp_path)
    log_ad(conn, NOW - timedelta(minutes=90), 100)  # outside the window
    log_ad(conn, NOW - timedelta(minutes=30), 60)  # inside
    log_ad(conn, NOW - timedelta(minutes=5), 40)  # inside

    # julianday() round-trips through floating point, so allow a hair of slop.
    assert ad_seconds_in_trailing_hour(conn, NOW) == pytest.approx(100, abs=0.01)


def test_ad_seconds_in_trailing_hour_is_zero_with_no_ads(tmp_path):
    conn = make_db(tmp_path)
    assert ad_seconds_in_trailing_hour(conn, NOW) == 0
