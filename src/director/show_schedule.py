"""CLI: print the generated program log for a broadcast day as an EPG-style table.

Usage:
    .venv/Scripts/python.exe -m director.show_schedule --date YYYY-MM-DD
"""

import argparse
from datetime import date, datetime

from director import db
from director.config import Config
from director.dashboard_data import describe_item, get_day_schedule
from director.timeutil import utc_to_msk


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True, help="broadcast day, YYYY-MM-DD")
    args = parser.parse_args()

    broadcast_date = date.fromisoformat(args.date)

    config = Config.load()
    conn = db.connect(config.db_path)

    rows = get_day_schedule(conn, broadcast_date)

    if not rows:
        print(f"Нет сгенерированной сетки на {broadcast_date.isoformat()}. Запусти director.generate_schedule.")
        return

    for row in rows:
        start_msk = utc_to_msk(datetime.fromisoformat(row["start_time"]))
        block = f"[{row['block_name']}]" if row["block_name"] else ""
        event = f" ({row['event_name']})" if row["event_name"] else ""
        print(f"{start_msk.strftime('%H:%M:%S')} {block}{event} {describe_item(conn, row)}")

    conn.close()


if __name__ == "__main__":
    main()
