"""CLI entry point: (re)scan the configured media folders into the catalog DB.

Usage:
    .venv/Scripts/python.exe -m director.scan_library
"""

from pathlib import Path

from director import db
from director.config import Config
from director.scanner import ScanStats, scan_flat_root, scan_series_root


def classify_ad(path: Path) -> str | None:
    """Used only when ads_root and bumpers_root are the same folder: a file
    only counts as an ad if it isn't named like one of the bumper kinds."""
    name = path.stem.lower()
    if name.startswith(("ad-in", "ad-out", "bumper")):
        return None
    return "general"


def classify_bumper(path: Path) -> str | None:
    """Counterpart to classify_ad for the shared-folder case."""
    name = path.stem.lower()
    if name.startswith("ad-in"):
        return "ad_in"
    if name.startswith("ad-out"):
        return "ad_out"
    if name.startswith("ad-block"):
        return None
    return "interstitial"


def apply_rotation_modes(conn, random_series: list[str]) -> None:
    """Curation call, not something derived from the files: series named in
    random_series air in random rerun order, everything else stays
    sequential (the default - correct for premieres/serialized shows)."""
    conn.execute("UPDATE series SET rotation_mode = 'sequential'")
    if random_series:
        placeholders = ",".join("?" * len(random_series))
        conn.execute(f"UPDATE series SET rotation_mode = 'random' WHERE name IN ({placeholders})", random_series)
    conn.commit()


def _report(label: str, stats: ScanStats) -> None:
    print(f"{label}: +{stats.added} added, {stats.updated} updated, "
          f"{stats.unchanged} unchanged, {stats.missing} now missing")
    for err in stats.errors:
        print(f"  ! {err}")


def main() -> None:
    config = Config.load()
    conn = db.connect(config.db_path)

    _report("series", scan_series_root(conn, config.series_root, config.active_series))
    apply_rotation_modes(conn, config.random_rotation_series)

    shared_folder = config.ads_root == config.bumpers_root
    ad_classifier = classify_ad if shared_folder else None
    bumper_classifier = classify_bumper if shared_folder else None

    _report("ads", scan_flat_root(conn, config.ads_root, "ads", "category", ad_classifier))
    _report("bumpers", scan_flat_root(conn, config.bumpers_root, "bumpers", "kind", bumper_classifier))

    conn.close()


if __name__ == "__main__":
    main()
