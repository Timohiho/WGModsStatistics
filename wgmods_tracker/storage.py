from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ModSnapshot


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    downloads INTEGER,
    votes INTEGER,
    rating REAL,
    internal_rating REAL,
    version TEXT,
    latest_changelog_body TEXT,
    latest_changelog_version TEXT,
    description_text TEXT,
    captured_at INTEGER NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_mod_time ON snapshots(mod_id, captured_at);

CREATE TABLE IF NOT EXISTS known_mods (
    mod_id INTEGER PRIMARY KEY,
    first_seen_at INTEGER NOT NULL,
    announced_at INTEGER
);

CREATE TABLE IF NOT EXISTS announced_changelogs (
    mod_id INTEGER NOT NULL,
    changelog_key TEXT NOT NULL,
    announced_at INTEGER NOT NULL,
    PRIMARY KEY(mod_id, changelog_key)
);
"""


class Storage:
    def __init__(self, database_path: str):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(snapshots)")}
        columns = {
            "version": "TEXT",
            "latest_changelog_body": "TEXT",
            "latest_changelog_version": "TEXT",
            "description_text": "TEXT",
            "internal_rating": "REAL",
        }
        for name, typ in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {typ}")

    def close(self) -> None:
        self.conn.close()

    def insert_snapshot(self, snapshot: ModSnapshot) -> None:
        self.conn.execute(
            """
            INSERT INTO snapshots (
                mod_id, title, downloads, votes, rating, internal_rating, version,
                latest_changelog_body, latest_changelog_version, description_text,
                captured_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.mod_id,
                snapshot.title,
                snapshot.downloads,
                snapshot.votes,
                snapshot.rating,
                snapshot.internal_rating,
                snapshot.version,
                snapshot.latest_changelog_body,
                snapshot.latest_changelog_version,
                snapshot.description_text,
                snapshot.captured_at,
                json.dumps(snapshot.raw, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def latest_snapshot(self, mod_id: int) -> ModSnapshot | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE mod_id = ? ORDER BY captured_at DESC, id DESC LIMIT 1",
            (mod_id,),
        ).fetchone()
        if not row:
            return None
        raw = json.loads(row["raw_json"])
        return ModSnapshot(
            mod_id=row["mod_id"],
            title=row["title"],
            downloads=row["downloads"],
            votes=row["votes"],
            rating=row["rating"],
            internal_rating=row["internal_rating"],
            version=row["version"],
            latest_changelog_body=row["latest_changelog_body"],
            latest_changelog_version=row["latest_changelog_version"],
            description_text=row["description_text"],
            captured_at=row["captured_at"],
            raw=raw,
        )

    def has_any_snapshots(self) -> bool:
        row = self.conn.execute("SELECT 1 FROM snapshots LIMIT 1").fetchone()
        return row is not None

    def is_known_mod(self, mod_id: int) -> bool:
        return self.conn.execute("SELECT 1 FROM known_mods WHERE mod_id = ?", (mod_id,)).fetchone() is not None

    def mark_known_mod(self, mod_id: int, captured_at: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO known_mods (mod_id, first_seen_at) VALUES (?, ?)",
            (mod_id, captured_at),
        )
        self.conn.commit()

    def mark_mod_announced(self, mod_id: int, captured_at: int) -> None:
        self.conn.execute(
            "UPDATE known_mods SET announced_at = COALESCE(announced_at, ?) WHERE mod_id = ?",
            (captured_at, mod_id),
        )
        self.conn.commit()

    def changelog_was_announced(self, mod_id: int, key: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM announced_changelogs WHERE mod_id = ? AND changelog_key = ?",
            (mod_id, key),
        ).fetchone() is not None

    def mark_changelog_announced(self, mod_id: int, key: str, captured_at: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO announced_changelogs (mod_id, changelog_key, announced_at) VALUES (?, ?, ?)",
            (mod_id, key, captured_at),
        )
        self.conn.commit()
