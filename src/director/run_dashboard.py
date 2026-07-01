"""CLI: keeps the operator dashboard (now-playing + EPG) HTTP server running.

Usage:
    .venv/Scripts/python.exe -m director.run_dashboard
"""

import time

from director.config import Config
from director.dashboard_server import start_server


def main() -> None:
    config = Config.load()
    start_server(config.db_path, config.dashboard_port)
    print(f"Dashboard listening on http://127.0.0.1:{config.dashboard_port}/ (Ctrl+C to stop)")

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
