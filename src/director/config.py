"""Loads library paths and other machine-specific settings from a JSON file.

Real paths differ per machine, so the actual config.json is gitignored;
config.example.json documents the expected shape.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class Config:
    series_root: Path
    ads_root: Path
    bumpers_root: Path
    db_path: Path
    logo_path: Path | None
    ticker_port: int
    dashboard_port: int
    active_series: list[str] | None
    random_rotation_series: list[str]
    ntsc_rs_cli_path: Path | None
    ntsc_rs_settings_path: Path | None
    ntsc_render_cache_dir: Path | None
    card_music_path: Path | None

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or Path(os.environ.get("DIRECTOR_CONFIG", REPO_ROOT / "config.json"))
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}. Copy config.example.json to config.json and fill in real paths."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        logo_path = raw.get("logo_path")
        active_series = raw.get("active_series")
        ntsc_rs_cli_path = raw.get("ntsc_rs_cli_path")
        ntsc_rs_settings_path = raw.get("ntsc_rs_settings_path")
        ntsc_render_cache_dir = raw.get("ntsc_render_cache_dir")
        card_music_path = raw.get("card_music_path")
        return cls(
            series_root=Path(raw["series_root"]),
            ads_root=Path(raw["ads_root"]),
            bumpers_root=Path(raw["bumpers_root"]),
            db_path=Path(raw.get("db_path", REPO_ROOT / "data" / "library.db")),
            logo_path=Path(logo_path) if logo_path else None,
            ticker_port=int(raw.get("ticker_port", 8765)),
            dashboard_port=int(raw.get("dashboard_port", 8766)),
            active_series=list(active_series) if active_series is not None else None,
            random_rotation_series=list(raw.get("random_rotation_series", [])),
            ntsc_rs_cli_path=Path(ntsc_rs_cli_path) if ntsc_rs_cli_path else None,
            ntsc_rs_settings_path=Path(ntsc_rs_settings_path) if ntsc_rs_settings_path else None,
            ntsc_render_cache_dir=Path(ntsc_render_cache_dir) if ntsc_render_cache_dir else None,
            card_music_path=Path(card_music_path) if card_music_path else None,
        )


@dataclass
class Secrets:
    gemini_api_keys: list[str]
    obs_ws_password: str | None

    @classmethod
    def load(cls, path: Path | None = None) -> "Secrets":
        path = path or Path(os.environ.get("DIRECTOR_SECRETS", REPO_ROOT / "secrets.json"))
        if not path.exists():
            raise FileNotFoundError(
                f"Secrets file not found: {path}. Copy secrets.example.json to secrets.json and fill in real keys."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            gemini_api_keys=list(raw.get("gemini_api_keys", [])),
            obs_ws_password=raw.get("obs_ws_password") or None,
        )
