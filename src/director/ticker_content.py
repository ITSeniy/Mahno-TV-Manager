"""Generates the daily pool of ticker headlines via Gemini, caches it, and
falls back to a static list if generation fails for any reason (all keys/
models exhausted, network error, empty/unusable response, ...).
"""

import json
import re
import sqlite3
from datetime import datetime

from director import gemini_client
from director.timeutil import utc_to_msk

PROMPT = """\
Ты — редактор бегущей строки российского развлекательного телеканала для детей и
подростков начала 2000-х годов (эстетика 2000-2005: анонсы мультсериалов, погода,
дешёвая реклама, дворовый юмор, ностальгия по видеокассетам и пейджерам).

Сгенерируй 20 коротких фраз для бегущей строки. Требования:
- каждая фраза на отдельной строке, без нумерации, без markdown, без кавычек;
- длина каждой фразы 40-90 символов;
- ЗАГЛАВНЫМИ БУКВАМИ;
- в стиле того времени: анонсы мультсериалов, погода, конкурсы, объявления,
  реклама товаров начала 2000-х, приветы в эфир.
"""

STATIC_FALLBACK = [
    "СМОТРИТЕ НОВЫЕ СЕРИИ ЛЮБИМЫХ МУЛЬТФИЛЬМОВ КАЖДЫЙ ДЕНЬ НА НАШЕМ КАНАЛЕ",
    "ПОГОДА НА ЗАВТРА: ПЕРЕМЕННАЯ ОБЛАЧНОСТЬ, МЕСТАМИ ДОЖДЬ, ОДЕВАЙТЕСЬ ТЕПЛЕЕ",
    "ПРИСЫЛАЙТЕ ПРИВЕТЫ В ЭФИР ДЛЯ ДРУЗЕЙ И ОДНОКЛАССНИКОВ",
    "НЕ ПЕРЕКЛЮЧАЙТЕ — ДАЛЬШЕ БУДЕТ ЕЩЁ ИНТЕРЕСНЕЕ",
    "СПАСИБО, ЧТО ОСТАЁТЕСЬ С НАМИ",
]

_STRIP_PREFIX = re.compile(r"^[\-\*•\d\.\)]+\s*")


def parse_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in raw_text.splitlines():
        line = _STRIP_PREFIX.sub("", raw_line.strip()).strip(" \"'")
        if line:
            lines.append(line)
    return lines


def _msk_date(now_utc: datetime) -> str:
    return utc_to_msk(now_utc).date().isoformat()


def get_current_pool(conn: sqlite3.Connection) -> list[str]:
    row = conn.execute("SELECT lines_json FROM ticker_pools ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return STATIC_FALLBACK
    return json.loads(row["lines_json"])


def refresh_pool(conn: sqlite3.Connection, api_keys: list[str], now_utc: datetime) -> list[str]:
    """Idempotent per MSK calendar day: if today's pool already exists,
    returns it without calling Gemini again."""
    today = _msk_date(now_utc)
    existing = conn.execute(
        "SELECT lines_json FROM ticker_pools WHERE msk_date = ? ORDER BY id DESC LIMIT 1", (today,)
    ).fetchone()
    if existing is not None:
        return json.loads(existing["lines_json"])

    try:
        raw = gemini_client.generate_text(api_keys, PROMPT)
        lines = parse_lines(raw)
        if not lines:
            raise RuntimeError("Gemini returned no usable lines")
        source = "gemini"
    except Exception as exc:  # noqa: BLE001 - any failure here must fall back, not crash the channel
        print(f"ticker: Gemini generation failed ({exc}), using fallback lines")
        lines = STATIC_FALLBACK
        source = "fallback"

    conn.execute(
        "INSERT INTO ticker_pools (generated_at, msk_date, source, lines_json) VALUES (?, ?, ?, ?)",
        (now_utc.isoformat(), today, source, json.dumps(lines, ensure_ascii=False)),
    )
    conn.commit()
    return lines
