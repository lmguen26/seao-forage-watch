from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb


def generate_report(database: str | Path, output: str | Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute("""
          SELECT e.event_type, r.ocid, r.release_id, r.title, r.buyer, r.tender_status,
                 r.score, r.reasons, r.release_date
          FROM events e JOIN releases r USING (ocid, release_id, version)
          WHERE r.matched
          ORDER BY e.detected_at DESC, r.score DESC, r.ocid
        """).fetchall()
    lines = ["# Veille SEAO — forage et eaux souterraines", "",
             f"Généré le {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
             f"**{len(rows)} événement(s) pertinent(s)**", ""]
    if not rows:
        lines.append("Aucun avis correspondant aux critères.")
    for event, ocid, release_id, title, buyer, status, score, reasons, date in rows:
        lines.extend([f"## {title or '(sans titre)'}", "",
                      f"- **Événement :** {event.replace('_', ' ')}",
                      f"- **OCID / release :** `{ocid}` / `{release_id}`",
                      f"- **Organisme :** {buyer or '—'}",
                      f"- **Statut / date :** {status or '—'} / {date or '—'}",
                      f"- **Score :** {score} — {', '.join(reasons or [])}", ""])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output

