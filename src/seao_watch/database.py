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
    """Yield releases from an OCDS ReleasePackage or a legacy bare payload."""
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
    new_tags = {"planning", "tender"}
    update_tags = {"planningupdate", "tenderupdate", "awardupdate", "contractupdate"}
    events: list[str] = []
    if tags.intersection(new_tags):
        events.append("nouvel_avis")
    elif previous is not None or tags.intersection(update_tags):
        events.append("mise_a_jour")
    if status in {"cancelled", "canceled", "annule", "annulé"} or "tendercancellation" in tags:
        events.append("annulation")
    if release.get("contracts") or tags.intersection({"award", "awardupdate", "contract", "contractupdate"}):
        events.append("contrat")
    return list(dict.fromkeys(events))


def ingest_files(database: str | Path, paths: Iterable[str | Path], filter_config: dict[str, Any]) -> dict[str, int]:
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    counts = {"files": 0, "releases": 0, "events": 0, "duplicates": 0}
    with duckdb.connect(str(database)) as connection:
        connection.execute(SCHEMA)
        known_hashes: set[tuple[str, str, str]] = set()
        latest_releases: dict[str, dict[str, Any]] = {}
        max_versions: dict[str, int] = {}
        for ocid, release_id, digest, version, raw in connection.execute(
            """SELECT ocid, release_id, content_hash, version, raw
               FROM releases
               ORDER BY release_date ASC NULLS FIRST, version ASC"""
        ).fetchall():
            known_hashes.add((ocid, release_id, digest))
            latest_releases[ocid] = json.loads(raw)
            max_versions[ocid] = max(max_versions.get(ocid, 0), version)
        for path_value in paths:
            path = Path(path_value)
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            counts["files"] += 1
            connection.execute("BEGIN TRANSACTION")
            try:
                release_rows: list[list[Any]] = []
                event_rows: list[list[Any]] = []
                for release in iter_releases(payload):
                    ocid, release_id = str(release.get("ocid") or ""), str(release.get("id") or "")
                    if not ocid or not release_id:
                        continue
                    canonical = json.dumps(release, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    digest = hashlib.sha256(canonical.encode()).hexdigest()
                    release_key = (ocid, release_id, digest)
                    if release_key in known_hashes:
                        counts["duplicates"] += 1
                        continue
                    previous = latest_releases.get(ocid)
                    version = max_versions.get(ocid, 0) + 1
                    score, reasons, matched = score_release(release, {"filter": filter_config})
                    tender, buyer = release.get("tender") or {}, release.get("buyer") or {}
                    now = datetime.now(timezone.utc)
                    release_rows.append(
                        [ocid, release_id, version, release.get("date"), now, str(path), digest,
                         list(release.get("tag") or []), tender.get("status"), tender.get("title"), buyer.get("name"),
                         score, matched, reasons, canonical]
                    )
                    for event in classify_events(release, previous):
                        event_rows.append([ocid, release_id, version, event, now, tender.get("title")])
                        counts["events"] += 1
                    known_hashes.add(release_key)
                    latest_releases[ocid] = release
                    max_versions[ocid] = version
                    counts["releases"] += 1
                if release_rows:
                    connection.executemany(
                        "INSERT INTO releases VALUES (?, ?, ?, try_cast(? AS TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        release_rows,
                    )
                if event_rows:
                    connection.executemany("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?)", event_rows)
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")
    return counts

