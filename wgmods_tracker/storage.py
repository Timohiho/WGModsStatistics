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
    captured_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_mod_time ON snapshots(mod_id, captured_at);

CREATE TABLE IF NOT EXISTS mod_detail_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id INTEGER NOT NULL,
    normalized_key TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    description_text TEXT,
    captured_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mod_detail_history_mod_time
    ON mod_detail_history(mod_id, captured_at, id);

CREATE TABLE IF NOT EXISTS mod_changelog_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id INTEGER NOT NULL,
    changelog_body TEXT,
    changelog_version TEXT,
    captured_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mod_changelog_history_mod_time
    ON mod_changelog_history(mod_id, captured_at, id);

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
        should_vacuum = self._migrate()
        self.conn.commit()
        if should_vacuum:
            self.conn.execute("VACUUM")

    def _migrate(self) -> bool:
        should_vacuum = False
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(snapshots)")}
        columns = {
            "version": "TEXT",
            "internal_rating": "REAL",
            "latest_changelog_body": "TEXT",
            "latest_changelog_version": "TEXT",
            "description_text": "TEXT",
            "raw_json": "TEXT",
        }
        for name, typ in columns.items():
            if name not in existing:
                self.conn.execute(f"ALTER TABLE snapshots ADD COLUMN {name} {typ}")
        if self._backfill_detail_history():
            should_vacuum = True
        if self._backfill_changelog_history():
            should_vacuum = True
        if self._snapshots_need_rebuild():
            self._rebuild_snapshots_table()
            should_vacuum = True
        self.conn.execute("PRAGMA user_version = 4")
        return should_vacuum

    def _snapshots_need_rebuild(self) -> bool:
        rows = list(self.conn.execute("PRAGMA table_info(snapshots)"))
        columns = [row[1] for row in rows]
        required = [
            "id",
            "mod_id",
            "title",
            "downloads",
            "votes",
            "rating",
            "internal_rating",
            "version",
            "captured_at",
        ]
        if columns != required:
            return True
        for row in rows:
            if row[1] == "id":
                return not bool(row[5])
        return False

    def _rebuild_snapshots_table(self) -> None:
        self.conn.executescript(
            """
            ALTER TABLE snapshots RENAME TO snapshots_old;

            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mod_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                downloads INTEGER,
                votes INTEGER,
                rating REAL,
                internal_rating REAL,
                version TEXT,
                captured_at INTEGER NOT NULL
            );

            INSERT INTO snapshots (
                id, mod_id, title, downloads, votes, rating, internal_rating, version, captured_at
            )
            SELECT
                id, mod_id, title, downloads, votes, rating, internal_rating, version, captured_at
            FROM snapshots_old;

            DROP TABLE snapshots_old;
            CREATE INDEX IF NOT EXISTS idx_snapshots_mod_time ON snapshots(mod_id, captured_at);
            """
        )

    def _normalized_raw_key(self, raw: dict[str, Any]) -> str:
        normalized = dict(raw)
        for key in ("downloads", "mark_votes_count", "mark", "rating"):
            normalized.pop(key, None)
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _latest_detail_row(
        self, mod_id: int, *, captured_at: int | None = None
    ) -> sqlite3.Row | None:
        query = """
            SELECT normalized_key, raw_json, description_text
            FROM mod_detail_history
            WHERE mod_id = ?
        """
        params: list[int] = [mod_id]
        if captured_at is not None:
            query += " AND captured_at <= ?"
            params.append(captured_at)
        query += " ORDER BY captured_at DESC, id DESC LIMIT 1"
        return self.conn.execute(query, tuple(params)).fetchone()

    def _latest_changelog_row(
        self, mod_id: int, *, captured_at: int | None = None
    ) -> sqlite3.Row | None:
        query = """
            SELECT changelog_body, changelog_version
            FROM mod_changelog_history
            WHERE mod_id = ?
        """
        params: list[int] = [mod_id]
        if captured_at is not None:
            query += " AND captured_at <= ?"
            params.append(captured_at)
        query += " ORDER BY captured_at DESC, id DESC LIMIT 1"
        return self.conn.execute(query, tuple(params)).fetchone()

    def _insert_detail_history(
        self,
        mod_id: int,
        normalized_key: str,
        raw_json: str,
        description_text: str | None,
        captured_at: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO mod_detail_history (
                mod_id, normalized_key, raw_json, description_text, captured_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (mod_id, normalized_key, raw_json, description_text, captured_at),
        )

    def _insert_changelog_history(
        self,
        mod_id: int,
        changelog_body: str | None,
        changelog_version: str | None,
        captured_at: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO mod_changelog_history (
                mod_id, changelog_body, changelog_version, captured_at
            ) VALUES (?, ?, ?, ?)
            """,
            (mod_id, changelog_body, changelog_version, captured_at),
        )

    def _materialize_raw(
        self, snapshot_row: sqlite3.Row, detail_row: sqlite3.Row | None
    ) -> dict[str, Any]:
        raw = json.loads(detail_row["raw_json"]) if detail_row and detail_row["raw_json"] else {}
        overlay = {
            "downloads": snapshot_row["downloads"],
            "mark_votes_count": snapshot_row["votes"],
            "mark": snapshot_row["rating"],
            "rating": snapshot_row["internal_rating"],
        }
        for key, value in overlay.items():
            if value is not None:
                raw[key] = value
        return raw

    def _backfill_detail_history(self) -> bool:
        rows = self.conn.execute(
            """
            SELECT id, mod_id, description_text, captured_at, raw_json
            FROM snapshots
            WHERE raw_json IS NOT NULL OR description_text IS NOT NULL
            ORDER BY mod_id, captured_at, id
            """
        ).fetchall()
        if not rows:
            return False

        detail_rows = self.conn.execute(
            """
            SELECT mod_id, normalized_key, description_text
            FROM mod_detail_history
            ORDER BY mod_id, captured_at, id
            """
        ).fetchall()
        last_seen: dict[int, tuple[str, str | None]] = {
            row["mod_id"]: (row["normalized_key"], row["description_text"])
            for row in detail_rows
        }
        snapshot_ids: list[tuple[None, None, int]] = []
        changed = False
        for row in rows:
            raw_json = row["raw_json"]
            description_text = row["description_text"]
            snapshot_ids.append((None, None, row["id"]))
            if not raw_json:
                changed = True
                continue

            normalized_key = self._normalized_raw_key(json.loads(raw_json))
            current_state = (normalized_key, description_text)
            if last_seen.get(row["mod_id"]) == current_state:
                changed = True
                continue

            self._insert_detail_history(
                row["mod_id"],
                normalized_key,
                raw_json,
                description_text,
                row["captured_at"],
            )
            last_seen[row["mod_id"]] = current_state
            changed = True

        self.conn.executemany(
            "UPDATE snapshots SET description_text = ?, raw_json = ? WHERE id = ?",
            snapshot_ids,
        )
        return changed

    def _backfill_changelog_history(self) -> bool:
        rows = self.conn.execute(
            """
            SELECT id, mod_id, latest_changelog_body, latest_changelog_version, captured_at
            FROM snapshots
            WHERE latest_changelog_body IS NOT NULL OR latest_changelog_version IS NOT NULL
            ORDER BY mod_id, captured_at, id
            """
        ).fetchall()
        if not rows:
            return False

        history_rows = self.conn.execute(
            """
            SELECT mod_id, changelog_body, changelog_version
            FROM mod_changelog_history
            ORDER BY mod_id, captured_at, id
            """
        ).fetchall()
        last_seen: dict[int, tuple[str | None, str | None]] = {
            row["mod_id"]: (row["changelog_body"], row["changelog_version"])
            for row in history_rows
        }
        snapshot_ids: list[tuple[None, None, int]] = []
        changed = False
        for row in rows:
            body = row["latest_changelog_body"]
            version = row["latest_changelog_version"]
            snapshot_ids.append((None, None, row["id"]))
            current_state = (body, version)
            if last_seen.get(row["mod_id"]) == current_state:
                changed = True
                continue

            self._insert_changelog_history(
                row["mod_id"],
                body,
                version,
                row["captured_at"],
            )
            last_seen[row["mod_id"]] = current_state
            changed = True

        self.conn.executemany(
            "UPDATE snapshots SET latest_changelog_body = ?, latest_changelog_version = ? WHERE id = ?",
            snapshot_ids,
        )
        return changed

    def close(self) -> None:
        self.conn.close()

    def insert_snapshot(self, snapshot: ModSnapshot) -> None:
        raw_json = json.dumps(snapshot.raw, ensure_ascii=False)
        normalized_key = self._normalized_raw_key(snapshot.raw)
        latest_detail = self._latest_detail_row(snapshot.mod_id)
        latest_changelog = self._latest_changelog_row(snapshot.mod_id)
        if (
            latest_detail is None
            or latest_detail["normalized_key"] != normalized_key
            or latest_detail["description_text"] != snapshot.description_text
        ):
            self._insert_detail_history(
                snapshot.mod_id,
                normalized_key,
                raw_json,
                snapshot.description_text,
                snapshot.captured_at,
            )
        if (
            latest_changelog is None
            or latest_changelog["changelog_body"] != snapshot.latest_changelog_body
            or latest_changelog["changelog_version"] != snapshot.latest_changelog_version
        ):
            self._insert_changelog_history(
                snapshot.mod_id,
                snapshot.latest_changelog_body,
                snapshot.latest_changelog_version,
                snapshot.captured_at,
            )

        self.conn.execute(
            """
            INSERT INTO snapshots (
                mod_id, title, downloads, votes, rating, internal_rating, version, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.mod_id,
                snapshot.title,
                snapshot.downloads,
                snapshot.votes,
                snapshot.rating,
                snapshot.internal_rating,
                snapshot.version,
                snapshot.captured_at,
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
        detail_row = self._latest_detail_row(mod_id, captured_at=row["captured_at"])
        changelog_row = self._latest_changelog_row(mod_id, captured_at=row["captured_at"])

        raw = self._materialize_raw(row, detail_row)
        description_text = (
            detail_row["description_text"] if detail_row else None
        )
        latest_changelog_body = (
            changelog_row["changelog_body"] if changelog_row else None
        )
        latest_changelog_version = (
            changelog_row["changelog_version"] if changelog_row else None
        )
        return ModSnapshot(
            mod_id=row["mod_id"],
            title=row["title"],
            downloads=row["downloads"],
            votes=row["votes"],
            rating=row["rating"],
            internal_rating=row["internal_rating"],
            version=row["version"],
            latest_changelog_body=latest_changelog_body,
            latest_changelog_version=latest_changelog_version,
            description_text=description_text,
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
