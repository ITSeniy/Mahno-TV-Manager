import sqlite3

from director import db

# The program_log schema exactly as it was before 'card' was added, used to
# stand up a pre-migration database on disk and confirm db.connect upgrades it.
_OLD_PROGRAM_LOG = """
CREATE TABLE program_log (
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
CREATE INDEX idx_program_log_start ON program_log(start_time);
CREATE INDEX idx_program_log_item ON program_log(item_type, item_id, start_time);
INSERT INTO program_log (start_time, end_time, item_type, item_id)
    VALUES ('2026-07-06T07:00:00+00:00', '2026-07-06T07:20:00+00:00', 'episode', 1);
INSERT INTO program_log (start_time, end_time, item_type, item_id)
    VALUES ('2026-07-06T07:20:00+00:00', '2026-07-06T12:00:00+00:00', 'off_air', NULL);
"""


def _insert_card_row(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO program_log (start_time, end_time, item_type, item_id) VALUES (?, ?, 'card', ?)",
        ("2026-07-06T12:00:00+00:00", "2026-07-06T12:00:47+00:00", None),
    )
    conn.commit()


def test_fresh_db_has_cards_and_accepts_card_item_type(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")

    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"cards", "weather_pools"} <= tables

    # The whole point of widening the constraint: a card row must insert cleanly.
    _insert_card_row(conn)
    assert conn.execute("SELECT COUNT(*) AS c FROM program_log WHERE item_type = 'card'").fetchone()["c"] == 1


def test_connect_migrates_a_pre_card_program_log_in_place(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(_OLD_PROGRAM_LOG)
    raw.commit()
    raw.close()

    conn = db.connect(path)

    # Existing rows survive the rebuild untouched, in order.
    preserved = [r["item_type"] for r in conn.execute("SELECT item_type FROM program_log ORDER BY id")]
    assert preserved == ["episode", "off_air"]

    # ...and the widened constraint now accepts 'card' where it didn't before.
    _insert_card_row(conn)
    assert conn.execute("SELECT COUNT(*) AS c FROM program_log").fetchone()["c"] == 3

    indexes = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_program_log_start", "idx_program_log_item"} <= indexes


def test_migration_is_idempotent_and_survives_reconnect(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(_OLD_PROGRAM_LOG)
    raw.commit()
    raw.close()

    conn = db.connect(path)
    _insert_card_row(conn)
    conn.close()

    # Reconnecting must not rebuild again (guarded on the constraint text) and
    # must not lose the card row inserted after the first migration.
    conn2 = db.connect(path)
    assert conn2.execute("SELECT COUNT(*) AS c FROM program_log WHERE item_type = 'card'").fetchone()["c"] == 1
