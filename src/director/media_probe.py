"""Extracts duration/resolution from a media file via ffprobe."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MediaInfo:
    duration_seconds: float | None
    width: int | None
    height: int | None


def probe(file_path: Path) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    duration = None
    fmt_duration = data.get("format", {}).get("duration")
    if fmt_duration is not None:
        duration = float(fmt_duration)

    width = height = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            if duration is None and stream.get("duration") is not None:
                duration = float(stream["duration"])
            break

    return MediaInfo(duration_seconds=duration, width=width, height=height)
