"""Cache HTTP em SQLite (``~/.cache/errei/http.sqlite``)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_TTL = 30 * 24 * 3600


class HttpCache:
    def __init__(self, path: Path | None, ttl: float = DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS http ("
                "key TEXT PRIMARY KEY, status INTEGER, body TEXT, ts REAL)"
            )
            self._db.commit()
        except (OSError, sqlite3.Error):
            self._db = None  # cache é opcional

    def get(self, key: str) -> tuple[int, str] | None:
        if self._db is None:
            return None
        with self._lock:
            try:
                row = self._db.execute(
                    "SELECT status, body, ts FROM http WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                return None
        if row is None or time.time() - float(row[2]) > self.ttl:
            return None
        return int(row[0]), str(row[1])

    def put(self, key: str, status: int, body: str) -> None:
        if self._db is None:
            return
        with self._lock:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO http (key, status, body, ts) VALUES (?, ?, ?, ?)",
                    (key, status, body, time.time()),
                )
                self._db.commit()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.close()
                self._db = None
