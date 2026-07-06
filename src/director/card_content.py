"""Content behind continuity cards: the day's EPG projection and the weather
forecast pool.

EPG data is just a projection of program_log (reusing dashboard_data), so a
card never invents a schedule - it shows exactly what's booked. Weather mirrors
ticker_content: one idempotent Gemini generation per MSK day with a static
fallback, so a flaky API never stalls the render job.
"""

import json
import re
import sqlite3
from datetime import date, datetime

from director import gemini_client
from director.dashboard_data import PROGRAM_ITEM_TYPES, describe_item, get_day_schedule, program_items_after
from director.timeutil import utc_to_msk

WEATHER_PROMPT = """\
Ты — редактор прогноза погоды российского телеканала начала 2000-х годов.
Сгенерируй прогноз погоды на завтра для 8 городов России. Требования:
- каждый город на отдельной строке в формате: ГОРОД +NN ОПИСАНИЕ
  (температура со знаком, например -5 или +21; описание 1-3 слова);
- ЗАГЛАВНЫМИ БУКВАМИ, без нумерации, без markdown, без кавычек;
- города: МОСКВА, САНКТ-ПЕТЕРБУРГ, ЕКАТЕРИНБУРГ, НОВОСИБИРСК, СОЧИ, КАЗАНЬ,
  ВЛАДИВОСТОК, МУРМАНСК.
"""

WEATHER_FALLBACK = [
    "МОСКВА +19 ПЕРЕМЕННАЯ ОБЛАЧНОСТЬ",
    "САНКТ-ПЕТЕРБУРГ +15 НЕБОЛЬШОЙ ДОЖДЬ",
    "ЕКАТЕРИНБУРГ +12 ОБЛАЧНО",
    "НОВОСИБИРСК +17 ЯСНО",
    "СОЧИ +26 СОЛНЕЧНО",
    "КАЗАНЬ +18 ПЕРЕМЕННАЯ ОБЛАЧНОСТЬ",
    "ВЛАДИВОСТОК +14 ТУМАН",
    "МУРМАНСК +8 ДОЖДЬ",
]

_STRIP_PREFIX = re.compile(r"^[\-\*•\d\.\)]+\s*")


def _msk_date(now_utc: datetime) -> str:
    return utc_to_msk(now_utc).date().isoformat()


def parse_weather(raw_text: str) -> list[str]:
    lines = []
    for raw_line in raw_text.splitlines():
        line = _STRIP_PREFIX.sub("", raw_line.strip()).strip(" \"'")
        if line:
            lines.append(line)
    return lines


def get_current_weather(conn: sqlite3.Connection) -> list[str]:
    row = conn.execute("SELECT forecast_json FROM weather_pools ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return WEATHER_FALLBACK
    return json.loads(row["forecast_json"])


def refresh_weather(conn: sqlite3.Connection, api_keys: list[str], now_utc: datetime) -> list[str]:
    """Idempotent per MSK calendar day, exactly like ticker_content.refresh_pool."""
    today = _msk_date(now_utc)
    existing = conn.execute(
        "SELECT forecast_json FROM weather_pools WHERE msk_date = ? ORDER BY id DESC LIMIT 1", (today,)
    ).fetchone()
    if existing is not None:
        return json.loads(existing["forecast_json"])

    try:
        raw = gemini_client.generate_text(api_keys, WEATHER_PROMPT)
        lines = parse_weather(raw)
        if not lines:
            raise RuntimeError("Gemini returned no usable weather lines")
        source = "gemini"
    except Exception as exc:  # noqa: BLE001 - any failure must fall back, not crash the render job
        print(f"weather: Gemini generation failed ({exc}), using fallback forecast")
        lines = WEATHER_FALLBACK
        source = "fallback"

    conn.execute(
        "INSERT INTO weather_pools (generated_at, msk_date, source, forecast_json) VALUES (?, ?, ?, ?)",
        (now_utc.isoformat(), today, source, json.dumps(lines, ensure_ascii=False)),
    )
    conn.commit()
    return lines


def _fmt_time(iso: str) -> str:
    return utc_to_msk(datetime.fromisoformat(iso)).strftime("%H:%M")


def day_programmes(conn: sqlite3.Connection, broadcast_date: date) -> list[tuple[str, str]]:
    """(MSK start time, label) for every programme booked that broadcast day -
    the ads/bumpers/cards in between are collapsed out, the way a printed guide
    only lists the shows."""
    out: list[tuple[str, str]] = []
    for row in get_day_schedule(conn, broadcast_date):
        if row["item_type"] in PROGRAM_ITEM_TYPES:
            out.append((_fmt_time(row["start_time"]), describe_item(conn, row)))
    return out


def epg_day_pages(conn: sqlite3.Connection, broadcast_date: date, per_page: int = 8) -> list[list[tuple[str, str]]]:
    """The day's programmes split into fixed-size pages, one PNG per page."""
    progs = day_programmes(conn, broadcast_date)
    if not progs:
        return [[]]
    return [progs[i : i + per_page] for i in range(0, len(progs), per_page)]


def epg_next_items(conn: sqlite3.Connection, slot_start_iso: str, count: int = 3) -> list[tuple[str, str]]:
    """(MSK start time, label) for the next few programmes - the "Далее" card."""
    return [(_fmt_time(r["start_time"]), describe_item(conn, r)) for r in program_items_after(conn, slot_start_iso, count)]
