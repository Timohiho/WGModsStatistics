from __future__ import annotations

import httpx

from .models import ModSnapshot
from .utils import clamp_discord_message


async def post_webhook(url: str | None, content: str, username: str | None = None) -> None:
    if not url:
        return
    payload = {"content": clamp_discord_message(content)}
    if username:
        payload["username"] = username
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


def format_stat_change(snapshot: ModSnapshot, changes: list[str]) -> str:
    joined = "; ".join(changes)
    linked_mod_id = f"[{snapshot.mod_id}](<{snapshot.url}>)"
    return f"**Changes for {snapshot.title} ({linked_mod_id})**: {joined}"


def format_new_mod_announcement(snapshot: ModSnapshot, mention: str) -> str:
    version = snapshot.version or "?"
    description = (snapshot.description_text or "").strip()
    if not description:
        description = "New mod published on WGMods."
    return (
        f"# :new: {snapshot.title} `{version}`\n"
        f"{description}\n"
        f"[Download]({snapshot.url})\n"
        f"{mention}".strip()
    )


def format_changelog_announcement(snapshot: ModSnapshot, mention: str) -> str:
    version = snapshot.latest_changelog_version or snapshot.version or "?"
    body = (snapshot.latest_changelog_body or "").strip()
    return (
        f"# 🔄 {snapshot.title} `{version}`\n"
        f"{body}\n"
        f"[Download]({snapshot.url})\n"
        f"{mention}".strip()
    )
