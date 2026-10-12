from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb


def generate_report(database: str | Path, output: str | Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute("""
          WITH ranked_releases AS (
            SELECT r.*,
                   row_number() OVER (
                     PARTITION BY r.ocid
                     ORDER BY r.release_date DESC NULLS LAST, r.version DESC
                   ) AS release_rank
            FROM releases r
          ),
          ranked_events AS (
            SELECT e.*,
                   row_number() OVER (
                     PARTITION BY e.ocid, e.release_id, e.version
                     ORDER BY CASE e.event_type
                       WHEN 'nouvel_avis' THEN 1
                       WHEN 'mise_a_jour' THEN 2
                       ELSE 3
                     END
                   ) AS event_rank
            FROM events e
          )
          SELECT coalesce(e.event_type, 'avis_actif'), r.ocid, r.release_id,
                 r.title, r.buyer, r.tender_status, r.score, r.reasons,
                 r.release_date
          FROM ranked_releases r
          LEFT JOIN ranked_events e
            ON e.ocid = r.ocid
           AND e.release_id = r.release_id
           AND e.version = r.version
           AND e.event_rank = 1
          WHERE r.release_rank = 1
            AND r.matched
            AND lower(trim(coalesce(r.tender_status, ''))) = 'active'
          ORDER BY r.score DESC, r.release_date DESC NULLS LAST, r.ocid
        """).fetchall()
    lines = ["# Veille SEAO — demandes actives en forage et eaux souterraines", "",
             f"Généré le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"**{len(rows)} demande(s) active(s) pertinente(s)**", ""]
    if not rows:
        lines.append("Aucune demande active correspondant aux critères.")
    for event, ocid, release_id, title, buyer, status, score, reasons, date in rows:
        lines.extend([f"## {title or '(sans titre)'}", "",
                      f"- **Événement :** {event.replace('_', ' ')}",
                      f"- **OCID / release :** `{ocid}` / `{release_id}`",
                      f"- **Organisme :** {buyer or '—'}",
                      f"- **Statut / date :** {status or '—'} / {date or '—'}",
                      f"- **Score :** {score} — {', '.join(reasons or [])}", ""])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
