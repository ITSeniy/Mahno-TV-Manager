"""Pre-renders library files through ntsc-rs-cli.exe.

ntsc-rs has no live/streaming mode - only whole-file offline rendering (a
~12-minute episode took ~2m15s to process in testing, i.e. no way to run it
synchronously in the middle of a live poll loop without stalling playout for
minutes). So the approach is: render every catalog file once, ahead of time,
into a cache directory, and have playout prefer the cached copy over the raw
source file. render_library.py (the batch driver) is the only thing that
ever calls render_file/ensure_rendered; playout.py only ever does the cheap
is_render_valid() read-only check, never renders on the fly.

Anything not yet rendered (new files, or mid-migration on first run - a full
~126h library took roughly a day to get through in testing) falls back to
the raw file. To avoid airing that raw file completely undegraded, the live
obs-retro-effects NTSC/VHS filters (see vhs_effect.py) stay in the OBS
filter chain and get toggled on specifically for not-yet-rendered items
(see obs_playout.apply_item) - off when ntsc-rs already did the job, on as
a fallback when it hasn't yet, so nothing ever airs completely pristine.
"""

import subprocess
import sqlite3
from pathlib import Path

_TABLES = {"episode": "episodes", "ad": "ads", "bumper": "bumpers"}


def cache_path_for(cache_dir: Path, item_type: str, item_id: int) -> Path:
    # Keyed by DB id rather than mirroring the original filename: source
    # filenames are full of characters (unicode, brackets, quotes) that are
    # awkward to round-trip safely through a subprocess command line and a
    # filesystem path on Windows, and the id is already a stable unique key.
    return cache_dir / item_type / f"{item_id}.mp4"


def is_render_valid(row: sqlite3.Row) -> bool:
    """True if row has a pre-rendered copy that's still current (exists on
    disk and was rendered from the file's current mtime/size - if the source
    file changed since, the cached render is stale and must be redone)."""
    rendered_path = row["rendered_path"]
    if not rendered_path:
        return False
    if not Path(rendered_path).exists():
        return False
    return row["rendered_source_mtime"] == row["file_mtime"] and row["rendered_source_size"] == row["file_size"]


def render_file(cli_path: Path, settings_path: Path, input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # ntsc-rs-cli emits some diagnostics (e.g. a GStreamer plugin-load
    # warning) as Windows-locale-encoded text, not UTF-8 - decoding those
    # strictly crashes subprocess's internal reader thread mid-run. errors=
    # "replace" keeps stderr readable for diagnostics without that crash.
    result = subprocess.run(
        [str(cli_path), "-i", str(input_path), "-o", str(output_path), "-p", str(settings_path), "-y"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ntsc-rs-cli failed for {input_path} (exit {result.returncode}): {result.stderr.strip()}")


def ensure_rendered(
    conn: sqlite3.Connection,
    item_type: str,
    row: sqlite3.Row,
    cli_path: Path,
    settings_path: Path,
    cache_dir: Path,
) -> Path:
    """Renders row's source file if needed (missing or stale cache) and
    records the result in the DB. Only called from the batch pre-render
    script - never from the live playout loop, since a single render can
    take minutes."""
    if is_render_valid(row):
        # Trust the DB's recorded path rather than recomputing cache_path_for
        # fresh - they normally agree, but if cache_dir ever changed between
        # runs the recorded path is the one that's actually known-valid.
        return Path(row["rendered_path"])

    table = _TABLES[item_type]
    output_path = cache_path_for(cache_dir, item_type, row["id"])
    input_path = Path(row["file_path"])
    render_file(cli_path, settings_path, input_path, output_path)

    conn.execute(
        f"UPDATE {table} SET rendered_path = ?, rendered_source_mtime = ?, rendered_source_size = ? WHERE id = ?",
        (str(output_path), row["file_mtime"], row["file_size"], row["id"]),
    )
    conn.commit()
    return output_path
