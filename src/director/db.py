"""SQLite schema and connection helper for the media catalog."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    root_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    season INTEGER NOT NULL DEFAULT 1,
    episode INTEGER,
    title TEXT,
    file_path TEXT NOT NULL UNIQUE,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    file_mtime REAL,
    file_size INTEGER,
    scanned_at TEXT NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_episodes_series ON episodes(series_id, season, episode);

CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL UNIQUE,
    category TEXT,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    file_mtime REAL,
    file_size INTEGER,
    scanned_at TEXT NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bumpers (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL UNIQUE,
    kind TEXT,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    file_mtime REAL,
    file_size INTEGER,
    scanned_at TEXT NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS play_history (
    id INTEGER PRIMARY KEY,
    item_type TEXT NOT NULL CHECK (item_type IN ('episode', 'ad', 'bumper')),
    item_id INTEGER NOT NULL,
    played_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_play_history_item ON play_history(item_type, item_id, played_at);

CREATE TABLE IF NOT EXISTS program_log (
    id INTEGER PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('episode', 'ad', 'bumper', 'off_air')),
    item_id INTEGER,
    block_name TEXT,
    event_name TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'played', 'skipped')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_program_log_start ON program_log(start_time);
CREATE INDEX IF NOT EXISTS idx_program_log_item ON program_log(item_type, item_id, start_time);

CREATE TABLE IF NOT EXISTS ticker_pools (
    id INTEGER PRIMARY KEY,
    generated_at TEXT NOT NULL,
    msk_date TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('gemini', 'fallback')),
    lines_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticker_pools_msk_date ON ticker_pools(msk_date);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
