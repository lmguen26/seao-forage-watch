from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path) -> dict[str, Any]:
    """Charge la configuration YAML et résout les chemins depuis sa racine."""
    config_path = Path(path).resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    for key in ("raw_dir", "database", "report"):
        value = config.get("storage", {}).get(key)
        if value and not Path(value).is_absolute():
            config["storage"][key] = str(config_path.parent / value)
    return config

