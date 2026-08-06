# SEAO Forage Watch

Pipeline Python de veille des avis du **Système électronique d'appel d'offres du Québec (SEAO)** portant sur le forage, les puits municipaux, les eaux souterraines et les essais de pompage.

## Fonctionnement

1. interroge l'API CKAN de Données Québec (`package_search`) et découvre les ressources hebdomadaires JSON;
2. conserve chaque réponse OCDS brute sous un nom incluant son SHA-256, avec provenance dans `manifest.jsonl`;
3. normalise les releases dans DuckDB, sans perdre le JSON source;
4. versionne indépendamment chaque couple `(ocid, release.id)` et ignore un contenu déjà ingéré;
5. produit les événements `nouvel_avis`, `mise_a_jour`, `annulation` et `contrat`;
6. applique le score YAML et génère un rapport Markdown des avis pertinents.

Le fixture [`hebdo_20260727_20260802.json`](tests/fixtures/hebdo_20260727_20260802.json), construit selon un Release Package OCDS hebdomadaire du SEAO, sert de modèle et couvre notamment `ocid`, `release.id`, `tag`, `buyer`, `tender`, `items` et la classification UNSPSC.

## Installation

Python 3.11 ou plus récent est requis.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

## Utilisation

```bash
# Pipeline complet : découverte/téléchargement, ingestion, rapport
seao-watch --config config.yaml run

# Étapes séparées
seao-watch --config config.yaml download
seao-watch --config config.yaml ingest data/raw/un-fichier.json
seao-watch --config config.yaml report
```

Les chemins relatifs sont résolus par rapport au fichier de configuration. La base par défaut est `data/seao.duckdb`, les données immuables sont dans `data/raw/` et le rapport dans `data/reports/latest.md`.

## Configuration du ciblage

`config.yaml` contient :

- l'URL et la requête CKAN ainsi qu'une expression régulière de ressource;
- un score minimum;
- des mots-clés pondérés (les accents et la casse sont neutralisés);
- des préfixes UNSPSC pondérés;
- des exclusions prioritaires, notamment « puits d'ascenseur » et « puits de lumière ».

Une exclusion force le rejet, même si un autre terme ou code a marqué l'avis. Ajuster les poids ne requiert aucune modification Python.

## Modèle de données et événements

La table `releases` a une clé `(ocid, release_id, version)`, l'empreinte du contenu, la date, les champs normalisés, le score et le JSON intégral. Une release strictement identique est idempotente; une nouvelle empreinte du même identifiant crée la version suivante. La table `events` conserve les changements détectés : première observation, version ultérieure, statut/tag d'annulation, ou présence d'un contrat/tag contractuel.

## Automatisation GitHub Actions

Le workflow `.github/workflows/watch.yml` tourne chaque jour à 11 h 17 UTC et accepte `workflow_dispatch`. Il archive la base, le manifeste et le rapport sur la branche exécutée afin que l'exécution suivante compare l'historique. Le dépôt ne contient **aucune clé** : les données ouvertes sont téléchargées sans authentification et `GITHUB_TOKEN` est fourni automatiquement par Actions.

Pour un dépôt protégé, remplacer l'étape de commit direct par une branche/PR automatisée ou accorder au workflow l'autorisation d'écriture appropriée.

## Limites et exploitation

- Le schéma OCDS tolère des champs absents; une release sans `ocid` ou `id` est ignorée.
- CKAN peut republier un fichier sous le même nom : le SHA-256 empêche l'écrasement.
- Le rapport liste tout l'historique pertinent. DuckDB permet ensuite d'ajouter une fenêtre temporelle selon les besoins opérationnels.
- Les fichiers de données générés sont ignorés localement; le workflow les ajoute explicitement pour maintenir son état.
