"""CLI: renders pending continuity cards through the HTML -> ffmpeg -> ntsc-rs
pipeline. Meant to run during the profilaktika window (05:00-10:00 MSK) for the
upcoming broadcast day, but safe to run any time.

Idempotent and interrupt-safe like render_library: already-rendered cards are
skipped, and one card's failure is logged (its row marked 'failed') without
aborting the batch. The schedule must already be generated - cards read their
EPG content out of program_log.

Usage:
    .venv/Scripts/python.exe -m director.render_cards
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from director import card_content, db
from director.card_render import is_card_render_valid, render_card
from director.config import Config, Secrets

REQUIRED_CONFIG = ("ntsc_rs_cli_path", "ntsc_rs_settings_path", "ntsc_render_cache_dir")
CARD_KEEP_HOURS = 30  # keep the current broadcast day (10:00->05:00 = 19h) plus margin


def missing_render_config(config: Config) -> list[str]:
    return [name for name in REQUIRED_CONFIG if getattr(config, name) is None]


def purge_expired_cards(conn: sqlite3.Connection, now_utc: datetime, keep_hours: int = CARD_KEEP_HOURS) -> int:
    """Cards are date-specific (a given day's EPG, a given clock time) and
    regenerated daily, so once a card's slot is well in the past its file is
    dead weight. Deletes the rendered file and the row. The past program_log
    rows that referenced it are already played/skipped and never resolved
    again, so dropping the card row is safe."""
    cutoff = (now_utc - timedelta(hours=keep_hours)).isoformat()
    expired = conn.execute("SELECT id, rendered_path FROM cards WHERE slot_start < ?", (cutoff,)).fetchall()
    for row in expired:
        if row["rendered_path"]:
            try:
                Path(row["rendered_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        conn.execute("DELETE FROM cards WHERE id = ?", (row["id"],))
    conn.commit()
    return len(expired)


def render_pending_cards(
    conn: sqlite3.Connection, config: Config, secrets: Secrets, now_utc: datetime
) -> tuple[int, int, int, int]:
    """Renders every not-yet-rendered card whose slot is still in the future.
    Idempotent and failure-isolating (mirrors render_library). Returns
    (rendered, skipped, failed, total). Shared by the CLI and the profilaktika
    job so both behave identically."""
    purge_expired_cards(conn, now_utc)

    # One forecast for the day (idempotent per MSK date), reused by every weather card.
    weather = card_content.refresh_weather(conn, secrets.gemini_api_keys, now_utc)

    rows = conn.execute(
        "SELECT * FROM cards WHERE status != 'rendered' AND slot_start >= ? ORDER BY slot_start",
        (now_utc.isoformat(),),
    ).fetchall()
    total = len(rows)
    rendered = skipped = failed = 0

    for i, card in enumerate(rows, start=1):
        if is_card_render_valid(card):
            skipped += 1
            continue
        try:
            render_card(conn, card, config, weather)
            rendered += 1
            print(f"[card {i}/{total}] rendered {card['kind']} @ {card['slot_start']} ({card['target_seconds']:.0f}s)")
        except Exception as exc:  # noqa: BLE001 - one bad card must not abort the batch
            failed += 1
            print(f"[card {i}/{total}] FAILED {card['kind']} @ {card['slot_start']}: {exc}")

    return rendered, skipped, failed, total


def main() -> None:
    config = Config.load()
    secrets = Secrets.load()
    missing = missing_render_config(config)
    if missing:
        raise SystemExit(f"config.json is missing required field(s) for rendering: {', '.join(missing)}")

    conn = db.connect(config.db_path)
    rendered, skipped, failed, total = render_pending_cards(conn, config, secrets, datetime.now(timezone.utc))
    print(f"cards: {rendered} rendered, {skipped} already up to date, {failed} failed (of {total})")
    conn.close()


if __name__ == "__main__":
    main()
