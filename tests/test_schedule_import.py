from __future__ import annotations

from datetime import date
from pathlib import Path

from app.db import Database
from app.schedule_import import import_schedule, read_schedule_blocks


CSV_PATH = Path(__file__).resolve().parent.parent / "virgo_boys_schedule_web.csv"


def test_csv_schedule_rolls_midnight_and_merges_identical_blocks() -> None:
    blocks = read_schedule_blocks(CSV_PATH, date(2026, 9, 4))

    movie = next(block for block in blocks if block.id == "fri-2000-movie")
    midnight_dj = next(block for block in blocks if block.id == "fri-0000-dj")
    saturday_swim = next(block for block in blocks if block.id == "sat-1300-swim-bbq")
    open_slot = next(block for block in blocks if block.id == "fri-1600-open")

    assert movie.starts_at.isoformat() == "2026-09-04T20:00:00-07:00"
    assert movie.ends_at.isoformat() == "2026-09-04T22:00:00-07:00"
    assert midnight_dj.starts_at.isoformat() == "2026-09-05T00:00:00-07:00"
    assert saturday_swim.ends_at.isoformat() == "2026-09-05T15:00:00-07:00"
    assert open_slot.title == "Open Slot"


def test_csv_import_is_idempotent_and_preserves_unrelated_events(settings) -> None:
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    database.create_schedule(
        {
            "title": "Unrelated event",
            "description": None,
            "starts_at": "2031-01-01T12:00:00+00:00",
            "ends_at": None,
            "location": None,
        }
    )

    first_count = import_schedule(database, CSV_PATH, date(2026, 9, 4))
    second_count = import_schedule(database, CSV_PATH, date(2026, 9, 4))
    rows = database.schedule_all()

    assert first_count == second_count
    assert len(rows) == first_count + 1
    assert sum(row["title"] == "Unrelated event" for row in rows) == 1
