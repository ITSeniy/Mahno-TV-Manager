"""Walks the configured folders and (re)populates the SQLite catalog.

Convention (no pre-existing library assumed, adjust as the real layout emerges):
  series_root/<Series Name>/**/<file with optional SxxEyy or NxM markers>
  ads_root/[<category>/]<file>
  bumpers_root/[<kind>/]<file>

Files whose mtime+size match the last scan are not re-probed with ffprobe.
Files that disappear from disk are kept in the DB (so play_history stays
valid) but flagged missing=1.
"""

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from director.media_probe import probe

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".ts", ".m4v", ".wmv", ".flv"}

_SEASON_EP_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[Ee](\d{1,3})"),
    re.compile(r"(\d{1,2})[xX](\d{1,3})"),
]
_LONE_NUMBER = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")


@dataclass
class ScanStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ScanStats") -> None:
        self.added += other.added
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.missing += other.missing
        self.errors.extend(other.errors)


def iter_video_files(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            yield path


def parse_season_episode(filename: str) -> tuple[int, int | None]:
    # Strip the extension first so a digit inside it (mp4, m4v, h264...) can't
    # be mistaken for an episode number.
    stem = Path(filename).stem
    for pattern in _SEASON_EP_PATTERNS:
        m = pattern.search(stem)
        if m:
            return int(m.group(1)), int(m.group(2))
    m = _LONE_NUMBER.search(stem)
    if m:
        return 1, int(m.group(1))
    return 1, None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _needs_reprobe(row: sqlite3.Row | None, mtime: float, size: int) -> bool:
    if row is None:
        return True
    return row["file_mtime"] != mtime or row["file_size"] != size


def scan_series_root(conn: sqlite3.Connection, series_root: Path) -> ScanStats:
    stats = ScanStats()
    if not series_root.is_dir():
        stats.errors.append(f"series_root not found: {series_root}")
        return stats

    for series_dir in sorted(p for p in series_root.iterdir() if p.is_dir()):
        series_id = _upsert_series(conn, series_dir.name, series_dir)
        found_paths: set[str] = set()

        parsed = [(f, *parse_season_episode(f.name)) for f in iter_video_files(series_dir)]

        known_per_season: dict[int, set[int]] = defaultdict(set)
        for _, season, episode in parsed:
            if episode is not None:
                known_per_season[season].add(episode)
        next_per_season: dict[int, int] = {}

        for file_path, season, episode in parsed:
            if episode is None:
                n = next_per_season.get(season, 1)
                while n in known_per_season[season]:
                    n += 1
                known_per_season[season].add(n)
                next_per_season[season] = n + 1
                episode = n

            found_paths.add(str(file_path.resolve()))
            try:
                _upsert_episode(conn, series_id, season, episode, file_path, stats)
            except Exception as exc:  # ffprobe failures, permission errors, etc.
                stats.errors.append(f"{file_path}: {exc}")

        stats.missing += _mark_missing(conn, "episodes", "series_id = ?", (series_id,), found_paths)

    conn.commit()
    return stats


def scan_flat_root(conn: sqlite3.Connection, root: Path, table: str, kind_column: str) -> ScanStats:
    assert table in ("ads", "bumpers")
    stats = ScanStats()
    if not root.is_dir():
        stats.errors.append(f"{table} root not found: {root}")
        return stats

    found_paths: set[str] = set()
    for file_path in iter_video_files(root):
        kind = file_path.parent.name if file_path.parent != root else None
        found_paths.add(str(file_path.resolve()))
        try:
            _upsert_flat_item(conn, table, kind_column, kind, file_path, stats)
        except Exception as exc:
            stats.errors.append(f"{file_path}: {exc}")

    stats.missing += _mark_missing(conn, table, "1=1", (), found_paths)
    conn.commit()
    return stats


def _upsert_series(conn: sqlite3.Connection, name: str, root_path: Path) -> int:
    conn.execute(
        "INSERT INTO series (name, root_path) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET root_path = excluded.root_path",
        (name, str(root_path.resolve())),
    )
    return conn.execute("SELECT id FROM series WHERE name = ?", (name,)).fetchone()["id"]


def _upsert_episode(
    conn: sqlite3.Connection,
    series_id: int,
    season: int,
    episode: int,
    file_path: Path,
    stats: ScanStats,
) -> None:
    resolved = str(file_path.resolve())
    stat = file_path.stat()
    row = conn.execute("SELECT * FROM episodes WHERE file_path = ?", (resolved,)).fetchone()

    if not _needs_reprobe(row, stat.st_mtime, stat.st_size):
        conn.execute(
            "UPDATE episodes SET missing = 0, scanned_at = ? WHERE file_path = ?",
            (_now(), resolved),
        )
        stats.unchanged += 1
        return

    info = probe(file_path)
    conn.execute(
        """
        INSERT INTO episodes
            (series_id, season, episode, title, file_path, duration_seconds,
             width, height, file_mtime, file_size, scanned_at, missing)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(file_path) DO UPDATE SET
            series_id = excluded.series_id,
            season = excluded.season,
            episode = excluded.episode,
            title = excluded.title,
            duration_seconds = excluded.duration_seconds,
            width = excluded.width,
            height = excluded.height,
            file_mtime = excluded.file_mtime,
            file_size = excluded.file_size,
            scanned_at = excluded.scanned_at,
            missing = 0
        """,
        (
            series_id, season, episode, file_path.stem, resolved,
            info.duration_seconds, info.width, info.height,
            stat.st_mtime, stat.st_size, _now(),
        ),
    )
    stats.updated += 1 if row is not None else 0
    stats.added += 1 if row is None else 0


def _upsert_flat_item(
    conn: sqlite3.Connection,
    table: str,
    kind_column: str,
    kind: str | None,
    file_path: Path,
    stats: ScanStats,
) -> None:
    resolved = str(file_path.resolve())
    stat = file_path.stat()
    row = conn.execute(f"SELECT * FROM {table} WHERE file_path = ?", (resolved,)).fetchone()

    if not _needs_reprobe(row, stat.st_mtime, stat.st_size):
        conn.execute(
            f"UPDATE {table} SET missing = 0, scanned_at = ? WHERE file_path = ?",
            (_now(), resolved),
        )
        stats.unchanged += 1
        return

    info = probe(file_path)
    conn.execute(
        f"""
        INSERT INTO {table}
            (file_path, {kind_column}, duration_seconds, width, height, file_mtime, file_size, scanned_at, missing)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(file_path) DO UPDATE SET
            {kind_column} = excluded.{kind_column},
            duration_seconds = excluded.duration_seconds,
            width = excluded.width,
            height = excluded.height,
            file_mtime = excluded.file_mtime,
            file_size = excluded.file_size,
            scanned_at = excluded.scanned_at,
            missing = 0
        """,
        (resolved, kind, info.duration_seconds, info.width, info.height, stat.st_mtime, stat.st_size, _now()),
    )
    stats.updated += 1 if row is not None else 0
    stats.added += 1 if row is None else 0


def _mark_missing(
    conn: sqlite3.Connection,
    table: str,
    where: str,
    where_params: tuple,
    found_paths: set[str],
) -> int:
    rows = conn.execute(f"SELECT id, file_path FROM {table} WHERE {where}", where_params).fetchall()
    stale_ids = [r["id"] for r in rows if r["file_path"] not in found_paths]
    if stale_ids:
        placeholders = ",".join("?" * len(stale_ids))
        conn.execute(f"UPDATE {table} SET missing = 1 WHERE id IN ({placeholders})", stale_ids)
    return len(stale_ids)
