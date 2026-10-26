from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


MIGRATIONS = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 40),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            author_id TEXT,
            author_name TEXT NOT NULL,
            text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 2000),
            created_at TEXT NOT NULL,
            is_ai INTEGER NOT NULL DEFAULT 0 CHECK(is_ai IN (0, 1)),
            reply_to TEXT REFERENCES chat_messages(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS media (
            id TEXT PRIMARY KEY,
            author_id TEXT,
            author_name TEXT NOT NULL,
            caption TEXT,
            original_path TEXT NOT NULL UNIQUE,
            thumbnail_path TEXT,
            vision_path TEXT,
            media_type TEXT NOT NULL,
            byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
            width INTEGER,
            height INTEGER,
            duration_seconds REAL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS media_comments (
            id TEXT PRIMARY KEY,
            media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
            author_id TEXT,
            author_name TEXT NOT NULL,
            text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 2000),
            created_at TEXT NOT NULL,
            is_ai INTEGER NOT NULL DEFAULT 0 CHECK(is_ai IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS schedule_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
            description TEXT,
            starts_at TEXT NOT NULL,
            ends_at TEXT,
            location TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_media_created ON media(created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_comments_media_created
            ON media_comments(media_id, created_at ASC, id ASC);
        CREATE INDEX IF NOT EXISTS idx_schedule_starts ON schedule_events(starts_at ASC, id ASC);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS citation_comments (
            id TEXT PRIMARY KEY,
            citation_id TEXT NOT NULL CHECK(length(citation_id) BETWEEN 1 AND 64),
            author_id TEXT NOT NULL REFERENCES users(id),
            author_name TEXT NOT NULL CHECK(length(author_name) BETWEEN 1 AND 40),
            text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 2000),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_citation_comments_created
            ON citation_comments(citation_id, created_at ASC, id ASC);
        """,
    ),
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                connection.executescript(sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
                )
            connection.commit()

    def health(self) -> dict[str, Any]:
        with self.connection() as connection:
            connection.execute("SELECT 1").fetchone()
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        return {"status": "ok", "journal_mode": journal_mode}

    def media_bytes(self) -> int:
        with self.connection() as connection:
            row = connection.execute("SELECT COALESCE(SUM(byte_size), 0) FROM media").fetchone()
        return int(row[0])

    def latest_chat(self, limit: int) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, author_id, author_name, text, created_at, is_ai, reply_to "
                "FROM (SELECT * FROM chat_messages ORDER BY created_at DESC, id DESC LIMIT ?) "
                "ORDER BY created_at ASC, id ASC",
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def chat_before(self, message_id: str, limit: int) -> list[dict[str, Any]]:
        with self.connection() as connection:
            source = connection.execute(
                "SELECT created_at, id FROM chat_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
            if source is None:
                return []
            rows = connection.execute(
                "SELECT id, author_id, author_name, text, created_at, is_ai, reply_to "
                "FROM chat_messages WHERE (created_at, id) < (?, ?) "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (source["created_at"], source["id"], limit),
            ).fetchall()
        return [self._row(row) for row in reversed(rows)]

    def chat_page(self, limit: int, before_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if before_id is None:
                rows = connection.execute(
                    "SELECT id, author_id, author_name, text, created_at, is_ai, reply_to "
                    "FROM chat_messages ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                cursor = connection.execute(
                    "SELECT created_at, id FROM chat_messages WHERE id = ?", (before_id,)
                ).fetchone()
                if cursor is None:
                    return []
                rows = connection.execute(
                    "SELECT id, author_id, author_name, text, created_at, is_ai, reply_to "
                    "FROM chat_messages WHERE (created_at, id) < (?, ?) "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (cursor["created_at"], cursor["id"], limit),
                ).fetchall()
        return [self._row(row) for row in rows]

    def create_chat(
        self,
        browser_id: str,
        author: str,
        text: str,
        reply_to: str | None,
        *,
        is_ai: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        message_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO users(id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
                "updated_at=excluded.updated_at",
                (browser_id, author, now, now),
            )
            connection.execute(
                "INSERT INTO chat_messages(id, author_id, author_name, text, created_at, is_ai, reply_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, browser_id, author, text, now, int(is_ai), reply_to),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, author_id, author_name, text, created_at, is_ai, reply_to "
                "FROM chat_messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        return self._row(row)

    def latest_media(self, limit: int) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT m.id, m.author_id, m.author_name, m.caption, m.media_type, "
                "m.original_path, m.thumbnail_path, m.vision_path, m.byte_size, "
                "m.width, m.height, m.duration_seconds, m.created_at, "
                "COUNT(c.id) AS comment_count "
                "FROM media AS m LEFT JOIN media_comments AS c ON c.media_id = m.id "
                "GROUP BY m.id ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def media_page(self, limit: int, before_id: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as connection:
            parameters: tuple[Any, ...]
            where = ""
            if before_id is None:
                parameters = (limit,)
            else:
                cursor = connection.execute(
                    "SELECT created_at, id FROM media WHERE id = ?", (before_id,)
                ).fetchone()
                if cursor is None:
                    return []
                where = "WHERE (m.created_at, m.id) < (?, ?)"
                parameters = (cursor["created_at"], cursor["id"], limit)
            rows = connection.execute(
                "SELECT m.id, m.author_id, m.author_name, m.caption, m.media_type, "
                "m.original_path, m.thumbnail_path, m.vision_path, m.byte_size, "
                "m.width, m.height, m.duration_seconds, m.created_at, "
                "COUNT(c.id) AS comment_count "
                "FROM media AS m LEFT JOIN media_comments AS c ON c.media_id = m.id "
                f"{where} GROUP BY m.id ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._row(row) for row in rows]

    def create_media(self, item: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO users(id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
                "updated_at=excluded.updated_at",
                (item["author_id"], item["author_name"], now, now),
            )
            connection.execute(
                "INSERT INTO media(id, author_id, author_name, caption, original_path, "
                "thumbnail_path, vision_path, media_type, byte_size, width, height, "
                "duration_seconds, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"],
                    item["author_id"],
                    item["author_name"],
                    item["caption"],
                    item["original_path"],
                    item["thumbnail_path"],
                    item["vision_path"],
                    item["media_type"],
                    item["byte_size"],
                    item["width"],
                    item["height"],
                    item["duration_seconds"],
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT m.id, m.author_id, m.author_name, m.caption, m.media_type, "
                "m.original_path, m.thumbnail_path, m.vision_path, m.byte_size, "
                "m.width, m.height, m.duration_seconds, m.created_at, 0 AS comment_count "
                "FROM media AS m WHERE m.id = ?",
                (item["id"],),
            ).fetchone()
        return self._row(row)

    def media_exists(self, media_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute("SELECT 1 FROM media WHERE id = ?", (media_id,)).fetchone()
        return row is not None

    def comment_page(
        self,
        media_id: str,
        limit: int,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.connection() as connection:
            if before_id is None:
                rows = connection.execute(
                    "SELECT id, media_id, author_id, author_name, text, created_at, is_ai "
                    "FROM media_comments WHERE media_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (media_id, limit),
                ).fetchall()
            else:
                cursor = connection.execute(
                    "SELECT created_at, id FROM media_comments WHERE id = ? AND media_id = ?",
                    (before_id, media_id),
                ).fetchone()
                if cursor is None:
                    return []
                rows = connection.execute(
                    "SELECT id, media_id, author_id, author_name, text, created_at, is_ai "
                    "FROM media_comments WHERE media_id = ? AND (created_at, id) < (?, ?) "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (media_id, cursor["created_at"], cursor["id"], limit),
                ).fetchall()
        return [self._row(row) for row in rows]

    def create_comment(
        self,
        media_id: str,
        browser_id: str,
        author: str,
        text: str,
        *,
        is_ai: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        comment_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO users(id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
                "updated_at=excluded.updated_at",
                (browser_id, author, now, now),
            )
            connection.execute(
                "INSERT INTO media_comments(id, media_id, author_id, author_name, text, created_at, is_ai) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (comment_id, media_id, browser_id, author, text, now, int(is_ai)),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, media_id, author_id, author_name, text, created_at, is_ai "
                "FROM media_comments WHERE id = ?",
                (comment_id,),
            ).fetchone()
        return self._row(row)

    def citation_comments(self, citation_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, citation_id, author_id, author_name, text, created_at "
                "FROM citation_comments WHERE citation_id = ? ORDER BY created_at ASC, id ASC",
                (citation_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def citation_comment_counts(self) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT citation_id, COUNT(*) AS total FROM citation_comments GROUP BY citation_id"
            ).fetchall()
        return {row["citation_id"]: int(row["total"]) for row in rows}

    def create_citation_comment(
        self, citation_id: str, browser_id: str, author: str, text: str
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        comment_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO users(id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
                "updated_at=excluded.updated_at",
                (browser_id, author, now, now),
            )
            connection.execute(
                "INSERT INTO citation_comments(id, citation_id, author_id, author_name, text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (comment_id, citation_id, browser_id, author, text, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, citation_id, author_id, author_name, text, created_at "
                "FROM citation_comments WHERE id = ?",
                (comment_id,),
            ).fetchone()
        return self._row(row)

    def schedule_all(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, title, description, starts_at, ends_at, location, created_at, updated_at "
                "FROM schedule_events ORDER BY starts_at ASC, id ASC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def create_schedule(self, item: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO schedule_events(id, title, description, starts_at, ends_at, "
                "location, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    item["title"],
                    item["description"],
                    item["starts_at"],
                    item["ends_at"],
                    item["location"],
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id, title, description, starts_at, ends_at, location, created_at, updated_at "
                "FROM schedule_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return self._row(row)

    def update_schedule(self, event_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            cursor = connection.execute(
                "UPDATE schedule_events SET title = ?, description = ?, starts_at = ?, "
                "ends_at = ?, location = ?, updated_at = ? WHERE id = ?",
                (
                    item["title"],
                    item["description"],
                    item["starts_at"],
                    item["ends_at"],
                    item["location"],
                    now,
                    event_id,
                ),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT id, title, description, starts_at, ends_at, location, created_at, updated_at "
                "FROM schedule_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return self._row(row)

    def delete_schedule(self, event_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,))
            connection.commit()
        return cursor.rowcount > 0

    def get_media_files(self, media_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT original_path, thumbnail_path, vision_path FROM media WHERE id = ?",
                (media_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_media(self, media_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM media WHERE id = ?", (media_id,))
            connection.commit()
        return cursor.rowcount > 0

    def get_media(self, media_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id, author_id, author_name, caption, original_path, thumbnail_path, "
                "vision_path, media_type, byte_size, width, height, duration_seconds, created_at "
                "FROM media WHERE id = ?",
                (media_id,),
            ).fetchone()
        return self._row(row) if row else None

    def upcoming_schedule(self, now_utc: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, title, description, starts_at, ends_at, location, created_at, updated_at "
                "FROM schedule_events WHERE COALESCE(ends_at, starts_at) >= ? "
                "ORDER BY starts_at ASC, id ASC LIMIT 100",
                (now_utc,),
            ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        if "is_ai" in item:
            item["is_ai"] = bool(item["is_ai"])
        return item
