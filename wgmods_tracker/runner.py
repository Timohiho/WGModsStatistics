from __future__ import annotations

import asyncio
from typing import Any

from .browser import WGModsBrowser
from .discord import (
    format_changelog_announcement,
    format_new_mod_announcement,
    format_stat_change,
    post_webhook,
)
from .snapshot import changelog_key, diff_snapshots, snapshot_from_raw
from .storage import Storage


async def run_snapshot(
    config: dict[str, Any],
    *,
    announce_existing: bool = False,
    max_announcements: int = 0,
) -> None:
    storage = Storage(config.get("database_path", "data/wgmods_stats.sqlite"))
    discord_cfg = config.get("discord", {})
    is_bootstrap = not storage.has_any_snapshots()
    sent_announcements = 0

    try:
        async with WGModsBrowser(config) as browser:
            mod_ids = await browser.discover_mod_ids()
            for mod_id in mod_ids:
                was_known = storage.is_known_mod(mod_id)
                raw = await browser.fetch_mod_details(mod_id)
                snapshot = snapshot_from_raw(raw)
                old = storage.latest_snapshot(mod_id)
                changes = diff_snapshots(old, snapshot)

                storage.mark_known_mod(mod_id, snapshot.captured_at)
                storage.insert_snapshot(snapshot)

                if old is None:
                    print(
                        f"First snapshot for {snapshot.title} ({snapshot.mod_id}): "
                        f"downloads={snapshot.downloads}, votes={snapshot.votes}, rating={snapshot.rating}"
                    )
                    should_announce_new = (
                        discord_cfg.get("post_new_mod_announcements", True)
                        and (
                            (not is_bootstrap and not was_known)
                            or announce_existing
                        )
                    )
                    if max_announcements and sent_announcements >= max_announcements:
                        should_announce_new = False

                    if should_announce_new:
                        msg = format_new_mod_announcement(
                            snapshot,
                            discord_cfg.get("new_mod_mention", "@Update Notifications"),
                        )
                        await post_webhook(
                            discord_cfg.get("announcements_webhook_url"),
                            msg,
                            discord_cfg.get("announcements_username"),
                        )
                        storage.mark_mod_announced(snapshot.mod_id, snapshot.captured_at)
                        sent_announcements += 1
                    continue

                if changes:
                    print(f"Changes for {snapshot.title} ({snapshot.mod_id}): {'; '.join(changes)}")
                    if discord_cfg.get("post_stat_changes", True):
                        await post_webhook(
                            discord_cfg.get("stats_webhook_url"),
                            format_stat_change(snapshot, changes),
                            discord_cfg.get("stats_username"),
                        )
                else:
                    print(f"No changes for {snapshot.title} ({snapshot.mod_id})")

                key = changelog_key(snapshot)
                old_key = changelog_key(old)
                if (
                    key
                    and key != old_key
                    and discord_cfg.get("post_changelog_announcements", True)
                    and not storage.changelog_was_announced(snapshot.mod_id, key)
                ):
                    msg = format_changelog_announcement(
                        snapshot,
                        discord_cfg.get("update_mention", "<@&1472909774919307286>"),
                    )
                    await post_webhook(
                        discord_cfg.get("announcements_webhook_url"),
                        msg,
                        discord_cfg.get("announcements_username"),
                    )
                    storage.mark_changelog_announced(snapshot.mod_id, key, snapshot.captured_at)
    finally:
        storage.close()


async def run_watch(config: dict[str, Any]) -> None:
    interval = int(config.get("watch_interval_seconds", 3600))
    while True:
        try:
            await run_snapshot(config)
        except Exception as exc:
            print(f"Snapshot failed: {exc}")
        await asyncio.sleep(interval)


async def test_webhooks(config: dict[str, Any]) -> None:
    discord_cfg = config.get("discord", {})
    await post_webhook(
        discord_cfg.get("stats_webhook_url"),
        "WGMods statistics webhook test.",
        discord_cfg.get("stats_username"),
    )
    await post_webhook(
        discord_cfg.get("announcements_webhook_url"),
        "# :new: WGMods announcement webhook test\nThis is a test message.\n[Download](https://wgmods.net/)\n"
        + discord_cfg.get("new_mod_mention", "@Update Notifications"),
        discord_cfg.get("announcements_username"),
    )
    print("Webhook test completed.")


async def test_announcements(config: dict[str, Any]) -> None:
    discord_cfg = config.get("discord", {})

    update_msg = (
        "# 🔄 Crosshair Ballistics Info `1.1`\n"
        "Added the option to customize the colour of the overlay in the preferences.xml file. "
        "(Section: ballisticsCrosshairOverlay)\n"
        "You'll have to start the game and drag the overlay a bit first for the colour options to appear.\n"
        "[Download](https://wgmods.net/7681/)\n"
        + discord_cfg.get("update_mention", "<@&1472909774919307286>")
    )

    new_mod_msg = (
        "# :new: Crosshair Ballistics Info `1.0`\n"
        "Shows distance, dynamic damage, and dynamic penetration at your crosshair.\n"
        "Especially useful for Deep Rifled Guns.\n"
        "[Download](https://wgmods.net/7681/)\n"
        + discord_cfg.get("new_mod_mention", "@Update Notifications")
    )

    await post_webhook(
        discord_cfg.get("announcements_webhook_url"),
        update_msg,
        discord_cfg.get("announcements_username"),
    )
    await post_webhook(
        discord_cfg.get("announcements_webhook_url"),
        new_mod_msg,
        discord_cfg.get("announcements_username"),
    )
    print("Announcement format test completed.")
