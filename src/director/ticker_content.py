"""Generates the daily pool of ticker headlines via Gemini, caches it, and
falls back to a static list if generation fails for any reason (all keys/
models exhausted, network error, empty/unusable response, ...).
"""

import json
import re
import sqlite3
from datetime import datetime, timedelta

from director import gemini_client
from director.blocks import OFF_AIR_END
from director.timeutil import combine_msk, utc_to_msk

BASE_PROMPT = """\
Ты — редактор бегущей строки российского развлекательного телеканала начала
2000-х годов (эстетика 2000-2005: анонсы передач, погода, дешёвая реклама,
дворовый юмор, ностальгия по видеокассетам и пейджерам).

Сгенерируй 20 коротких фраз для бегущей строки. Требования:
- каждая фраза на отдельной строке, ЗАГЛАВНЫМИ БУКВАМИ, без нумерации/markdown/кавычек;
- длина каждой фразы 40-90 символов;
- формат строки: НАЗВАНИЕ::текст (если фраза про конкретную передачу из списка
  ниже, НАЗВАНИЕ строго дословно из списка) или ::текст (общая фраза).
"""


def _todays_shows(conn: sqlite3.Connection, now_utc: datetime) -> list[str]:
    """Distinct series airing on the current MSK broadcast day - fed into the
    prompt so the ticker can reference real shows."""
    day = utc_to_msk(now_utc).date()
    start = combine_msk(day, OFF_AIR_END).isoformat()
    end = combine_msk(day + timedelta(days=1), OFF_AIR_END).isoformat()
    rows = conn.execute(
        "SELECT DISTINCT s.name FROM program_log pl JOIN episodes e ON e.id = pl.item_id "
        "JOIN series s ON s.id = e.series_id "
        "WHERE pl.item_type = 'episode' AND pl.start_time >= ? AND pl.start_time < ? ORDER BY s.name",
        (start, end),
    ).fetchall()
    return [r["name"] for r in rows]


def _build_prompt(shows: list[str]) -> str:
    if shows:
        return (
            BASE_PROMPT
            + "\nПередачи сегодня: " + ", ".join(shows)
            + ".\nСделай примерно половину фраз с привязкой к этим передачам, остальные общие."
        )
    return BASE_PROMPT + "\nСписок передач пуст — все фразы общие (::текст)."

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
        raw = gemini_client.generate_text(api_keys, _build_prompt(_todays_shows(conn, now_utc)))
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


def current_programme_name(conn: sqlite3.Connection, now_utc: datetime) -> str | None:
    """Series (or film title) airing right now, or None outside the schedule."""
    now = now_utc.isoformat()
    row = conn.execute(
        "SELECT item_type, item_id FROM program_log WHERE start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1",
        (now, now),
    ).fetchone()
    if row is None:
        return None
    if row["item_type"] == "episode":
        r = conn.execute(
            "SELECT s.name FROM episodes e JOIN series s ON s.id = e.series_id WHERE e.id = ?", (row["item_id"],)
        ).fetchone()
        return r["name"] if r else None
    if row["item_type"] in ("film", "reel"):
        r = conn.execute(
            "SELECT f.title FROM reels rl JOIN films f ON f.id = rl.film_id WHERE rl.id = ?", (row["item_id"],)
        ).fetchone()
        return r["title"] if r else None
    return None


def current_ticker_lines(conn: sqlite3.Connection, now_utc: datetime) -> list[str]:
    """The pool filtered to the current programme: lines tagged for the show on
    air now plus untagged/generic lines, with the 'НАЗВАНИЕ::' tag stripped."""
    pool = get_current_pool(conn)
    current = current_programme_name(conn, now_utc)
    current_lc = current.lower() if current else None

    out: list[str] = []
    for line in pool:
        tag, sep, text = line.partition("::")
        if not sep:
            out.append(line)  # legacy/fallback line with no tag = generic
        elif tag.strip() == "":
            out.append(text.strip())  # explicit generic ::text
        elif current_lc is not None and tag.strip().lower() == current_lc:
            out.append(text.strip())  # tagged for the show on air now
    # If every line was tagged for other shows, fall back to showing them all.
    return out or [(line.partition("::")[2].strip() or line) for line in pool]
