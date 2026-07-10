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
  (температура со знаком, например -5 или +21; описание — ОДНО короткое слово:
  ЯСНО, СОЛНЕЧНО, ОБЛАЧНО, ПЕРЕМЕННО, ДОЖДЬ, ГРОЗА, ТУМАН, СНЕГ);
- ЗАГЛАВНЫМИ БУКВАМИ, без нумерации, без markdown, без кавычек;
- города: МОСКВА, САНКТ-ПЕТЕРБУРГ, ЕКАТЕРИНБУРГ, НОВОСИБИРСК, СОЧИ, КАЗАНЬ,
  ВЛАДИВОСТОК, МУРМАНСК.
"""

WEATHER_FALLBACK = [
    "МОСКВА +19 ПЕРЕМЕННО",
    "САНКТ-ПЕТЕРБУРГ +15 ДОЖДЬ",
    "ЕКАТЕРИНБУРГ +12 ОБЛАЧНО",
    "НОВОСИБИРСК +17 ЯСНО",
    "СОЧИ +26 СОЛНЕЧНО",
    "КАЗАНЬ +18 ПЕРЕМЕННО",
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


# --- Generic service-text pool (currency, horoscope, sms) ------------------
# Same idempotent-per-MSK-day pattern as refresh_weather, generalized by kind so
# new service content reuses one table (service_pools) and one code path.

def refresh_service_pool(
    conn: sqlite3.Connection,
    kind: str,
    prompt: str,
    fallback: list[str],
    api_keys: list[str],
    now_utc: datetime,
) -> list[str]:
    today = _msk_date(now_utc)
    existing = conn.execute(
        "SELECT payload_json FROM service_pools WHERE kind = ? AND msk_date = ? ORDER BY id DESC LIMIT 1",
        (kind, today),
    ).fetchone()
    if existing is not None:
        return json.loads(existing["payload_json"])

    try:
        raw = gemini_client.generate_text(api_keys, prompt)
        lines = parse_weather(raw)  # generic line stripper - fine for any line-per-item pool
        if not lines:
            raise RuntimeError("Gemini returned no usable lines")
        source = "gemini"
    except Exception as exc:  # noqa: BLE001 - any failure must fall back, not crash the render/ticker job
        print(f"{kind}: Gemini generation failed ({exc}), using fallback")
        lines = fallback
        source = "fallback"

    conn.execute(
        "INSERT INTO service_pools (kind, generated_at, msk_date, source, payload_json) VALUES (?, ?, ?, ?, ?)",
        (kind, now_utc.isoformat(), today, source, json.dumps(lines, ensure_ascii=False)),
    )
    conn.commit()
    return lines


def get_service_pool(conn: sqlite3.Connection, kind: str, fallback: list[str]) -> list[str]:
    row = conn.execute(
        "SELECT payload_json FROM service_pools WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
    ).fetchone()
    return json.loads(row["payload_json"]) if row is not None else fallback


CURRENCY_PROMPT = """\
Ты — редактор блока курсов валют российского телеканала начала 2000-х.
Выдай курс ЦБ РФ на завтра для 4 валют, каждая на отдельной строке в формате
ВАЛЮТА|Х РУБ ХХ КОП (через вертикальную черту), ЗАГЛАВНЫМИ, без нумерации и
markdown. Значения реалистичные для 2002–2005:
ДОЛЛАР США (~30 руб), ЕВРО (~35 руб), ФУНТ СТЕРЛИНГОВ (~48 руб),
ШВЕЙЦАРСКИЙ ФРАНК (~23 руб).
"""

CURRENCY_FALLBACK = [
    "ДОЛЛАР США|30 РУБ 15 КОП",
    "ЕВРО|35 РУБ 40 КОП",
    "ФУНТ СТЕРЛИНГОВ|48 РУБ 90 КОП",
    "ШВЕЙЦАРСКИЙ ФРАНК|23 РУБ 10 КОП",
]

HOROSCOPE_PROMPT = """\
Ты — редактор гороскопа российского развлекательного телеканала начала 2000-х.
Выдай короткий шуточный гороскоп на завтра для 12 знаков зодиака, каждый на
отдельной строке в формате ЗНАК|фраза (через вертикальную черту, фраза 15–55
символов), ЗАГЛАВНЫМИ знак, без нумерации и markdown. Дворовый юмор, ностальгия
по нулевым. Знаки: ОВЕН, ТЕЛЕЦ, БЛИЗНЕЦЫ, РАК, ЛЕВ, ДЕВА, ВЕСЫ, СКОРПИОН,
СТРЕЛЕЦ, КОЗЕРОГ, ВОДОЛЕЙ, РЫБЫ.
"""

HOROSCOPE_FALLBACK = [
    "ОВЕН|не переключайте канал — будет удача",
    "ТЕЛЕЦ|день хорош для повтора любимых серий",
    "БЛИЗНЕЦЫ|пришлите привет в эфир — сбудется",
    "РАК|берегите видеокассеты от солнца",
    "ЛЕВ|вас ждёт приятный звонок на пейджер",
    "ДЕВА|разберите наконец полку с дисками",
    "ВЕСЫ|equilibrium: смотрите мультики в меру",
    "СКОРПИОН|не спорьте с младшим братом о пульте",
    "СТРЕЛЕЦ|удачный день для прогулки во дворе",
    "КОЗЕРОГ|дела пойдут в гору после обеда",
    "ВОДОЛЕЙ|звёзды советуют дождаться вечера",
    "РЫБЫ|сегодня всё сложится само собой",
]


def refresh_currency(conn: sqlite3.Connection, api_keys: list[str], now_utc: datetime) -> list[str]:
    return refresh_service_pool(conn, "currency", CURRENCY_PROMPT, CURRENCY_FALLBACK, api_keys, now_utc)


def get_currency(conn: sqlite3.Connection) -> list[str]:
    return get_service_pool(conn, "currency", CURRENCY_FALLBACK)


def refresh_horoscope(conn: sqlite3.Connection, api_keys: list[str], now_utc: datetime) -> list[str]:
    return refresh_service_pool(conn, "horoscope", HOROSCOPE_PROMPT, HOROSCOPE_FALLBACK, api_keys, now_utc)


def get_horoscope(conn: sqlite3.Connection) -> list[str]:
    return get_service_pool(conn, "horoscope", HOROSCOPE_FALLBACK)


SMS_PROMPT = """\
Ты — редактор ночного SMS-чата российского развлекательного телеканала начала
2000-х. Выдай 25 коротких сообщений от зрителей, каждое на отдельной строке в
формате ИМЯ, ГОРОД: текст (текст 10–55 символов), без нумерации и markdown.
Приветы в эфир, дворовый юмор, ностальгия по нулевым (пейджеры, кассеты, дискотека).
"""

SMS_FALLBACK = [
    "ВАСЯ, ТАМБОВ: ПРИВЕТ ВСЕМ КТО НЕ СПИТ!!!",
    "ЛЕНА, ОМСК: КТО СМОТРИТ КАНАЛ В ТАКОЙ ЧАС?)))",
    "ДИМОН, КАЗАНЬ: РУЛИТ ЭТОТ КАНАЛ, ПАЦАНЫ",
    "НАСТЯ, 15 ЛЕТ: ПЕРЕДАЙТЕ ПРИВЕТ 9 «Б»",
    "АНОНИМ: СКИНЬТЕ НОМЕР ПЕЙДЖЕРА))",
    "МАКС, ПЕРМЬ: СПОКОЙНОЙ НОЧИ ВСЕМ ЗРИТЕЛЯМ",
    "ОКСАНА: ОБОЖАЮ ЭТОТ ЧАТ, СИЖУ ДО УТРА",
    "СЕРЫЙ, РОСТОВ: КТО С ДВОРА — ОТЗОВИТЕСЬ",
]


def refresh_sms(conn: sqlite3.Connection, api_keys: list[str], now_utc: datetime) -> list[str]:
    return refresh_service_pool(conn, "sms", SMS_PROMPT, SMS_FALLBACK, api_keys, now_utc)


def get_sms(conn: sqlite3.Connection) -> list[str]:
    return get_service_pool(conn, "sms", SMS_FALLBACK)


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


PROMO_TEASERS = [
    "НЕ ПРОПУСТИ!",
    "ТОЛЬКО У НАС!",
    "ОСТАВАЙСЯ НА КАНАЛЕ!",
    "ЖДЁМ ТЕБЯ У ЭКРАНОВ!",
    "СМОТРИ ОБЯЗАТЕЛЬНО!",
]


def upcoming_promo(conn: sqlite3.Connection, after_iso: str, ahead: int = 3) -> tuple[str, str] | None:
    """A programme a few slots ahead to hype on a "скоро на канале" card -
    (MSK time, label). Reaches past the immediate next so the promo teases
    something not already on the "Далее" card. None if nothing's upcoming."""
    rows = program_items_after(conn, after_iso, ahead)
    if not rows:
        return None
    row = rows[-1]
    return _fmt_time(row["start_time"]), describe_item(conn, row)
