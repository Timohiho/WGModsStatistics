from __future__ import annotations

import argparse
import asyncio

from .config import load_config
from .runner import run_snapshot, run_watch, test_announcements, test_webhooks


def main() -> None:
    parser = argparse.ArgumentParser(description="Track WGMods statistics and post Discord updates.")
    parser.add_argument(
        "command",
        choices=["snapshot", "watch", "test-webhooks", "test-announcements"],
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--announce-existing",
        action="store_true",
        help="For snapshot only: announce mods even during first database bootstrap. Useful for testing real new-mod messages.",
    )
    parser.add_argument(
        "--max-announcements",
        type=int,
        default=0,
        help="For --announce-existing: maximum new-mod announcements to send. 0 means no limit.",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    if args.command == "snapshot":
        asyncio.run(
            run_snapshot(
                config,
                announce_existing=args.announce_existing,
                max_announcements=args.max_announcements,
            )
        )
    elif args.command == "watch":
        asyncio.run(run_watch(config))
    elif args.command == "test-webhooks":
        asyncio.run(test_webhooks(config))
    elif args.command == "test-announcements":
        asyncio.run(test_announcements(config))
