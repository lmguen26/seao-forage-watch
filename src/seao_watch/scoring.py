from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def release_text(release: dict[str, Any]) -> str:
    tender = release.get("tender") or {}
    buyer = release.get("buyer") or {}
    procuring_entity = tender.get("procuringEntity") or {}
    parts = [tender.get("title"), tender.get("description"), buyer.get("name"), procuring_entity.get("name")]
    for item in tender.get("items", []):
        if not isinstance(item, dict):
            continue
        parts.extend([item.get("description"), (item.get("classification") or {}).get("description")])
        parts.extend(c.get("description") for c in item.get("additionalClassifications", []) if isinstance(c, dict))
    for document in tender.get("documents", []):
        if isinstance(document, dict):
            parts.extend([document.get("title"), document.get("description")])
    return normalized(" ".join(str(part or "") for part in parts))


def score_release(release: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str], bool]:
    rules = config["filter"]
    text = release_text(release)
    exclusions = [term for term in rules.get("exclusions", []) if normalized(term) in text]
    if exclusions:
        return 0, [f"exclusion:{term}" for term in exclusions], False
    score, reasons = 0, []
    for keyword, weight in rules.get("keywords", {}).items():
        if normalized(keyword) in text:
            score += int(weight)
            reasons.append(f"mot-clé:{keyword} (+{weight})")
    tender = release.get("tender") or {}
    codes = []
    for item in tender.get("items", []):
        if not isinstance(item, dict):
            continue
        classification = item.get("classification") or {}
        codes.append(str(classification.get("id") or ""))
        codes.extend(str(c.get("id") or "") for c in item.get("additionalClassifications", []) if isinstance(c, dict))
    for prefix, weight in rules.get("unspsc", {}).items():
        if any(code.startswith(str(prefix)) for code in codes):
            score += int(weight)
            reasons.append(f"UNSPSC:{prefix} (+{weight})")
    return score, reasons, score >= int(rules.get("minimum_score", 1))

