"""SQLite storage: listings, events, checks and a few settings."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .search import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    city INTEGER,
    bedrooms INTEGER,
    contract INTEGER,
    furnishing INTEGER,
    active INTEGER NOT NULL DEFAULT 0,
    misses INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    listed_at TEXT,
    last_seen TEXT,
    gone_at TEXT
);
CREATE INDEX IF NOT EXISTS listings_active ON listings(active, status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    listing_id INTEGER,
    status TEXT,
    price REAL,
    detail TEXT,
    notified INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_at ON events(at);
CREATE TABLE IF NOT EXISTS checks (
    at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    ms INTEGER,
    found INTEGER,
    requests INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS checks_at ON checks(at);
CREATE TABLE IF NOT EXISTS buildings (
    street TEXT PRIMARY KEY,
    city INTEGER,
    homes INTEGER NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
VERSION = 1
ALERT_KINDS = ("new", "back", "bookable", "price", "lottery")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def to_listing(row) -> Listing:
    return Listing(id=row["id"], name=row["name"], slug=row["slug"], url=row["url"], price=row["price"],
                   status=row["status"], city=row["city"], bedrooms=row["bedrooms"],
                   contract=row["contract"], furnishing=row["furnishing"])


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.executescript(SCHEMA)
            self.db.execute(f"PRAGMA user_version={VERSION}")

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            return self.db.execute(sql, args).lastrowid

    @contextmanager
    def transaction(self):
        """All or nothing: a crash halfway never leaves a home without its alert."""
        with self.lock:
            self.db.execute("BEGIN")
            try:
                yield
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")

    # Settings

    def get(self, key: str, default=None):
        rows = self.q("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value) -> None:
        self.x("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))

    # Listings

    def listing(self, pid: int) -> sqlite3.Row | None:
        rows = self.q("SELECT * FROM listings WHERE id=?", (pid,))
        return rows[0] if rows else None

    def active(self, status: str) -> dict[int, sqlite3.Row]:
        return {r["id"]: r for r in self.q("SELECT * FROM listings WHERE active=1 AND status=?", (status,))}

    def activate(self, x: Listing, now: datetime, new_period: bool) -> None:
        with self.lock:
            row = self.listing(x.id)
            if row is None:
                self.x("""INSERT INTO listings(id, slug, name, url, price, status, city, bedrooms, contract,
                          furnishing, active, misses, first_seen, listed_at, last_seen)
                          VALUES(?,?,?,?,?,?,?,?,?,?,1,0,?,?,?)""",
                       (x.id, x.slug, x.name, x.url, x.price, x.status, x.city, x.bedrooms, x.contract,
                        x.furnishing, iso(now), iso(now) if new_period else None, iso(now)))
                return
            listed_at = iso(now) if new_period else row["listed_at"]
            self.x("""UPDATE listings SET slug=?, name=?, url=?, price=?, status=?, active=1, misses=0,
                      listed_at=?, last_seen=?, gone_at=NULL,
                      city=COALESCE(?, city), bedrooms=COALESCE(?, bedrooms),
                      contract=COALESCE(?, contract), furnishing=COALESCE(?, furnishing)
                      WHERE id=?""",
                   (x.slug, x.name, x.url, x.price, x.status, listed_at, iso(now), x.city, x.bedrooms,
                    x.contract, x.furnishing, x.id))

    def missed(self, pid: int, misses: int) -> None:
        self.x("UPDATE listings SET misses=? WHERE id=?", (misses, pid))

    def gone(self, pid: int, now: datetime) -> None:
        self.x("UPDATE listings SET active=0, misses=0, gone_at=? WHERE id=?", (iso(now), pid))

    def retire(self, pid: int) -> None:
        """No longer matches the search (filters changed). Not the same as taken."""
        self.x("UPDATE listings SET active=0, misses=0, listed_at=NULL WHERE id=?", (pid,))

    def details(self, x: Listing) -> None:
        self.x("""UPDATE listings SET city=COALESCE(?, city), bedrooms=COALESCE(?, bedrooms),
                  contract=COALESCE(?, contract), furnishing=COALESCE(?, furnishing) WHERE id=?""",
               (x.city, x.bedrooms, x.contract, x.furnishing, x.id))

    def known_details(self, x: Listing) -> None:
        row = self.listing(x.id)
        if row:
            for attr in ("city", "bedrooms", "contract", "furnishing"):
                if getattr(x, attr) is None and row[attr] is not None:
                    setattr(x, attr, row[attr])

    # Events

    def event(self, kind: str, listing_id: int | None, status: str | None = None, price: float | None = None,
              detail: str | None = None, at: datetime | None = None, notified: bool | None = None) -> int:
        if notified is None:
            notified = kind not in ALERT_KINDS
        return self.x("INSERT INTO events(at, kind, listing_id, status, price, detail, notified) VALUES(?,?,?,?,?,?,?)",
                      (iso(at or utcnow()), kind, listing_id, status, price, detail, int(notified)))

    def pending(self, since: datetime) -> list[sqlite3.Row]:
        """Unsent alerts, oldest first. Building notices have no listing, so a LEFT JOIN."""
        return self.q("""SELECT e.id AS event_id, e.kind, e.at, e.status AS event_status, e.price AS event_price,
                         e.detail, e.attempts, l.* FROM events e LEFT JOIN listings l ON l.id = e.listing_id
                         WHERE e.notified=0 AND e.at >= ? ORDER BY e.id""", (iso(since),))

    def expire(self, before: datetime) -> int:
        """Give up on alerts that could not be sent for too long."""
        with self.lock:
            return self.db.execute("UPDATE events SET notified=1 WHERE notified=0 AND at < ?",
                                   (iso(before),)).rowcount

    def mark_sent(self, event_ids: list[int]) -> None:
        with self.lock:
            self.db.executemany("UPDATE events SET notified=1 WHERE id=?", [(i,) for i in event_ids])

    def mark_failed(self, event_ids: list[int]) -> None:
        with self.lock:
            self.db.executemany("UPDATE events SET attempts=attempts+1 WHERE id=?", [(i,) for i in event_ids])

    # Checks

    def check(self, ok: bool, ms: int, found: int | None, requests: int, error: str | None = None) -> None:
        self.x("INSERT INTO checks(at, ok, ms, found, requests, error) VALUES(?,?,?,?,?,?)",
               (iso(utcnow()), int(ok), ms, found, requests, error))

    def prune(self, days: int = 30) -> None:
        cutoff = iso(utcnow() - timedelta(days=days))
        self.x("DELETE FROM checks WHERE at < ?", (cutoff,))

    # Buildings

    def building(self, street: str, city: int | None, homes: int, now: datetime) -> bool:
        """Record a building; True when it was not known before."""
        with self.lock:
            known = self.q("SELECT homes FROM buildings WHERE street=?", (street,))
            if known:
                self.x("UPDATE buildings SET homes=MAX(homes, ?), city=COALESCE(city, ?) WHERE street=?",
                       (homes, city, street))
                return False
            self.x("INSERT INTO buildings(street, city, homes, first_seen) VALUES(?,?,?,?)",
                   (street, city, homes, iso(now)))
            return True
