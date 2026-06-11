from __future__ import annotations

import time
from typing import Any

from .models import ModSnapshot
from .utils import (
    get_description_html,
    get_localized_title,
    html_to_clean_text,
    latest_changelog,
    newest_version_string,
    to_float,
    to_int,
)


def snapshot_from_raw(raw: dict[str, Any]) -> ModSnapshot:
    mod_id = int(raw["id"])
    body, ch_ver = latest_changelog(raw)
    return ModSnapshot(
        mod_id=mod_id,
        title=get_localized_title(raw),
        downloads=to_int(raw.get("downloads")),
        votes=to_int(raw.get("mark_votes_count")),
        rating=to_float(raw.get("mark")),
        internal_rating=to_float(raw.get("rating")),
        version=newest_version_string(raw),
        latest_changelog_body=body,
        latest_changelog_version=ch_ver,
        description_text=html_to_clean_text(get_description_html(raw)),
        captured_at=int(time.time()),
        raw=raw,
    )


def diff_snapshots(old: ModSnapshot | None, new: ModSnapshot) -> list[str]:
    if old is None:
        return []
    changes: list[str] = []

    def add_change(label: str, old_value, new_value, suffix: str = "") -> None:
        if old_value == new_value:
            return
        if old_value is None and new_value is None:
            return
        delta = None
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            delta_value = new_value - old_value
            sign = "+" if delta_value > 0 else ""
            delta = f" ({sign}{delta_value:g}{suffix})"
        changes.append(f"{label}: {old_value} -> {new_value}{delta or ''}")

    add_change("downloads", old.downloads, new.downloads)
    add_change("votes", old.votes, new.votes)
    add_change("rating", old.rating, new.rating)
    add_change("internal rating", old.internal_rating, new.internal_rating)
    add_change("version", old.version, new.version)
    return changes


def changelog_key(snapshot: ModSnapshot) -> str | None:
    body = (snapshot.latest_changelog_body or "").strip()
    if not body:
        return None
    ver = snapshot.latest_changelog_version or snapshot.version or ""
    return f"{snapshot.mod_id}:{ver}:{body}"
