"""CLI: renders the animated "silk cloth" background loop used under continuity
cards, writing it to config.cloth_bg_path.

This is a one-time asset - regenerate it only when the cloth look changes, not
every broadcast day. card_render composites each card's transparent foreground
over this loop, so without it cards fall back to a flat navy colour.

Usage:
    .venv/Scripts/python.exe -m director.render_cloth_bg
    .venv/Scripts/python.exe -m director.render_cloth_bg path/to/cloth_loop.mp4
"""

import sys
from pathlib import Path

from director.cloth_bg import render_cloth_loop
from director.config import Config


def main() -> None:
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    else:
        out = Config.load().cloth_bg_path
        if out is None:
            raise SystemExit(
                "config.json has no 'cloth_bg_path'. Add it, or pass an output path:\n"
                "    python -m director.render_cloth_bg path/to/cloth_loop.mp4"
            )
    print(f"rendering cloth loop -> {out} ...")
    render_cloth_loop(out)
    print(f"done: {out} ({out.stat().st_size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    main()
