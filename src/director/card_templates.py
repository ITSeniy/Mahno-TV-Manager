"""HTML templates for continuity cards (720x480, early-2000s infotainment look).

Design lives here so it can be tweaked without touching render plumbing. Each
function returns a full standalone HTML document; Playwright screenshots it at
720x480 and ffmpeg turns the still(s) into a clip. ntsc-rs adds the analog
grime on top, so these stay clean and legible - the vibe comes from the signal
chain, not from faux-distressing the markup.
"""

CARD_WIDTH = 720
CARD_HEIGHT = 480

_BASE_CSS = f"""
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {CARD_WIDTH}px; height: {CARD_HEIGHT}px; overflow: hidden; }}
  body {{
    font-family: Tahoma, 'Trebuchet MS', Arial, sans-serif;
    color: #f4f4ff;
    background: linear-gradient(160deg, #101a4a 0%, #1c2f7a 55%, #0a1030 100%);
    padding: 26px 34px;
    display: flex; flex-direction: column;
  }}
  .header {{
    font-size: 34px; font-weight: bold; letter-spacing: 2px;
    text-transform: uppercase; color: #ffe14d;
    text-shadow: 2px 2px 0 #00000066;
    border-bottom: 4px solid #ffe14d; padding-bottom: 10px; margin-bottom: 18px;
    display: flex; justify-content: space-between; align-items: baseline;
  }}
  .header .sub {{ font-size: 20px; color: #cfd6ff; letter-spacing: 1px; }}
  .rows {{ flex: 1; display: flex; flex-direction: column; justify-content: flex-start; gap: 2px; }}
  .row {{ display: flex; align-items: baseline; font-size: 30px; line-height: 1.28; }}
  .row .t {{ color: #7fe0ff; font-weight: bold; width: 132px; flex: none; }}
  .row .v {{ color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .footer {{ margin-top: 16px; font-size: 18px; color: #aab4ee; letter-spacing: 1px; }}
"""


def _page(body_html: str, extra_css: str = "") -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_BASE_CSS}{extra_css}</style></head><body>{body_html}</body></html>"


def _rows(items: list[tuple[str, str]]) -> str:
    return "".join(f"<div class='row'><span class='t'>{t}</span><span class='v'>{_esc(v)}</span></div>" for t, v in items)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def epg_day_html(page_items: list[tuple[str, str]], page_index: int, page_count: int, date_label: str) -> str:
    counter = f"{page_index + 1}/{page_count}" if page_count > 1 else ""
    body = (
        f"<div class='header'>ПРОГРАММА ПЕРЕДАЧ<span class='sub'>{_esc(date_label)} &nbsp; {counter}</span></div>"
        f"<div class='rows'>{_rows(page_items)}</div>"
        "<div class='footer'>ХОРОШЕГО ДНЯ • ОСТАВАЙТЕСЬ С НАМИ</div>"
    )
    return _page(body)


def epg_next_html(items: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>ДАЛЕЕ В ЭФИРЕ</div>"
        f"<div class='rows'>{_rows(items)}</div>"
        "<div class='footer'>НЕ ПЕРЕКЛЮЧАЙТЕ</div>"
    )
    return _page(body)


def weather_html(lines: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>ПОГОДА<span class='sub'>ПО РОССИИ</span></div>"
        f"<div class='rows'>{_rows(lines)}</div>"
        "<div class='footer'>ПРОГНОЗ НА ЗАВТРА</div>"
    )
    return _page(body)


def currency_html(rows: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>КУРС ВАЛЮТ<span class='sub'>ЦБ РФ</span></div>"
        f"<div class='rows'>{_rows(rows)}</div>"
        "<div class='footer'>ПО ДАННЫМ НА ЗАВТРА</div>"
    )
    return _page(body)


def horoscope_html(items: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>ГОРОСКОП<span class='sub'>НА ЗАВТРА</span></div>"
        f"<div class='rows'>{_rows(items)}</div>"
        "<div class='footer'>ЗВЁЗДЫ СОВЕТУЮТ ОСТАВАТЬСЯ С НАМИ</div>"
    )
    return _page(body)


def clock_html(time_label: str) -> str:
    extra = """
      .clock { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
      .clock .time { font-size: 132px; font-weight: bold; color: #ffe14d; letter-spacing: 4px; text-shadow: 3px 3px 0 #00000066; }
      .clock .label { font-size: 26px; letter-spacing: 4px; color: #cfd6ff; margin-top: 8px; }
    """
    body = f"<div class='clock'><div class='time'>{_esc(time_label)}</div><div class='label'>МОСКОВСКОЕ ВРЕМЯ</div></div>"
    return _page(body, extra)
