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

from director.card_content import get_sms
from director.ticker_content import get_current_pool

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Ticker</title>
<style>
  html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; height: 100%; }
  .ticker-bar {
    position: fixed; left: 0; bottom: 0; width: 100%; height: 100%;
    background: linear-gradient(to bottom, #003366, #0055aa 60%, #003366);
    border-top: 3px solid #ffcc00;
    box-sizing: border-box;
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
    color: #fff; font-weight: bold; text-shadow: 2px 2px 2px #000;
  }
  .ticker-item::before { content: "\\25CF"; color: #ffcc00; }
  @keyframes scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
</style>
</head>
<body>
  <div class="ticker-bar"><div class="ticker-track" id="track"></div></div>
  <script>
    // The bar fills whatever height OBS assigns this browser source (see
    // overlays.py's TICKER_HEIGHT_FRACTION) rather than a fixed pixel value -
    // a hardcoded CSS height here previously didn't match the OBS-side
    // viewport size, so the bottom-anchored bar had its top (and the top of
    // the text) silently clipped off. Font/marker/spacing scale off the
    // actual viewport height so this doesn't recur if that fraction changes.
    const REFRESH_MS = 60000;

    function render(lines) {
      const track = document.getElementById("track");
      track.innerHTML = "";

      const fontSize = Math.max(10, Math.round(window.innerHeight * 0.5));
      const gap = Math.round(fontSize * 2.5);
      const dotSize = Math.round(fontSize * 0.5);
      const dotMargin = Math.round(fontSize * 0.6);

      for (let rep = 0; rep < 2; rep++) {
        for (const line of lines) {
          const span = document.createElement("span");
          span.className = "ticker-item";
          span.textContent = line;
          span.style.fontSize = fontSize + "px";
          span.style.paddingRight = gap + "px";
          track.appendChild(span);
        }
      }

      const style = document.createElement("style");
      style.textContent = `.ticker-item::before { font-size: ${dotSize}px; margin-right: ${dotMargin}px; }`;
      document.head.appendChild(style);

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


# Full-screen night SMS-chat: viewer messages credits-roll up the screen under a
# "send SMS to 1121" header. OBS points the SMS_CHAT scene's browser source here;
# the schedule switches to that scene for the 04:00-05:00 sms_chat block.
SMS_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>SMS-чат</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden;
    font-family: Tahoma, "Trebuchet MS", Arial, sans-serif; color: #f4f4ff;
    background: linear-gradient(160deg, #101a4a 0%, #1c2f7a 55%, #0a1030 100%); }
  .head { position: fixed; top: 0; left: 0; right: 0; height: 15%;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(#1c2f7a, #101a4a); border-bottom: 3px solid #ffe14d;
    color: #ffe14d; font-weight: bold; letter-spacing: 2px; text-transform: uppercase;
    text-shadow: 2px 2px 0 rgba(0,0,0,0.4); z-index: 2; }
  .roll { position: absolute; top: 15%; left: 0; right: 0; bottom: 0; overflow: hidden; padding: 0 4%; }
  .track { display: flex; flex-direction: column; gap: 1.6%;
    animation-name: roll; animation-timing-function: linear; animation-iteration-count: infinite;
    animation-duration: var(--dur, 40s); }
  .msg { line-height: 1.25; text-shadow: 1px 1px 2px rgba(0,0,0,0.6); }
  .msg b { color: #7fe0ff; }
  @keyframes roll { from { transform: translateY(65%); } to { transform: translateY(-50%); } }
</style>
</head>
<body>
  <div class="head" id="head">&#9733; НОЧНОЙ ЧАТ &middot; ОТПРАВЬ SMS НА 1121 &#9733;</div>
  <div class="roll"><div class="track" id="track"></div></div>
  <script>
    const REFRESH_MS = 120000;
    function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function render(lines) {
      const track = document.getElementById("track");
      track.innerHTML = "";
      const fs = Math.max(12, Math.round(window.innerHeight * 0.045));
      document.getElementById("head").style.fontSize = Math.round(window.innerHeight * 0.05) + "px";
      for (let rep = 0; rep < 2; rep++) {
        for (const line of lines) {
          const div = document.createElement("div");
          div.className = "msg";
          div.style.fontSize = fs + "px";
          const i = line.indexOf(":");
          if (i > 0) { div.innerHTML = "<b>" + esc(line.slice(0, i + 1)) + "</b> " + esc(line.slice(i + 1)); }
          else { div.textContent = line; }
          track.appendChild(div);
        }
      }
      track.style.setProperty("--dur", Math.max(30, lines.length * 3) + "s");
    }
    async function refresh() {
      try { const r = await fetch("/sms.json", { cache: "no-store" }); render((await r.json()).lines || []); }
      catch (e) { /* keep the current roll on a failed fetch */ }
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
            elif self.path == "/sms":
                self._send(200, "text/html; charset=utf-8", SMS_PAGE.encode("utf-8"))
            elif self.path == "/ticker.json":
                self._send_feed(get_current_pool)
            elif self.path == "/sms.json":
                self._send_feed(get_sms)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def _send_feed(self, get_lines) -> None:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            lines = get_lines(conn)
            conn.close()
            body = json.dumps({"lines": lines}, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

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
