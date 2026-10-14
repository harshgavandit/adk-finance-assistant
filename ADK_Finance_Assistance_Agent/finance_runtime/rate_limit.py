"""Atomic fixed-window admission shared by processes using one local SQLite file."""

from dataclasses import dataclass
from contextlib import closing
import hashlib
import math
from pathlib import Path
import sqlite3
import time


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Admission:
    allowed: bool
    remaining: int
    retry_after: int


class LocalRateLimiter:
    def __init__(self, database: Path, limit: int, window: int, clock=time.time):
        if limit <= 0 or window <= 0:
            raise ValueError("Rate limits must be positive.")
        self.database = database
        self.limit = limit
        self.window = window
        self.clock = clock

    def admit(self, scope: str) -> Admission:
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.database, timeout=5)) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                # Read the clock after the write lock is acquired.
                now = self.clock()
                conn.execute("CREATE TABLE IF NOT EXISTS quota (scope TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)")
                conn.execute("DELETE FROM quota WHERE expires <= ?", (now,))
                row = conn.execute("SELECT count, expires FROM quota WHERE scope = ?", (scope,)).fetchone()
                count, expires = row if row else (0, now + self.window)
                if count >= self.limit:
                    return Admission(False, 0, max(1, math.ceil(expires - now)))
                conn.execute("INSERT OR REPLACE INTO quota VALUES (?, ?, ?)", (scope, count + 1, expires))
                return Admission(True, self.limit - count - 1, 0)
        except (OSError, sqlite3.Error):
            raise RateLimitUnavailable("Local rate limiter is unavailable; model calls are blocked.") from None


def credential_scope(api_key: str) -> str:
    # Store only a hash, never the key, prompt, or personal finance data.
    return hashlib.sha256(api_key.encode()).hexdigest()
