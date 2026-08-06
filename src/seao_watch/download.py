from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def discover_resources(config: dict[str, Any], client: httpx.Client) -> list[dict[str, Any]]:
    """Découvre toutes les ressources JSON hebdomadaires via package_search CKAN."""
    ckan = config["ckan"]
    response = client.get(f"{ckan['api_url'].rstrip('/')}/package_search", params={"q": ckan["query"], "rows": 100})
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError("La recherche CKAN a échoué")
    pattern = re.compile(ckan["resource_pattern"], re.IGNORECASE)
    resources: list[dict[str, Any]] = []
    for package in payload["result"]["results"]:
        for resource in package.get("resources", []):
            name = resource.get("name") or resource.get("url", "").rsplit("/", 1)[-1]
            if pattern.search(name):
                resources.append({**resource, "package_id": package.get("id"), "name": name})
    return sorted(resources, key=lambda item: item["name"])


def download_resources(config: dict[str, Any]) -> list[Path]:
    """Télécharge sans écraser les instantanés bruts et inscrit un manifeste SHA-256."""
    raw_dir = Path(config["storage"]["raw_dir"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    timeout = config["ckan"].get("timeout_seconds", 120)
    saved: list[Path] = []
    manifest_path = raw_dir / "manifest.jsonl"
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "seao-forage-watch/0.1"}) as client:
        for resource in discover_resources(config, client):
            content = client.get(resource["url"]).raise_for_status().content
            digest = hashlib.sha256(content).hexdigest()
            # Le digest rend chaque version immuable même si CKAN réutilise un nom.
            safe_name = Path(resource["name"]).name.removesuffix(".json")
            target = raw_dir / f"{safe_name}-{digest[:12]}.json"
            if not target.exists():
                json.loads(content)  # refuse une page d'erreur enregistrée comme JSON
                target.write_bytes(content)
                record = {"downloaded_at": datetime.now(timezone.utc).isoformat(), "sha256": digest,
                          "file": target.name, "resource_id": resource.get("id"), "url": resource["url"]}
                with manifest_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            saved.append(target)
    return saved

