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

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or Path(os.environ.get("DIRECTOR_CONFIG", REPO_ROOT / "config.json"))
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}. Copy config.example.json to config.json and fill in real paths."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        logo_path = raw.get("logo_path")
        return cls(
            series_root=Path(raw["series_root"]),
            ads_root=Path(raw["ads_root"]),
            bumpers_root=Path(raw["bumpers_root"]),
            db_path=Path(raw.get("db_path", REPO_ROOT / "data" / "library.db")),
            logo_path=Path(logo_path) if logo_path else None,
            ticker_port=int(raw.get("ticker_port", 8765)),
        )


@dataclass
class Secrets:
    gemini_api_keys: list[str]

    @classmethod
    def load(cls, path: Path | None = None) -> "Secrets":
        path = path or Path(os.environ.get("DIRECTOR_SECRETS", REPO_ROOT / "secrets.json"))
        if not path.exists():
            raise FileNotFoundError(
                f"Secrets file not found: {path}. Copy secrets.example.json to secrets.json and fill in real keys."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(gemini_api_keys=list(raw.get("gemini_api_keys", [])))
