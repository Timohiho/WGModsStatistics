from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Browser, Page

from .utils import normalize_endpoint_offset


class WGModsBrowser:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_url = config.get("base_url", "https://wgmods.net").rstrip("/")
        self.playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.debug_dir = Path(config.get("debug_json_dir", "data/debug"))
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "WGModsBrowser":
        browser_cfg = self.config.get("browser", {})
        self.playwright = await async_playwright().start()
        launch_options = {
            "headless": bool(browser_cfg.get("headless", True)),
            "slow_mo": int(browser_cfg.get("slow_mo_ms", 0) or 0),
        }

        # Raspberry Pi / ARM note:
        # Playwright may not be able to download its bundled Chromium build on ARM.
        # In that case install the system Chromium package and set
        # browser.executable_path in config.json, for example /usr/bin/chromium-browser
        # or /usr/bin/chromium.
        executable_path = (browser_cfg.get("executable_path") or "").strip()
        if executable_path:
            launch_options["executable_path"] = executable_path

        extra_args = browser_cfg.get("args")
        if isinstance(extra_args, list) and extra_args:
            launch_options["args"] = [str(arg) for arg in extra_args]

        self.browser = await self.playwright.chromium.launch(**launch_options)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(int(browser_cfg.get("navigation_timeout_ms", 60000)))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    def _page(self) -> Page:
        if not self.page:
            raise RuntimeError("Browser page is not initialized.")
        return self.page

    async def bootstrap_api_context(self) -> None:
        mod_id = int(self.config.get("api_bootstrap_mod_id", 7438))
        await self.open_mod_page(mod_id)

    async def open_mod_page(self, mod_id: int) -> None:
        page = self._page()
        await page.goto(f"{self.base_url}/{mod_id}/", wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    async def _fetch_json_in_page(self, url: str) -> dict[str, Any] | list[Any]:
        page = self._page()
        return await page.evaluate(
            """
            async (url) => {
                const response = await fetch(url, {
                    method: "GET",
                    credentials: "include",
                    headers: {
                        "Accept": "application/json, text/plain, */*",
                        "X-Requested-With": "XMLHttpRequest"
                    }
                });
                const text = await response.text();
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${text.slice(0, 500)}`);
                }
                try {
                    return JSON.parse(text);
                } catch (e) {
                    throw new Error(`Response was not JSON: ${text.slice(0, 500)}`);
                }
            }
            """,
            url,
        )

    def _extract_mod_ids_from_payload(self, payload: Any) -> list[int]:
        ids: list[int] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                if "id" in obj and ("downloads" in obj or "mark" in obj or "versions" in obj or "localizations" in obj):
                    try:
                        ids.append(int(obj["id"]))
                    except Exception:
                        pass
                for key in ("results", "items", "mods", "objects", "data"):
                    if key in obj:
                        walk(obj[key])
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(payload)
        seen = set()
        out = []
        for mod_id in ids:
            if mod_id not in seen:
                seen.add(mod_id)
                out.append(mod_id)
        return out

    async def discover_mod_ids(self) -> list[int]:
        await self.bootstrap_api_context()
        endpoint = self.config["owner_mods_endpoint"]
        limit = int(self.config.get("owner_mods_page_size", 12))
        max_pages = int(self.config.get("owner_mods_max_pages", 100))

        all_ids: list[int] = []
        seen: set[int] = set()

        for page_idx in range(max_pages):
            offset = page_idx * limit
            url = normalize_endpoint_offset(endpoint, offset, limit)
            try:
                payload = await self._fetch_json_in_page(url)
            except Exception as exc:
                print(f"Owner endpoint failed at offset={offset}: {exc}")
                break

            debug_path = self.debug_dir / f"owner_offset_{offset}.json"
            debug_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

            ids = self._extract_mod_ids_from_payload(payload)
            new_ids = [mid for mid in ids if mid not in seen]
            for mid in new_ids:
                seen.add(mid)
                all_ids.append(mid)

            print(f"Owner page offset={offset}, limit={limit}: {len(ids)} mods, {len(new_ids)} new")

            count = payload.get("count") if isinstance(payload, dict) else None
            if count is not None and len(all_ids) >= int(count):
                break
            if len(ids) < limit:
                break
            if not new_ids:
                break

        print(f"Found {len(all_ids)} mod IDs: {', '.join(map(str, all_ids))}")
        return all_ids

    async def fetch_mod_details(self, mod_id: int) -> dict[str, Any]:
        await self.open_mod_page(mod_id)
        url = f"{self.base_url}/api/mods/{mod_id}/"
        payload = await self._fetch_json_in_page(url)
        debug_path = self.debug_dir / f"mod_{mod_id}.json"
        debug_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected mod detail payload for {mod_id}: {type(payload).__name__}")
        return payload
