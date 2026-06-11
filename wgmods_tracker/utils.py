from __future__ import annotations

import html
import re
from bs4 import BeautifulSoup


def to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_localized_title(raw: dict) -> str:
    for loc in raw.get("localizations") or []:
        title = loc.get("title")
        if title:
            return str(title)
    return f"Mod {raw.get('id')}"


def get_description_html(raw: dict) -> str:
    for loc in raw.get("localizations") or []:
        desc = loc.get("description")
        if desc:
            return str(desc)
    return ""


def html_to_clean_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text("\n")
    text = html.unescape(text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if "for support" in low or "questions" in low or "suggestions" in low:
            continue
        if "support me on patreon" in low:
            continue
        if "patreon.com" in low:
            continue
        if "discord.gg" in low:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def first_version(raw: dict) -> dict | None:
    versions = raw.get("versions") or []
    if not versions:
        return None
    return versions[0]


def latest_changelog(raw: dict) -> tuple[str | None, str | None]:
    # Prefer WGMods top-level changelog because it is the author-facing changelog list.
    for item in raw.get("change_log") or []:
        body = (item.get("body") or "").strip()
        version = (item.get("version") or "").strip() or None
        if body:
            return body, version

    version = first_version(raw)
    if version:
        body = (version.get("change_log") or version.get("comment") or "").strip()
        ver = (version.get("version") or "").strip() or None
        if body:
            return body, ver
    return None, None


def newest_version_string(raw: dict) -> str | None:
    version = first_version(raw)
    if version and version.get("version"):
        return str(version["version"])
    body, ver = latest_changelog(raw)
    return ver


def clamp_discord_message(message: str, max_len: int = 1900) -> str:
    if len(message) <= max_len:
        return message
    return message[: max_len - 20].rstrip() + "\n…"


def normalize_endpoint_offset(endpoint: str, offset: int, limit: int) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(endpoint)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["offset"] = str(offset)
    query["limit"] = str(limit)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
