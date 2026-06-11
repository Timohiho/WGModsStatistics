from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ModSnapshot:
    mod_id: int
    title: str
    downloads: int | None
    votes: int | None
    rating: float | None
    internal_rating: float | None
    version: str | None
    latest_changelog_body: str | None
    latest_changelog_version: str | None
    description_text: str | None
    captured_at: int
    raw: dict[str, Any]

    @property
    def url(self) -> str:
        return f"https://wgmods.net/{self.mod_id}/"
