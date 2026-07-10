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
    series_categories: dict[str, list[str]]  # category -> [series names]; unlisted series default to 'cartoon'
    ntsc_rs_cli_path: Path | None
    ntsc_rs_settings_path: Path | None
    ntsc_render_cache_dir: Path | None
    card_music_path: Path | None
    films_root: Path | None
    active_films: list[str] | None  # allowlist of film folders, like active_series
    film_categories: dict[str, list[str]]  # category -> [film titles]; unlisted default to 'film'
    film_repeat_days: int  # don't re-air a film within this many days
    test_card_path: Path | None  # optional УЭИТ/SMPTE image shown during profilaktika (else color+text)
    cloth_bg_path: Path | None  # seamless "silk cloth" loop composited under continuity cards (render_cloth_bg.py)

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
        films_root = raw.get("films_root")
        active_films = raw.get("active_films")
        test_card_path = raw.get("test_card_path")
        cloth_bg_path = raw.get("cloth_bg_path")
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
            series_categories={k: list(v) for k, v in raw.get("series_categories", {}).items()},
            ntsc_rs_cli_path=Path(ntsc_rs_cli_path) if ntsc_rs_cli_path else None,
            ntsc_rs_settings_path=Path(ntsc_rs_settings_path) if ntsc_rs_settings_path else None,
            ntsc_render_cache_dir=Path(ntsc_render_cache_dir) if ntsc_render_cache_dir else None,
            card_music_path=Path(card_music_path) if card_music_path else None,
            films_root=Path(films_root) if films_root else None,
            active_films=list(active_films) if active_films is not None else None,
            film_categories={k: list(v) for k, v in raw.get("film_categories", {}).items()},
            film_repeat_days=int(raw.get("film_repeat_days", 14)),
            test_card_path=Path(test_card_path) if test_card_path else None,
            cloth_bg_path=Path(cloth_bg_path) if cloth_bg_path else None,
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
