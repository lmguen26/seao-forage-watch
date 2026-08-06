import json
from pathlib import Path

import duckdb

from seao_watch.config import load_config
from seao_watch.database import classify_events, ingest_files, iter_releases
from seao_watch.report import generate_report
from seao_watch.scoring import score_release


ROOT = Path(__file__).parents[1]
UNIT_FIXTURE = ROOT / "tests/fixtures/ocds_synthetic.json"
REAL_FIXTURE = ROOT / "tests/fixtures/hebdo_20260727_20260802.json"


def test_scoring_includes_drilling_and_excludes_false_positive():
    config = load_config(ROOT / "config.yaml")
    releases = json.loads(UNIT_FIXTURE.read_text(encoding="utf-8"))["releases"]
    score, reasons, matched = score_release(releases[0], config)
    assert matched and score >= 3 and any("UNSPSC" in reason for reason in reasons)
    assert score_release(releases[1], config)[2] is False


def test_ingestion_is_idempotent_versions_and_report(tmp_path):
    config = load_config(ROOT / "config.yaml")
    database = tmp_path / "watch.duckdb"
    first = ingest_files(database, [UNIT_FIXTURE], config["filter"])
    second = ingest_files(database, [UNIT_FIXTURE], config["filter"])
    assert first["releases"] == 2
    assert second["duplicates"] == 2

    updated = json.loads(UNIT_FIXTURE.read_text(encoding="utf-8"))
    updated["releases"] = [updated["releases"][0]]
    updated["releases"][0]["id"] = "release-1-update"
    updated["releases"][0]["date"] = "2026-07-29T09:00:00-04:00"
    updated["releases"][0]["tag"] = ["tenderUpdate"]
    updated["releases"][0]["tender"]["status"] = "cancelled"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(updated), encoding="utf-8")
    ingest_files(database, [changed], config["filter"])
    with duckdb.connect(str(database)) as connection:
        versions = connection.execute(
            "SELECT version FROM releases WHERE ocid='ocds-test-drilling' ORDER BY version"
        ).fetchall()
        events = {
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM events WHERE ocid='ocds-test-drilling'"
            ).fetchall()
        }
    assert versions == [(1,), (2,)]
    assert {"nouvel_avis", "mise_a_jour", "annulation"} <= events
    report = generate_report(database, tmp_path / "report.md")
    assert "Travaux municipaux" in report.read_text(encoding="utf-8")


def test_contract_detection():
    release = {"tag": ["contract"], "tender": {}, "contracts": [{"id": "c-1"}]}
    assert "contrat" in classify_events(release, {})


def test_real_seao_release_package_is_preserved_and_parseable():
    payload = json.loads(REAL_FIXTURE.read_text(encoding="utf-8-sig"))
    releases = list(iter_releases(payload))
    assert payload["version"] == "1.1"
    assert payload["extensions"]
    assert len(releases) == 3483
    required = {"ocid", "id", "date", "tag", "parties", "buyer", "tender"}
    assert all(required <= release.keys() for release in releases)
    assert any(release.get("awards") for release in releases)
    assert any(release.get("contracts") for release in releases)
