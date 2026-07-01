"""Local HTTP dashboard: "on air now" page and a multi-day EPG grid with
manual replace/delete actions on not-yet-aired program_log rows.

Runs on its own port (config.dashboard_port) via run_dashboard.py, managed
by supervisor.py alongside the ticker server and playout controller.
"""

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from director.blocks import OFF_AIR_END
from director.dashboard_data import (
    delete_item,
    describe_item,
    get_day_schedule,
    get_now_and_next,
    replace_item,
    search_catalog,
)
from director.timeutil import utc_to_msk

PAGE_STYLE = """
<style>
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background: #14161a; color: #e8e8e8; margin: 0; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 16px; }
  a { color: #7ab8ff; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #2a2d33; font-size: 13px; vertical-align: top; }
  th { color: #9aa0a6; font-weight: 600; }
  tr.now { background: #1d3a24; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin-right: 6px; }
  .badge-episode { background: #2b4a7a; }
  .badge-ad { background: #7a4a2b; }
  .badge-bumper { background: #4a2b7a; }
  .badge-off_air { background: #333; }
  button { background: #2a2d33; color: #e8e8e8; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 12px; }
  button:hover { background: #3a3d43; }
  .nav { margin-bottom: 12px; }
  .edit-box { margin-top: 6px; padding: 6px; background: #1a1c20; border-radius: 4px; display: none; }
  .edit-box input, .edit-box select { background: #14161a; color: #e8e8e8; border: 1px solid #444; padding: 3px; }
  .result { padding: 3px 0; cursor: pointer; }
  .result:hover { color: #7ab8ff; }
</style>
"""

DASHBOARD_JS = """
<script>
function toggleEdit(rowId) {
  var box = document.getElementById('edit-' + rowId);
  box.style.display = box.style.display === 'block' ? 'none' : 'block';
}
async function searchCatalog(rowId) {
  var type = document.getElementById('type-' + rowId).value;
  var q = document.getElementById('q-' + rowId).value;
  var resp = await fetch('/api/catalog?type=' + type + '&q=' + encodeURIComponent(q));
  var data = await resp.json();
  var list = document.getElementById('results-' + rowId);
  list.innerHTML = '';
  data.items.forEach(function(item) {
    var div = document.createElement('div');
    div.className = 'result';
    div.textContent = item.label;
    div.onclick = function() { applyReplace(rowId, type, item.id); };
    list.appendChild(div);
  });
}
async function applyReplace(rowId, type, itemId) {
  var resp = await fetch('/api/replace', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: rowId, item_type: type, item_id: itemId}),
  });
  var data = await resp.json();
  if (data.ok) { location.reload(); } else { alert(data.error); }
}
async function deleteRow(rowId) {
  if (!confirm('Удалить этот элемент из сетки?')) return;
  var resp = await fetch('/api/delete', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: rowId}),
  });
  var data = await resp.json();
  if (data.ok) { location.reload(); } else { alert(data.error); }
}
</script>
"""


def current_broadcast_date(now_utc: datetime) -> date:
    """Which broadcast day "now" belongs to - the day doesn't roll over at
    midnight, it rolls over at 10:00 MSK (see scheduler.py)."""
    msk_now = utc_to_msk(now_utc)
    if msk_now.time() < OFF_AIR_END:
        return msk_now.date() - timedelta(days=1)
    return msk_now.date()


def _row_html(conn: sqlite3.Connection, row: sqlite3.Row, is_now: bool) -> str:
    start_msk = utc_to_msk(datetime.fromisoformat(row["start_time"])).strftime("%H:%M:%S")
    item_type = row["item_type"]
    label = describe_item(conn, row)
    editable = item_type != "off_air" and row["status"] == "scheduled"
    actions = ""
    if editable:
        actions = f"""
        <button onclick="toggleEdit({row['id']})">Заменить</button>
        <button onclick="deleteRow({row['id']})">Удалить</button>
        <div class="edit-box" id="edit-{row['id']}">
          <select id="type-{row['id']}">
            <option value="episode" {"selected" if item_type == "episode" else ""}>эпизод</option>
            <option value="ad" {"selected" if item_type == "ad" else ""}>реклама</option>
            <option value="bumper" {"selected" if item_type == "bumper" else ""}>заставка</option>
          </select>
          <input type="text" id="q-{row['id']}" placeholder="поиск...">
          <button onclick="searchCatalog({row['id']})">Найти</button>
          <div id="results-{row['id']}"></div>
        </div>
        """
    return f"""
    <tr class="{'now' if is_now else ''}">
      <td>{start_msk}</td>
      <td><span class="badge badge-{item_type}">{item_type}</span></td>
      <td>{label}{actions}</td>
    </tr>
    """


def _now_page(conn: sqlite3.Connection, now_utc: datetime) -> str:
    current, upcoming = get_now_and_next(conn, now_utc, count=8)
    current_html = (
        f'<p style="color:#8a8f96">Сейчас ничего не идёт по расписанию '
        f'(сетка ещё не сгенерирована на этот момент).</p>'
        if current is None
        else f'<table><tr><th>Время (МСК)</th><th>Тип</th><th>Что идёт</th></tr>{_row_html(conn, current, is_now=True)}</table>'
    )
    upcoming_body = "".join(_row_html(conn, r, is_now=False) for r in upcoming)
    upcoming_html = (
        f'<h2 style="font-size:14px;margin:20px 0 8px;color:#9aa0a6">Дальше</h2>'
        f'<table><tr><th>Время (МСК)</th><th>Тип</th><th>Что идёт</th></tr>{upcoming_body}</table>'
        if upcoming
        else ""
    )
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
    <meta http-equiv="refresh" content="30">
    <title>Сейчас в эфире</title>{PAGE_STYLE}</head><body>
    <h1>Сейчас в эфире</h1>
    <div class="nav"><a href="/epg">Полная сетка (EPG)</a></div>
    {current_html}
    {upcoming_html}
    </body></html>"""


def _epg_page(conn: sqlite3.Connection, broadcast_date: date) -> str:
    rows = get_day_schedule(conn, broadcast_date)
    current, _ = get_now_and_next(conn, datetime.now(timezone.utc), count=1)
    # Only actually highlights something if "now" falls within this rendered
    # day - harmless no-op when browsing a different day.
    now_id = current["id"] if current else None

    body = "".join(_row_html(conn, r, is_now=(r["id"] == now_id)) for r in rows)
    prev_day = (broadcast_date - timedelta(days=1)).isoformat()
    next_day = (broadcast_date + timedelta(days=1)).isoformat()
    empty_notice = "" if rows else "<p>Нет сгенерированной сетки на этот день.</p>"
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
    <title>EPG {broadcast_date.isoformat()}</title>{PAGE_STYLE}{DASHBOARD_JS}</head><body>
    <h1>Сетка вещания — {broadcast_date.isoformat()}</h1>
    <div class="nav">
      <a href="/">Сейчас в эфире</a> &nbsp;|&nbsp;
      <a href="/epg?date={prev_day}">&larr; {prev_day}</a> &nbsp;
      <a href="/epg?date={next_day}">{next_day} &rarr;</a>
    </div>
    {empty_notice}
    <table><tr><th>Время (МСК)</th><th>Тип</th><th>Что идёт</th></tr>{body}</table>
    </body></html>"""


def _make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

        def _connect(self) -> sqlite3.Connection:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

        def _send_json(self, payload: dict, status: int = 200) -> None:
            self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            conn = self._connect()
            try:
                if parsed.path == "/":
                    self._send_html(_now_page(conn, datetime.now(timezone.utc)))
                elif parsed.path == "/epg":
                    date_str = qs.get("date", [None])[0]
                    broadcast_date = date.fromisoformat(date_str) if date_str else current_broadcast_date(datetime.now(timezone.utc))
                    self._send_html(_epg_page(conn, broadcast_date))
                elif parsed.path == "/api/now":
                    current, upcoming = get_now_and_next(conn, datetime.now(timezone.utc))
                    self._send_json(
                        {
                            "current": {"id": current["id"], "label": describe_item(conn, current)} if current else None,
                            "upcoming": [{"id": r["id"], "label": describe_item(conn, r)} for r in upcoming],
                        }
                    )
                elif parsed.path == "/api/catalog":
                    item_type = qs.get("type", [""])[0]
                    query = qs.get("q", [""])[0]
                    results = search_catalog(conn, item_type, query)
                    items = []
                    for r in results:
                        if item_type == "episode":
                            label = f"{r['series_name']} S{r['season']:02d}E{r['episode']:02d} - {r['title']}"
                        else:
                            label = r["file_path"]
                        items.append({"id": r["id"], "label": label})
                    self._send_json({"items": items})
                else:
                    self._send(404, "text/plain; charset=utf-8", b"not found")
            finally:
                conn.close()

        def do_POST(self):
            conn = self._connect()
            try:
                body = self._read_json_body()
                if self.path == "/api/replace":
                    replace_item(conn, int(body["id"]), body["item_type"], int(body["item_id"]))
                    self._send_json({"ok": True})
                elif self.path == "/api/delete":
                    delete_item(conn, int(body["id"]))
                    self._send_json({"ok": True})
                else:
                    self._send(404, "text/plain; charset=utf-8", b"not found")
            except (ValueError, KeyError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            finally:
                conn.close()

    return Handler


def start_server(db_path: Path, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(db_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
