"""CLI: pre-renders the media library through ntsc-rs-cli.exe.

Safe to interrupt (Ctrl+C) and re-run - already-rendered, unchanged files
are skipped (see ntsc_render.is_render_valid), so this only ever does the
work still outstanding. A single file's render failure is logged and
skipped rather than aborting the whole run, since one corrupt/exotic source
file shouldn't take down a run that can take the better part of a day for
a full library.

Usage:
    .venv/Scripts/python.exe -m director.render_library
"""

from director import db
from director.config import Config
from director.ntsc_render import ensure_rendered, is_render_valid

_TABLES = {"episode": "episodes", "ad": "ads", "bumper": "bumpers", "reel": "reels"}


def _render_table(conn, config: Config, item_type: str) -> None:
    table = _TABLES[item_type]
    rows = conn.execute(f"SELECT * FROM {table} WHERE missing = 0 AND duration_seconds IS NOT NULL").fetchall()
    total = len(rows)
    rendered = skipped = failed = 0

    for i, row in enumerate(rows, start=1):
        if is_render_valid(row):
            skipped += 1
            continue
        try:
            ensure_rendered(conn, item_type, row, config.ntsc_rs_cli_path, config.ntsc_rs_settings_path, config.ntsc_render_cache_dir)
            rendered += 1
            print(f"[{item_type} {i}/{total}] rendered: {row['file_path']}")
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort an hours-long batch run
            failed += 1
            print(f"[{item_type} {i}/{total}] FAILED: {row['file_path']}: {exc}")

    print(f"{item_type}: {rendered} rendered, {skipped} already up to date, {failed} failed (of {total})")


def main() -> None:
    config = Config.load()
    missing = [
        name
        for name, value in (
            ("ntsc_rs_cli_path", config.ntsc_rs_cli_path),
            ("ntsc_rs_settings_path", config.ntsc_rs_settings_path),
            ("ntsc_render_cache_dir", config.ntsc_render_cache_dir),
        )
        if value is None
    ]
    if missing:
        raise SystemExit(f"config.json is missing required field(s) for rendering: {', '.join(missing)}")

    conn = db.connect(config.db_path)
    for item_type in ("episode", "ad", "bumper", "reel"):
        _render_table(conn, config, item_type)
    conn.close()


if __name__ == "__main__":
    main()
