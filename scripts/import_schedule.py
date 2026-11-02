from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "web/local"))

from app.db import Database
from app.schedule_import import import_schedule
from app.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the VirgoZone weekend schedule")
    parser.add_argument(
        "--friday",
        type=date.fromisoformat,
        default=date(2026, 9, 4),
        help="calendar date represented by the CSV's Friday rows",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=PROJECT_ROOT / "virgo_boys_schedule_web.csv",
    )
    parser.add_argument("--timezone", default="America/Los_Angeles")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    count = import_schedule(database, args.csv, args.friday, args.timezone)
    print(f"Imported {count} VirgoZone schedule blocks from {args.csv.name}.")


if __name__ == "__main__":
    main()
