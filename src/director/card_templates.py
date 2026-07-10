"""HTML templates for continuity cards (720x480, early-2000s REN-TV look).

Each function returns a full standalone HTML document. Playwright screenshots it
with a TRANSPARENT background (only the glossy bars/badges/text are opaque);
card_render then composites that foreground over the animated "cloth" loop and
runs ntsc-rs. So the page carries no background of its own - the flowing satin
comes from the composite, the analog grime from the signal chain.
"""

CARD_WIDTH = 720
CARD_HEIGHT = 480

# Zodiac glyphs for the one-sign-per-page horoscope card.
SIGN_GLYPHS = {
    "ОВЕН": "♈", "ТЕЛЕЦ": "♉", "БЛИЗНЕЦЫ": "♊", "РАК": "♋",
    "ЛЕВ": "♌", "ДЕВА": "♍", "ВЕСЫ": "♎", "СКОРПИОН": "♏",
    "СТРЕЛЕЦ": "♐", "КОЗЕРОГ": "♑", "ВОДОЛЕЙ": "♒", "РЫБЫ": "♓",
}

_BASE_CSS = f"""
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {CARD_WIDTH}px; height: {CARD_HEIGHT}px; overflow: hidden; }}
  body {{
    font-family: Tahoma, 'Trebuchet MS', Arial, sans-serif; color: #f3f4ff;
    background: transparent;  /* the cloth loop is composited underneath */
    padding: 24px 30px; display: flex; flex-direction: column;
  }}
  .header {{
    align-self: center; display: flex; gap: 18px; align-items: baseline;
    letter-spacing: 4px; text-transform: uppercase; color: #eaf0ff; font-weight: bold;
    font-size: 34px; text-shadow: 1px 1px 4px #0008; margin: 4px 0 22px;
  }}
  .header .sub {{ font-size: 19px; color: #cfe0ff; letter-spacing: 3px; }}
  .footer {{
    align-self: center; margin-top: 18px; color: #cfe0ff; font-size: 17px; letter-spacing: 4px;
    text-transform: uppercase; text-shadow: 1px 1px 3px #0008; opacity: .92;
  }}

  .rows {{ flex: 1; display: flex; flex-direction: column; justify-content: center; gap: var(--g, 16px); }}
  .row {{ display: flex; align-items: stretch; height: var(--bh, 64px); }}

  .badge {{
    position: relative; z-index: 2; display: flex; align-items: center; justify-content: center;
    min-width: 88px; padding: 0 10px 0 14px; margin-right: -12px;
    background: linear-gradient(180deg, #2a3d86, #0f1b47); border: 1px solid #3a58c0; border-radius: 999px;
    box-shadow: inset 0 2px 3px rgba(255,255,255,.28), 0 3px 6px rgba(0,0,0,.4); color: #fff; font-weight: bold;
  }}
  .badge .hh {{ font-size: 37px; text-shadow: 1px 1px 2px #0009; }}
  .badge .mm {{
    font-size: 17px; background: #e23c3c; border-radius: 4px; padding: 1px 5px; margin-left: 4px;
    align-self: flex-start; margin-top: 9px; box-shadow: 0 1px 2px #0007;
  }}
  .badge.word {{ min-width: 108px; padding: 0 16px; font-size: 22px; letter-spacing: 2px; }}

  .bar {{
    flex: 1; display: flex; align-items: center; gap: 14px; padding-left: 32px; padding-right: 18px;
    background: linear-gradient(180deg, rgba(30,55,120,.62) 0%, rgba(12,26,70,.86) 45%, rgba(8,18,52,.92) 100%);
    border-radius: 6px; border-top: 1px solid rgba(150,180,255,.5);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.18), 0 4px 10px rgba(0,0,0,.35);
    color: #fff; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; font-size: 24px;
    text-shadow: 1px 1px 3px #000a; white-space: nowrap; overflow: hidden;
  }}
  .bar.plain {{ padding-left: 22px; }}
  .bar.two {{ justify-content: space-between; }}
  .bar .l {{ color: #9fe0ff; }}
  .bar .v {{ color: #fff; overflow: hidden; text-overflow: ellipsis; }}

  .center {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 12px; }}
  .center .big {{ font-size: 150px; font-weight: bold; color: #ffe14d; letter-spacing: 6px; line-height: 1; text-shadow: 3px 3px 0 #00000066; }}
  .center .cap {{ font-size: 24px; letter-spacing: 6px; color: #dfe8ff; text-transform: uppercase; text-shadow: 1px 1px 3px #0009; }}
  .promo .when {{ font-size: 29px; font-weight: bold; color: #9fe0ff; letter-spacing: 3px; }}
  .promo .title {{
    max-width: 88%; font-size: 40px; font-weight: bold; color: #fff; text-transform: uppercase; line-height: 1.1;
    padding: 18px 24px; border-radius: 6px; border-top: 1px solid rgba(150,180,255,.5);
    background: linear-gradient(180deg, rgba(30,55,120,.62), rgba(8,18,52,.92));
    box-shadow: inset 0 1px 0 rgba(255,255,255,.18); text-shadow: 1px 1px 3px #000a;
  }}
  .promo .teaser {{ font-size: 26px; font-weight: bold; color: #ffe14d; letter-spacing: 4px; }}
  .horo {{ gap: 6px; }}
  .horo .glyph {{ font-size: 108px; line-height: 1; color: #ffe14d; text-shadow: 3px 3px 0 #00000055; }}
  .horo .sign {{ font-size: 46px; font-weight: bold; letter-spacing: 4px; color: #fff; text-transform: uppercase; text-shadow: 1px 1px 3px #0009; }}
  .horo .phrase {{ font-size: 26px; color: #ffe14d; max-width: 88%; text-shadow: 1px 1px 3px #0009; }}
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _page(body_html: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_BASE_CSS}</style></head><body>{body_html}</body></html>"


def _time_badge(hhmm: str) -> str:
    hh, _, mm = hhmm.partition(":")
    return f"<div class='badge'><span class='hh'>{_esc(hh)}</span><span class='mm'>{_esc(mm)}</span></div>"


def _epg_rows(items: list[tuple[str, str]]) -> str:
    return "".join(f"<div class='row'>{_time_badge(t)}<div class='bar'>{_esc(v)}</div></div>" for t, v in items)


def _two_col_rows(items: list[tuple[str, str]], bar_h: int, gap: int) -> str:
    inner = "".join(
        f"<div class='row'><div class='bar two plain'><span class='l'>{_esc(l)}</span><span class='v'>{_esc(v)}</span></div></div>"
        for l, v in items
    )
    return f"<div class='rows' style='--bh:{bar_h}px;--g:{gap}px'>{inner}</div>"


def epg_day_html(page_items: list[tuple[str, str]], page_index: int, page_count: int, date_label: str) -> str:
    counter = f"{page_index + 1}/{page_count}" if page_count > 1 else ""
    body = (
        f"<div class='header'>ПРОГРАММА ПЕРЕДАЧ<span class='sub'>{_esc(date_label)} {counter}</span></div>"
        f"<div class='rows' style='--bh:52px;--g:8px'>{_epg_rows(page_items)}</div>"
        "<div class='footer'>Хорошего дня · оставайтесь с нами</div>"
    )
    return _page(body)


def epg_next_html(items: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>СМОТРИТЕ</div>"
        f"<div class='rows' style='--bh:66px;--g:20px'>{_epg_rows(items)}</div>"
        "<div class='footer'>Не переключайте</div>"
    )
    return _page(body)


def weather_html(lines: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>ПОГОДА<span class='sub'>ПО РОССИИ</span></div>"
        + _two_col_rows(lines, 46, 8)
        + "<div class='footer'>Прогноз на завтра</div>"
    )
    return _page(body)


def currency_html(rows: list[tuple[str, str]]) -> str:
    body = (
        "<div class='header'>КУРС ВАЛЮТ<span class='sub'>ЦБ РФ</span></div>"
        + _two_col_rows(rows, 58, 12)
        + "<div class='footer'>По данным на завтра</div>"
    )
    return _page(body)


def horoscope_html(sign: str, phrase: str) -> str:
    """One zodiac sign per page (cycled across the card's pages), centered like
    the promo card - glyph + sign + phrase."""
    glyph = SIGN_GLYPHS.get(sign.upper().strip(), "★")
    body = (
        "<div class='header'>ГОРОСКОП<span class='sub'>НА ЗАВТРА</span></div>"
        f"<div class='center horo'><div class='glyph'>{glyph}</div>"
        f"<div class='sign'>{_esc(sign)}</div><div class='phrase'>{_esc(phrase)}</div></div>"
    )
    return _page(body)


def promo_html(title: str, when: str, teaser: str) -> str:
    body = (
        "<div class='header'>СКОРО НА КАНАЛЕ</div>"
        f"<div class='center promo'><div class='when'>{_esc(when)}</div>"
        f"<div class='title'>{_esc(title)}</div><div class='teaser'>{_esc(teaser)}</div></div>"
    )
    return _page(body)


def clock_html(time_label: str) -> str:
    body = f"<div class='center'><div class='big'>{_esc(time_label)}</div><div class='cap'>МОСКОВСКОЕ ВРЕМЯ</div></div>"
    return _page(body)
