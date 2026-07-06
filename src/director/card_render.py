"""Renders one continuity card: HTML -> PNG(s) (Playwright) -> exact-length
clip with a music bed (ffmpeg) -> analog grime (ntsc-rs).

Only the batch driver (render_cards.py) calls render_card, and only during the
profilaktika window - never the live playout loop (a single card render spawns
a browser + two encodes, far too slow for the 3s poll). Playwright is imported
lazily so the rest of the director doesn't depend on a browser being installed.
"""

import re
import subprocess
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from director import card_content, card_templates, cards
from director.config import Config
from director.ntsc_render import cache_path_for, render_file
from director.timeutil import utc_to_msk

CARD_FPS = 25
_MONTHS = [
    "ЯНВАРЯ", "ФЕВРАЛЯ", "МАРТА", "АПРЕЛЯ", "МАЯ", "ИЮНЯ",
    "ИЮЛЯ", "АВГУСТА", "СЕНТЯБРЯ", "ОКТЯБРЯ", "НОЯБРЯ", "ДЕКАБРЯ",
]
_WEATHER_SPLIT = re.compile(r"^(.*?)\s*([+\-]?\d.*)$")


def is_card_render_valid(row: sqlite3.Row) -> bool:
    """A card is playable once the render job produced a file that's still on
    disk. Unlike library files there's no source mtime/size to compare - the
    card IS the generated artifact."""
    return row["status"] == "rendered" and bool(row["rendered_path"]) and Path(row["rendered_path"]).exists()


def _human_date(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1]}"


def _split_weather(line: str) -> tuple[str, str]:
    m = _WEATHER_SPLIT.match(line)
    return (m.group(1).strip(), m.group(2).strip()) if m else (line, "")


def card_html_pages(conn: sqlite3.Connection, card: sqlite3.Row, weather_lines: list[str]) -> list[str]:
    kind = card["kind"]
    if kind == cards.KIND_EPG_DAY:
        d = date.fromisoformat(card["msk_date"])
        pages = card_content.epg_day_pages(conn, d)
        label = _human_date(d)
        return [card_templates.epg_day_html(pg, i, len(pages), label) for i, pg in enumerate(pages)]
    if kind == cards.KIND_EPG_NEXT:
        items = card_content.epg_next_items(conn, card["slot_start"])
        return [card_templates.epg_next_html(items)]
    if kind == cards.KIND_WEATHER:
        rows = [_split_weather(line) for line in (weather_lines or card_content.WEATHER_FALLBACK)]
        return [card_templates.weather_html(rows)]
    if kind == cards.KIND_CLOCK:
        return [card_templates.clock_html(utc_to_msk(datetime.fromisoformat(card["slot_start"])).strftime("%H:%M"))]
    return [card_templates.clock_html("")]  # unknown kind -> a neutral plate rather than a crash


def _render_htmls_to_pngs(htmls: list[str], out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright  # lazy: only the render job needs a browser

    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": card_templates.CARD_WIDTH, "height": card_templates.CARD_HEIGHT},
                device_scale_factor=1,
            )
            for i, html in enumerate(htmls):
                page.set_content(html, wait_until="load")
                png = out_dir / f"page{i}.png"
                page.screenshot(path=str(png))
                paths.append(png)
        finally:
            browser.close()
    return paths


def _run_ffmpeg(cmd: list[str], what: str, produced: Path) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not produced.exists():
        raise RuntimeError(f"ffmpeg failed {what} (exit {result.returncode}): {result.stderr.strip()[-800:]}")


def _build_video(pngs: list[Path], target_seconds: float, music_path: Path | None, out_mp4: Path) -> None:
    """Stills -> a clip of exactly target_seconds, each page shown for an equal
    share, with a looped music bed (or silence). The music is baked in so the
    live CHOW tape VST on program_player wow/flutters it like everything else.

    Each page becomes a real constant-frame-rate clip via `-loop 1`: concat-
    demuxing the PNGs directly yields a single-frame stream (one coded frame
    with an 8s presentation duration) that ntsc-rs hangs on indefinitely."""
    per = target_seconds / len(pngs)
    parts: list[Path] = []
    for i, png in enumerate(pngs):
        part = out_mp4.parent / f"part{i}.mp4"
        _run_ffmpeg(
            ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-t", f"{per:.3f}", "-r", str(CARD_FPS),
             "-s", f"{card_templates.CARD_WIDTH}x{card_templates.CARD_HEIGHT}", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", str(part)],
            f"building card page {i}", part,
        )
        parts.append(part)

    list_file = out_mp4.parent / "concat.txt"
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if music_path is not None and Path(music_path).exists():
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    # Pages already share codec/params, so the video concat stream-copies.
    cmd += ["-map", "0:v", "-map", "1:a", "-t", f"{target_seconds:.3f}", "-c:v", "copy", "-c:a", "aac", str(out_mp4)]
    _run_ffmpeg(cmd, "assembling card clip", out_mp4)


def _compress(src: Path, dst: Path) -> None:
    """Re-encodes the ntsc-rs output to a compact card. ntsc-rs writes near-
    archival bitrate (right for a one-time library render, ~300MB for a 2-min
    card here), but cards are regenerated every day - at CRF 26 the baked-in
    analog look survives visually while the file shrinks ~10-20x, so the daily
    render doesn't flood the cache disk."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not dst.exists():
        raise RuntimeError(f"ffmpeg failed compressing card (exit {result.returncode}): {result.stderr.strip()[-800:]}")


def render_card(conn: sqlite3.Connection, card: sqlite3.Row, config: Config, weather_lines: list[str]) -> Path:
    """Full pipeline for one card. Marks the row 'rendered' on success or
    'failed' on any error (then re-raises so the batch can log and move on)."""
    try:
        htmls = card_html_pages(conn, card, weather_lines)
        out = cache_path_for(config.ntsc_render_cache_dir, "card", card["id"])
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            pngs = _render_htmls_to_pngs(htmls, tdp)
            clip = tdp / "clip.mp4"  # stills + music bed
            _build_video(pngs, card["target_seconds"], config.card_music_path, clip)
            grimy = tdp / "ntsc.mp4"  # ntsc-rs output, huge - stays in the temp dir
            render_file(config.ntsc_rs_cli_path, config.ntsc_rs_settings_path, clip, grimy)
            _compress(grimy, out)  # compact final card in the cache
    except Exception:
        conn.execute(
            "UPDATE cards SET status = 'failed', generated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), card["id"]),
        )
        conn.commit()
        raise

    conn.execute(
        "UPDATE cards SET rendered_path = ?, duration_seconds = ?, status = 'rendered', generated_at = ? WHERE id = ?",
        (str(out), card["target_seconds"], datetime.now(timezone.utc).isoformat(), card["id"]),
    )
    conn.commit()
    return out
