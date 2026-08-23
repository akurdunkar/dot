"""SQLite-backed clipboard history.

Entries are deduplicated by content hash: re-copying known content bumps
its recency instead of inserting a duplicate. Pinned entries are immortal;
unpinned ones are pruned oldest-first past the configured cap. Image bytes
(`data`) stay in the database and are fetched lazily via `data()`; listing
only carries the small thumbnail.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

KIND_TEXT = "text"
KIND_IMAGE = "image"
KIND_URIS = "uris"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    text TEXT NOT NULL DEFAULT '',
    data BLOB,
    thumb BLOB,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_order ON entries (pinned DESC, last_used_at DESC);
"""

_LIST_COLS = "id, kind, text, thumb, width, height, pinned, created_at, last_used_at"


@dataclass(frozen=True, slots=True)
class Entry:
    id: int
    kind: str
    text: str  # content for text/uris kinds; empty for images
    thumb: bytes | None
    width: int
    height: int
    pinned: bool
    created_at: float
    last_used_at: float

    @property
    def preview(self) -> str:
        """Single-line human preview, also the fuzzy-search haystack for images."""
        if self.kind == KIND_IMAGE:
            return f"Image {self.width}\u00d7{self.height}"
        return self.text


def _row_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        kind=row["kind"],
        text=row["text"],
        thumb=row["thumb"],
        width=row["width"],
        height=row["height"],
        pinned=bool(row["pinned"]),
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
    )


class Store:
    """All access happens on the GLib main thread; no locking needed."""

    def __init__(self, path: Path | str) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def add(
        self,
        kind: str,
        *,
        text: str = "",
        data: bytes | None = None,
        thumb: bytes | None = None,
        width: int = 0,
        height: int = 0,
    ) -> tuple[Entry, bool]:
        """Insert new content or bump a known duplicate. Returns (entry, created)."""
        digest = hashlib.sha256()
        digest.update(kind.encode())
        digest.update(data if data is not None else text.encode())
        content_hash = digest.hexdigest()
        now = time.time()
        with self._db:
            cur = self._db.execute(
                "UPDATE entries SET last_used_at = ? WHERE hash = ? RETURNING " + _LIST_COLS,
                (now, content_hash),
            )
            row = cur.fetchone()
            if row is not None:
                return _row_entry(row), False
            cur = self._db.execute(
                "INSERT INTO entries (kind, hash, text, data, thumb, width, height,"
                " created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " RETURNING " + _LIST_COLS,
                (kind, content_hash, text, data, thumb, width, height, now, now),
            )
            return _row_entry(cur.fetchone()), True

    def entries(self) -> list[Entry]:
        """Pinned first, then most recently used."""
        cur = self._db.execute(
            f"SELECT {_LIST_COLS} FROM entries ORDER BY pinned DESC, last_used_at DESC"
        )
        return [_row_entry(r) for r in cur.fetchall()]

    def get(self, entry_id: int) -> Entry | None:
        cur = self._db.execute(f"SELECT {_LIST_COLS} FROM entries WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        return _row_entry(row) if row is not None else None

    def data(self, entry_id: int) -> bytes | None:
        cur = self._db.execute("SELECT data FROM entries WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        return row["data"] if row is not None else None

    def touch(self, entry_id: int) -> None:
        with self._db:
            self._db.execute(
                "UPDATE entries SET last_used_at = ? WHERE id = ?", (time.time(), entry_id)
            )

    def set_pinned(self, entry_id: int, pinned: bool) -> bool:
        with self._db:
            cur = self._db.execute(
                "UPDATE entries SET pinned = ? WHERE id = ?", (int(pinned), entry_id)
            )
            return cur.rowcount > 0

    def delete(self, entry_id: int) -> bool:
        with self._db:
            return self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def clear_unpinned(self) -> int:
        with self._db:
            return self._db.execute("DELETE FROM entries WHERE pinned = 0").rowcount

    def prune(self, cap: int) -> int:
        """Drop the oldest unpinned entries beyond `cap`."""
        with self._db:
            cur = self._db.execute(
                "DELETE FROM entries WHERE pinned = 0 AND id NOT IN ("
                " SELECT id FROM entries WHERE pinned = 0"
                " ORDER BY last_used_at DESC LIMIT ?)",
                (max(cap, 0),),
            )
            return cur.rowcount

    def count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def close(self) -> None:
        self._db.close()
