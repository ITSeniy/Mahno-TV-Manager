"""CLI: keeps the upcoming day's continuity cards rendered.

Runs as an always-on process under the supervisor, but only actually renders
during the profilaktika window (05:00-10:00 MSK) - that's the daily idle stretch
where the channel is off-air showing a test card anyway, so the CPU-heavy
Playwright + ntsc-rs passes never fight the live broadcast. Outside the window
it just idles. Rendering is idempotent, so repeated passes inside the window
only pick up whatever's still outstanding.

Usage:
    .venv/Scripts/python.exe -m director.run_card_renderer
"""

import time
from datetime import datetime, timezone

from director import db
from director.blocks import OFF_AIR_END, OFF_AIR_START
from director.config import Config, Secrets
from director.render_cards import missing_render_config, render_pending_cards
from director.timeutil import utc_to_msk

CHECK_INTERVAL_SECONDS = 1800  # passes are idempotent, so a lazy 30-min tick is plenty


def in_profilaktika_window(now_utc: datetime) -> bool:
    now_msk = utc_to_msk(now_utc).time()
    return OFF_AIR_START <= now_msk < OFF_AIR_END


def main() -> None:
    config = Config.load()
    secrets = Secrets.load()
    conn = db.connect(config.db_path)
    print("Card renderer started (renders only during 05:00-10:00 MSK profilaktika; Ctrl+C to stop).")

    while True:
        now = datetime.now(timezone.utc)
        missing = missing_render_config(config)
        if missing:
            print(f"{now.isoformat()}: card render disabled - config.json missing {', '.join(missing)}")
        elif in_profilaktika_window(now):
            rendered, skipped, failed, total = render_pending_cards(conn, config, secrets, now)
            print(f"{now.isoformat()}: cards pass - {rendered} rendered, {skipped} up to date, {failed} failed (of {total})")
        else:
            print(f"{now.isoformat()}: outside profilaktika window - skipping card render pass")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
