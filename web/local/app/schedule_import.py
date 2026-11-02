from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import Database


@dataclass
class ScheduleBlock:
    id: str
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime


def read_schedule_blocks(
    csv_path: Path,
    friday: date,
    timezone_name: str = "America/Los_Angeles",
) -> list[ScheduleBlock]:
    timezone = ZoneInfo(timezone_name)
    day_dates = {
        "Friday": friday,
        "Saturday": friday + timedelta(days=1),
        "Sunday": friday + timedelta(days=2),
    }
    slots: list[ScheduleBlock] = []
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            day = row["day"]
            hour, minute = (int(part) for part in row["time_24h"].split(":"))
            event_date = day_dates[day]
            if hour < 6:
                event_date += timedelta(days=1)
            starts_at = datetime.combine(event_date, time(hour, minute), timezone)
            title = row["activity"].strip() or "Open Slot"
            category = row["category"].strip().replace("_", " ").title()
            detail = row["description"].strip()
            description = " · ".join(part for part in (detail, category) if part) or None
            slots.append(
                ScheduleBlock(
                    id=row["id"],
                    title=title,
                    description=description,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(hours=1),
                )
            )

    merged: list[ScheduleBlock] = []
    for slot in slots:
        previous = merged[-1] if merged else None
        if (
            previous
            and previous.title == slot.title
            and previous.description == slot.description
            and previous.ends_at == slot.starts_at
        ):
            previous.ends_at = slot.ends_at
        else:
            merged.append(slot)
    return merged


def import_schedule(
    database: Database,
    csv_path: Path,
    friday: date,
    timezone_name: str = "America/Los_Angeles",
) -> int:
    blocks = read_schedule_blocks(csv_path, friday, timezone_name)
    now = datetime.now(ZoneInfo("UTC")).isoformat()
    with database.connection() as connection:
        for block in blocks:
            connection.execute(
                "INSERT INTO schedule_events(id, title, description, starts_at, ends_at, "
                "location, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "description=excluded.description, starts_at=excluded.starts_at, "
                "ends_at=excluded.ends_at, updated_at=excluded.updated_at",
                (
                    block.id,
                    block.title,
                    block.description,
                    block.starts_at.astimezone(ZoneInfo("UTC")).isoformat(),
                    block.ends_at.astimezone(ZoneInfo("UTC")).isoformat(),
                    now,
                    now,
                ),
            )
        connection.commit()
    return len(blocks)
