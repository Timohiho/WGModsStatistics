from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = "config.json"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy config.example.json to config.json and fill in your webhooks."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        return json.load(f)
