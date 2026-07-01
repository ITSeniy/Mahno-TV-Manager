"""CLI: generate the program log for N upcoming broadcast days.

Usage:
    .venv/Scripts/python.exe -m director.generate_schedule --days 3 [--start YYYY-MM-DD]
"""

import argparse
from datetime import date

from director import db
from director.config import Config
from director.scheduler import generate_schedule


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--start", type=str, default=None, help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start) if args.start else date.today()

    config = Config.load()
    conn = db.connect(config.db_path)

    results = generate_schedule(conn, start_date, args.days)
    for day, count in results.items():
        status = f"{count} items" if count else "уже сгенерировано, пропущено"
        print(f"{day.isoformat()}: {status}")

    conn.close()


if __name__ == "__main__":
    main()
