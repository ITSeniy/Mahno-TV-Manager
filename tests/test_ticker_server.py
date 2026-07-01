import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from director import db, ticker_content
from director.ticker_server import start_server


@pytest.fixture
def running_server(tmp_path: Path):
    db_path = tmp_path / "lib.db"
    conn = db.connect(db_path)
    conn.execute(
        "INSERT INTO ticker_pools (generated_at, msk_date, source, lines_json) VALUES "
        "(datetime('now'), '2026-07-06', 'gemini', ?)",
        (json.dumps(["СТРОКА ПЕРВАЯ", "СТРОКА ВТОРАЯ"], ensure_ascii=False),),
    )
    conn.commit()

    server = start_server(db_path, port=0)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_index_page_serves_html(running_server):
    with urllib.request.urlopen(f"{running_server}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers["Content-Type"]
        body = resp.read().decode("utf-8")
        assert "ticker-track" in body
        assert "/ticker.json" in body


def test_ticker_json_reflects_current_pool(running_server):
    with urllib.request.urlopen(f"{running_server}/ticker.json") as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers["Content-Type"]
        data = json.loads(resp.read().decode("utf-8"))
        assert data["lines"] == ["СТРОКА ПЕРВАЯ", "СТРОКА ВТОРАЯ"]


def test_unknown_path_returns_404(running_server):
    try:
        urllib.request.urlopen(f"{running_server}/nope")
        assert False, "expected an HTTPError"
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
