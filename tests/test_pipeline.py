import json
from pathlib import Path

import duckdb

from seao_watch.config import load_config
from seao_watch.database import classify_events, ingest_files
from seao_watch.report import generate_report
from seao_watch.scoring import score_release


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests/fixtures/hebdo_20260727_20260802.json"


def test_scoring_includes_drilling_and_excludes_false_positive():
    config = load_config(ROOT / "config.yaml")
    releases = json.loads(FIXTURE.read_text())["releases"]
    score, reasons, matched = score_release(releases[0], config)
    assert matched and score >= 3 and any("UNSPSC" in reason for reason in reasons)
    assert score_release(releases[1], config)[2] is False


def test_ingestion_is_idempotent_versions_and_report(tmp_path):
    config = load_config(ROOT / "config.yaml")
    database = tmp_path / "watch.duckdb"
    first = ingest_files(database, [FIXTURE], config["filter"])
    second = ingest_files(database, [FIXTURE], config["filter"])
    assert first["releases"] == 2
    assert second["duplicates"] == 2

    updated = json.loads(FIXTURE.read_text())
    updated["releases"][0]["tender"]["status"] = "cancelled"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(updated))
    ingest_files(database, [changed], config["filter"])
    with duckdb.connect(str(database)) as connection:
        versions = connection.execute("SELECT version FROM releases WHERE ocid='ocds-qc-001' ORDER BY version").fetchall()
        events = {row[0] for row in connection.execute("SELECT event_type FROM events WHERE ocid='ocds-qc-001'").fetchall()}
    assert versions == [(1,), (2,)]
    assert {"nouvel_avis", "mise_a_jour", "annulation"} <= events
    report = generate_report(database, tmp_path / "report.md")
    assert "Forage d'un puits municipal" in report.read_text()


def test_contract_detection():
    release = {"tender": {}, "contracts": [{"id": "c-1"}]}
    assert "contrat" in classify_events(release, {})

