"""CLI: the playout controller. Polls wall-clock time against the generated
program_log and drives OBS to match, forever.

Usage:
    OBS_WS_PASSWORD=... .venv/Scripts/python.exe -m director.run_playout
"""

import time
from datetime import datetime, timezone

from director import db
from director.config import Config
from director.obs_client import get_client
from director.obs_playout import ON_AIR_SCENE, apply_item, ensure_scenes
from director.overlays import ensure_logo, ensure_ticker_source
from director.playout import advance_status, find_current_row, resolve_media_path

POLL_INTERVAL_SECONDS = 3


def main() -> None:
    config = Config.load()
    conn = db.connect(config.db_path)
    client = get_client()
    ensure_scenes(client)

    if config.logo_path and config.logo_path.exists():
        ensure_logo(client, ON_AIR_SCENE, str(config.logo_path))
    else:
        print("logo_path не задан или файл не найден - оверлей лого пропущен")

    ensure_ticker_source(client, ON_AIR_SCENE, f"http://127.0.0.1:{config.ticker_port}/")

    current_row_id: int | None = None
    print("Playout controller started (Ctrl+C to stop).")

    while True:
        now = datetime.now(timezone.utc)
        advance_status(conn, current_row_id, now)
        row = find_current_row(conn, now)

        if row is None:
            if current_row_id is not None:
                print(f"{now.isoformat()}: нет сгенерированной сетки на текущий момент - ухожу на off-air")
            apply_item(client, "off_air", None)
            current_row_id = None
        elif row["id"] != current_row_id:
            path = resolve_media_path(conn, row)
            print(f"{now.isoformat()}: -> {row['item_type']} #{row['item_id']} [{row['block_name']}] {path or ''}")
            apply_item(client, row["item_type"], path)
            current_row_id = row["id"]

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
