"""Local HTTP server exposing the ticker overlay page and its JSON feed.

OBS's browser source hits this over http:// instead of loading a static
file, so the crawl content can be refreshed live (the page polls
/ticker.json) without anyone having to reload the source in OBS - the
spikes/ticker/ POC couldn't do this because file:// pages can't fetch()
local JSON without hitting CORS restrictions.
"""

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from director.ticker_content import get_current_pool

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Ticker</title>
<style>
  html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; }
  .ticker-bar {
    position: fixed; left: 0; bottom: 0; width: 100%; height: 60px;
    background: linear-gradient(to bottom, #003366, #0055aa 60%, #003366);
    border-top: 3px solid #ffcc00;
    display: flex; align-items: center;
    box-shadow: 0 -4px 10px rgba(0, 0, 0, 0.5);
    font-family: Arial, Helvetica, sans-serif;
  }
  .ticker-track {
    display: flex; white-space: nowrap;
    animation-name: scroll; animation-timing-function: linear; animation-iteration-count: infinite;
    animation-duration: var(--duration, 30s);
  }
  .ticker-item {
    display: inline-flex; align-items: center;
    color: #fff; font-weight: bold; font-size: 28px; text-shadow: 2px 2px 2px #000;
    padding-right: 80px;
  }
  .ticker-item::before { content: "\\25CF"; color: #ffcc00; margin-right: 20px; font-size: 16px; }
  @keyframes scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
</style>
</head>
<body>
  <div class="ticker-bar"><div class="ticker-track" id="track"></div></div>
  <script>
    const REFRESH_MS = 60000;

    function render(lines) {
      const track = document.getElementById("track");
      track.innerHTML = "";
      for (let rep = 0; rep < 2; rep++) {
        for (const line of lines) {
          const span = document.createElement("span");
          span.className = "ticker-item";
          span.textContent = line;
          track.appendChild(span);
        }
      }
      const totalChars = lines.join("").length;
      const duration = Math.max(20, totalChars * 0.25);
      track.style.setProperty("--duration", duration + "s");
    }

    async function refresh() {
      try {
        const resp = await fetch("/ticker.json", { cache: "no-store" });
        const data = await resp.json();
        render(data.lines || []);
      } catch (e) {
        // keep showing whatever's already on screen if a fetch fails
      }
    }

    refresh();
    setInterval(refresh, REFRESH_MS);
  </script>
</body>
</html>
"""


def _make_handler(db_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass  # run_ticker prints its own status lines; keep this quiet

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
            elif self.path == "/ticker.json":
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                lines = get_current_pool(conn)
                conn.close()
                body = json.dumps({"lines": lines}, ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start_server(db_path: Path, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(db_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
