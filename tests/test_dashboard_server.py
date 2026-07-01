import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from director import db
from director.blocks import OFF_AIR_END
from director.dashboard_server import current_broadcast_date, start_server
from director.timeutil import combine_msk


def add_series(conn, name):
    conn.execute("INSERT INTO series (name, root_path) VALUES (?, ?)", (name, f"/{name}"))
    return conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]


def add_episode(conn, series_id, season, episode, duration=600, title="Title"):
    path = f"/fake/{series_id}/{season}/{episode}"
    conn.execute(
        "INSERT INTO episodes (series_id, season, episode, title, file_path, duration_seconds, scanned_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (series_id, season, episode, title, path, duration),
    )
    return conn.execute("SELECT id FROM episodes WHERE file_path = ?", (path,)).fetchone()["id"]


def log_row(conn, start, end, item_id, status="scheduled"):
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id, status) "
        "VALUES (?, ?, 'episode', ?, ?)",
        (start.isoformat(), end.isoformat(), item_id, status),
    )
    return conn.execute("SELECT id FROM program_log ORDER BY id DESC LIMIT 1").fetchone()["id"]


@pytest.fixture
def running_dashboard(tmp_path: Path):
    db_path = tmp_path / "lib.db"
    conn = db.connect(db_path)

    sid = add_series(conn, "Avatar")
    ep1 = add_episode(conn, sid, 1, 1, title="The Boy in the Iceberg")
    ep2 = add_episode(conn, sid, 1, 2, title="The Avatar Returns")

    d = date(2026, 7, 6)
    start = combine_msk(d, OFF_AIR_END)
    row1 = log_row(conn, start, start + timedelta(minutes=10), ep1)
    log_row(conn, start + timedelta(minutes=10), start + timedelta(minutes=20), ep2)
    conn.commit()  # the server handles requests on its own connection to the same file

    server = start_server(db_path, port=0)
    try:
        yield f"http://127.0.0.1:{server.server_port}", conn, {"row1": row1, "ep1": ep1, "ep2": ep2, "day": d}
    finally:
        server.shutdown()


def get_json(url):
    with urllib.request.urlopen(url) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_now_page_serves_html(running_dashboard):
    base, conn, ctx = running_dashboard
    with urllib.request.urlopen(f"{base}/") as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "Сейчас в эфире" in body


def test_epg_page_lists_the_day_and_links_to_neighbors(running_dashboard):
    base, conn, ctx = running_dashboard
    with urllib.request.urlopen(f"{base}/epg?date={ctx['day'].isoformat()}") as resp:
        body = resp.read().decode("utf-8")
        assert "Avatar" in body
        assert "S01E01" in body
        assert "S01E02" in body


def test_api_catalog_filters_by_series_name(running_dashboard):
    base, conn, ctx = running_dashboard
    status, data = get_json(f"{base}/api/catalog?type=episode&q=Avatar")
    assert status == 200
    assert len(data["items"]) == 2
    assert "Avatar" in data["items"][0]["label"]


def test_api_replace_updates_the_row(running_dashboard):
    base, conn, ctx = running_dashboard
    status, data = post_json(f"{base}/api/replace", {"id": ctx["row1"], "item_type": "episode", "item_id": ctx["ep2"]})
    assert status == 200
    assert data["ok"] is True

    row = conn.execute("SELECT item_id FROM program_log WHERE id = ?", (ctx["row1"],)).fetchone()
    assert row["item_id"] == ctx["ep2"]


def test_api_replace_reports_errors_as_400(running_dashboard):
    base, conn, ctx = running_dashboard
    status, data = post_json(f"{base}/api/replace", {"id": ctx["row1"], "item_type": "episode", "item_id": 999999})
    assert status == 400
    assert data["ok"] is False
    assert "not found" in data["error"]


def test_api_delete_removes_the_row(running_dashboard):
    base, conn, ctx = running_dashboard
    status, data = post_json(f"{base}/api/delete", {"id": ctx["row1"]})
    assert status == 200
    assert data["ok"] is True
    assert conn.execute("SELECT * FROM program_log WHERE id = ?", (ctx["row1"],)).fetchone() is None


@pytest.mark.parametrize(
    "msk_hour,expected_offset_days",
    [
        (11, 0),  # after 10:00 -> today's broadcast day
        (5, -1),  # before 10:00 -> still yesterday's broadcast day
    ],
)
def test_current_broadcast_date_rolls_over_at_10_msk(msk_hour, expected_offset_days):
    now_utc = datetime(2026, 7, 6, msk_hour - 3, 0, tzinfo=timezone.utc)  # MSK = UTC+3
    result = current_broadcast_date(now_utc)
    assert result == date(2026, 7, 6) + timedelta(days=expected_offset_days)
