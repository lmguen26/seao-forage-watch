from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .database import ingest_files
from .download import download_resources
from .report import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Veille des appels d'offres SEAO liés au forage")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("files", nargs="*")
    sub.add_parser("report")
    sub.add_parser("run")
    args = parser.parse_args()
    config = load_config(args.config)
    storage = config["storage"]
    if args.command == "download":
        paths = download_resources(config)
        print(f"{len(paths)} ressource(s) disponible(s)")
    elif args.command == "ingest":
        paths = args.files or sorted(Path(storage["raw_dir"]).glob("*.json"))
        print(ingest_files(storage["database"], paths, config["filter"]))
    elif args.command == "report":
        print(generate_report(storage["database"], storage["report"]))
    else:
        paths = download_resources(config)
        print(ingest_files(storage["database"], paths, config["filter"]))
        print(generate_report(storage["database"], storage["report"]))


if __name__ == "__main__":
    main()

