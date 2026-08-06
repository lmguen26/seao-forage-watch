from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from .scoring import score_release

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
  ocid VARCHAR NOT NULL, release_id VARCHAR NOT NULL, version INTEGER NOT NULL,
  release_date TIMESTAMP, ingested_at TIMESTAMP NOT NULL, source_file VARCHAR NOT NULL,
  content_hash VARCHAR NOT NULL, tag VARCHAR[], tender_status VARCHAR, title VARCHAR,
  buyer VARCHAR, score INTEGER, matched BOOLEAN, reasons VARCHAR[], raw JSON,
  PRIMARY KEY (ocid, release_id, version)
);
CREATE TABLE IF NOT EXISTS events (
  ocid VARCHAR, release_id VARCHAR, version INTEGER, event_type VARCHAR,
  detected_at TIMESTAMP, details VARCHAR,
  UNIQUE (ocid, release_id, version, event_type)
);
"""


def iter_releases(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        yield from (item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        if isinstance(payload.get("releases"), list):
            yield from (item for item in payload["releases"] if isinstance(item, dict))
        elif payload.get("ocid"):
            yield payload


def classify_events(release: dict[str, Any], previous: dict[str, Any] | None) -> list[str]:
    tags = {str(tag).lower() for tag in release.get("tag", [])}
    status = str((release.get("tender") or {}).get("status") or "").lower()
    events = ["nouvel_avis"] if previous is None else ["mise_a_jour"]
    if status in {"cancelled", "canceled", "annule", "annulé"} or "tendercancellation" in tags:
        events.append("annulation")
    if release.get("contracts") or tags.intersection({"award", "contract", "contractupdate"}):
        events.append("contrat")
    return events


def ingest_files(database: str | Path, paths: Iterable[str | Path], filter_config: dict[str, Any]) -> dict[str, int]:
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    counts = {"files": 0, "releases": 0, "events": 0, "duplicates": 0}
    with duckdb.connect(str(database)) as connection:
        connection.execute(SCHEMA)
        for path_value in paths:
            path = Path(path_value)
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            counts["files"] += 1
            for release in iter_releases(payload):
                ocid, release_id = str(release.get("ocid") or ""), str(release.get("id") or "")
                if not ocid or not release_id:
                    continue
                canonical = json.dumps(release, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                existing = connection.execute(
                    "SELECT version FROM releases WHERE ocid=? AND release_id=? AND content_hash=?",
                    [ocid, release_id, digest],
                ).fetchone()
                if existing:
                    counts["duplicates"] += 1
                    continue
                row = connection.execute(
                    "SELECT version, raw FROM releases WHERE ocid=? ORDER BY release_date DESC NULLS LAST, version DESC LIMIT 1",
                    [ocid],
                ).fetchone()
                previous = json.loads(row[1]) if row else None
                version_row = connection.execute(
                    "SELECT coalesce(max(version), 0) + 1 FROM releases WHERE ocid=? AND release_id=?", [ocid, release_id]
                ).fetchone()
                version = version_row[0]
                score, reasons, matched = score_release(release, {"filter": filter_config})
                tender, buyer = release.get("tender") or {}, release.get("buyer") or {}
                now = datetime.now(timezone.utc)
                connection.execute(
                    "INSERT INTO releases VALUES (?, ?, ?, try_cast(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [ocid, release_id, version, release.get("date"), now, str(path), digest,
                     list(release.get("tag") or []), tender.get("status"), tender.get("title"), buyer.get("name"),
                     score, matched, reasons, canonical],
                )
                for event in classify_events(release, previous):
                    connection.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?)",
                                       [ocid, release_id, version, event, now, tender.get("title")])
                    counts["events"] += 1
                counts["releases"] += 1
    return counts

