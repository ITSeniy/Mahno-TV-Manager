"""CLI entry point: (re)scan the configured media folders into the catalog DB.

Usage:
    .venv/Scripts/python.exe -m director.scan_library
"""

from director import db
from director.config import Config
from director.scanner import ScanStats, scan_flat_root, scan_series_root


def _report(label: str, stats: ScanStats) -> None:
    print(f"{label}: +{stats.added} added, {stats.updated} updated, "
          f"{stats.unchanged} unchanged, {stats.missing} now missing")
    for err in stats.errors:
        print(f"  ! {err}")


def main() -> None:
    config = Config.load()
    conn = db.connect(config.db_path)

    _report("series", scan_series_root(conn, config.series_root))
    _report("ads", scan_flat_root(conn, config.ads_root, "ads", "category"))
    _report("bumpers", scan_flat_root(conn, config.bumpers_root, "bumpers", "kind"))

    conn.close()


if __name__ == "__main__":
    main()
