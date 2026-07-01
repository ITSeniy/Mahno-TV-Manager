"""CLI: keeps the ticker HTTP server running and the daily Gemini pool fresh.

Usage:
    .venv/Scripts/python.exe -m director.run_ticker
"""

import time
from datetime import datetime, timezone

from director import db
from director.config import Config, Secrets
from director.ticker_content import refresh_pool
from director.ticker_server import start_server

CHECK_INTERVAL_SECONDS = 1800  # refresh_pool is idempotent per MSK day, so frequent checks are harmless


def main() -> None:
    config = Config.load()
    secrets = Secrets.load()
    conn = db.connect(config.db_path)

    start_server(config.db_path, config.ticker_port)
    print(f"Ticker server listening on http://127.0.0.1:{config.ticker_port}/ (Ctrl+C to stop)")

    while True:
        now = datetime.now(timezone.utc)
        lines = refresh_pool(conn, secrets.gemini_api_keys, now)
        print(f"{now.isoformat()}: ticker pool has {len(lines)} lines")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
