"""CLI: print the generated program log for a broadcast day as an EPG-style table.

Usage:
    .venv/Scripts/python.exe -m director.show_schedule --date YYYY-MM-DD
"""

import argparse
import sqlite3
from datetime import date, datetime, timedelta

from director import db
from director.blocks import OFF_AIR_END
from director.config import Config
from director.timeutil import combine_msk, utc_to_msk


def _label(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    item_type = row["item_type"]
    item_id = row["item_id"]
    if item_type == "off_air":
        return "ТЕХПЕРЕРЫВ"
    if item_type == "episode":
        ep = conn.execute(
            "SELECT e.season, e.episode, e.title, s.name FROM episodes e "
            "JOIN series s ON s.id = e.series_id WHERE e.id = ?",
            (item_id,),
        ).fetchone()
        return f"{ep['name']} S{ep['season']:02d}E{ep['episode']:02d} - {ep['title']}"
    if item_type == "ad":
        ad = conn.execute("SELECT file_path FROM ads WHERE id = ?", (item_id,)).fetchone()
        return f"[РЕКЛАМА] {ad['file_path']}"
    if item_type == "bumper":
        bumper = conn.execute("SELECT file_path FROM bumpers WHERE id = ?", (item_id,)).fetchone()
        return f"[ЗАСТАВКА] {bumper['file_path']}"
    return item_type


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True, help="broadcast day, YYYY-MM-DD")
    args = parser.parse_args()

    broadcast_date = date.fromisoformat(args.date)

    config = Config.load()
    conn = db.connect(config.db_path)

    day_start = combine_msk(broadcast_date, OFF_AIR_END).isoformat()
    day_end = combine_msk(broadcast_date + timedelta(days=1), OFF_AIR_END).isoformat()

    rows = conn.execute(
        "SELECT * FROM program_log WHERE start_time >= ? AND start_time < ? ORDER BY start_time",
        (day_start, day_end),
    ).fetchall()

    if not rows:
        print(f"Нет сгенерированной сетки на {broadcast_date.isoformat()}. Запусти director.generate_schedule.")
        return

    for row in rows:
        start_msk = utc_to_msk(datetime.fromisoformat(row["start_time"]))
        block = f"[{row['block_name']}]" if row["block_name"] else ""
        event = f" ({row['event_name']})" if row["event_name"] else ""
        print(f"{start_msk.strftime('%H:%M:%S')} {block}{event} {_label(conn, row)}")

    conn.close()


if __name__ == "__main__":
    main()
