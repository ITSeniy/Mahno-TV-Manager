"""CLI entry point: (re)scan the configured media folders into the catalog DB.

Usage:
    .venv/Scripts/python.exe -m director.scan_library
"""

from pathlib import Path

from director import db
from director.config import Config
from director.scanner import ScanStats, scan_films_root, scan_flat_root, scan_series_root


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


def apply_categories(conn, series_categories: dict[str, list[str]]) -> None:
    """Curation call like apply_rotation_modes: unlisted series stay 'cartoon',
    each listed name gets its category (drives dayparting and themed blocks -
    e.g. adult-animation only airs in the Adult Swim night block)."""
    conn.execute("UPDATE series SET category = 'cartoon'")
    for category, names in series_categories.items():
        if not names:
            continue
        placeholders = ",".join("?" * len(names))
        conn.execute(f"UPDATE series SET category = ? WHERE name IN ({placeholders})", (category, *names))
    conn.commit()


def apply_film_categories(conn, film_categories: dict[str, list[str]]) -> None:
    """Counterpart to apply_categories for films (keyed by title, default 'film')."""
    conn.execute("UPDATE films SET category = 'film'")
    for category, titles in film_categories.items():
        if not titles:
            continue
        placeholders = ",".join("?" * len(titles))
        conn.execute(f"UPDATE films SET category = ? WHERE title IN ({placeholders})", (category, *titles))
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
    apply_categories(conn, config.series_categories)

    if config.films_root is not None:
        _report("films", scan_films_root(conn, config.films_root, config.active_films))
        apply_film_categories(conn, config.film_categories)

    shared_folder = config.ads_root == config.bumpers_root
    ad_classifier = classify_ad if shared_folder else None
    bumper_classifier = classify_bumper if shared_folder else None

    _report("ads", scan_flat_root(conn, config.ads_root, "ads", "category", ad_classifier))
    _report("bumpers", scan_flat_root(conn, config.bumpers_root, "bumpers", "kind", bumper_classifier))

    conn.close()


if __name__ == "__main__":
    main()
