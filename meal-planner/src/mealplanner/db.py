"""SQLite connection handling and schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
  age        INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS preferences (
  id        INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL CHECK (kind IN ('hard','like','dislike')),
  text      TEXT NOT NULL,
  UNIQUE (member_id, kind, text)
);

CREATE TABLE IF NOT EXISTS websites (
  id     INTEGER PRIMARY KEY,
  domain TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS recipes (
  id               INTEGER PRIMARY KEY,
  url              TEXT NOT NULL UNIQUE,
  title            TEXT,
  site             TEXT,
  servings         INTEGER,
  yields_raw       TEXT,
  total_time_min   INTEGER,
  ingredients_json TEXT NOT NULL DEFAULT '[]',
  instructions     TEXT,
  fetched_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
  id         INTEGER PRIMARY KEY,
  recipe_id  INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  member_id  INTEGER REFERENCES members(id) ON DELETE CASCADE,
  verdict    TEXT NOT NULL CHECK (verdict IN ('liked','disliked')),
  notes      TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (recipe_id, member_id)
);

CREATE TABLE IF NOT EXISTS meal_plans (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  start_date TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_slots (
  id        INTEGER PRIMARY KEY,
  plan_id   INTEGER NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
  day       TEXT NOT NULL,
  meal      TEXT NOT NULL,
  recipe_id INTEGER REFERENCES recipes(id),
  UNIQUE (plan_id, day, meal)
);

CREATE TABLE IF NOT EXISTS slot_attendees (
  slot_id   INTEGER NOT NULL REFERENCES plan_slots(id) ON DELETE CASCADE,
  member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  PRIMARY KEY (slot_id, member_id)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys on and the schema applied."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn
