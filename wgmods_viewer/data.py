from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "mod_id",
    "title",
    "downloads",
    "votes",
    "rating",
    "internal_rating",
    "version",
    "captured_at",
}


class DatabaseError(RuntimeError):
    pass


def validate_database(path: str | Path) -> Path:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise DatabaseError(f"Database file does not exist: {db_path}")

    try:
        with sqlite3.connect(db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "snapshots" not in tables:
                raise DatabaseError("The database has no 'snapshots' table.")

            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(snapshots)")
            }
    except sqlite3.Error as exc:
        raise DatabaseError(f"Could not read SQLite database: {exc}") from exc

    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise DatabaseError(
            "The snapshots table is missing required columns: "
            + ", ".join(sorted(missing))
        )
    return db_path


def load_snapshots(path: str | Path, timezone_name: str) -> pd.DataFrame:
    db_path = validate_database(path)

    query = """
        SELECT
            id,
            mod_id,
            title,
            downloads,
            votes,
            rating,
            internal_rating,
            version,
            captured_at
        FROM snapshots
        ORDER BY captured_at, id
    """

    try:
        with sqlite3.connect(db_path) as connection:
            frame = pd.read_sql_query(query, connection)
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        raise DatabaseError(f"Could not load snapshots: {exc}") from exc

    if frame.empty:
        raise DatabaseError("The snapshots table is empty.")

    frame["timestamp"] = pd.to_datetime(
        frame["captured_at"], unit="s", utc=True, errors="coerce"
    )
    frame = frame.dropna(subset=["timestamp"])
    if frame.empty:
        raise DatabaseError("No valid Unix timestamps were found.")

    try:
        frame["timestamp"] = frame["timestamp"].dt.tz_convert(timezone_name)
    except Exception as exc:
        raise DatabaseError(f"Invalid timezone '{timezone_name}': {exc}") from exc

    # Keep the latest title recorded for each mod in a separate stable label.
    latest_titles = (
        frame.sort_values(["captured_at", "id"])
        .groupby("mod_id", as_index=False)
        .tail(1)
        .set_index("mod_id")["title"]
    )
    frame["display_title"] = frame["mod_id"].map(latest_titles)
    return frame.sort_values(["timestamp", "mod_id", "id"]).reset_index(drop=True)


def list_mods(frame: pd.DataFrame) -> pd.DataFrame:
    latest = (
        frame.sort_values(["captured_at", "id"])
        .groupby("mod_id", as_index=False)
        .tail(1)
        .copy()
    )
    first_downloads = frame.groupby("mod_id")["downloads"].first()
    latest["growth"] = (
        latest["downloads"] - latest["mod_id"].map(first_downloads)
    ).fillna(0)
    return latest[
        ["mod_id", "display_title", "downloads", "votes", "growth"]
    ].sort_values(["downloads", "display_title"], ascending=[False, True])
