"""Decide what changed between two checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .search import Listing
from .store import Store, parse, to_listing

MISSES_TO_GONE = 2          # one odd answer must never mark a home as taken
MISSES_IF_ALL_GONE = 3      # an empty answer after many homes is more likely a glitch
FLICKER = timedelta(minutes=5)
PRICE_STEP = 1.0            # ignore rounding noise


@dataclass
class Change:
    kind: str               # new, back, bookable, lottery, price, gone
    listing: Listing
    detail: str | None = None


@dataclass
class Result:
    status: str
    changes: list[Change] = field(default_factory=list)
    baseline: bool = False
    filters_changed: bool = False
    matching: int = 0


class Tracker:
    def __init__(self, store: Store, fingerprint: str):
        self.store = store
        self.fingerprint = fingerprint

    def apply(self, status: str, current: dict[int, Listing], now: datetime) -> Result:
        store = self.store
        result = Result(status=status, matching=len(current))
        key = f"baseline:{status}"
        known = store.get(key)
        active = store.active(status)

        if known != self.fingerprint:
            # First run or new filters: take what matches now as the starting point, quietly.
            result.baseline = True
            result.filters_changed = known is not None
            for pid in active:
                if pid not in current:
                    store.retire(pid)
            for x in current.values():
                # start unknown, so it does not count towards time on market
                row = store.listing(x.id)
                if row is not None and not row["active"]:
                    store.retire(x.id)
                store.activate(x, now, new_period=False)
            store.set(key, self.fingerprint)
            return result

        for pid, x in current.items():
            row = active.get(pid) or store.listing(pid)
            if pid in active:
                old = row["price"]
                if old is not None and x.price is not None and x.price < old - PRICE_STEP:
                    result.changes.append(Change("price", x, f"{old:.0f}"))
                store.activate(x, now, new_period=False)
                continue

            if row is None:
                kind = "lottery" if status == "lottery" else "new"
            elif row["active"] and row["status"] != status:
                kind = "bookable" if status == "available" else "lottery"
            elif row["gone_at"] and now - parse(row["gone_at"]) < FLICKER:
                kind = None
            elif row["gone_at"]:
                kind = "lottery" if status == "lottery" else "back"
            else:
                kind = "lottery" if status == "lottery" else "new"
            store.activate(x, now, new_period=kind is not None)
            if kind:
                result.changes.append(Change(kind, x))

        need = MISSES_IF_ALL_GONE if not current and len(active) >= 5 else MISSES_TO_GONE
        for pid, row in active.items():
            if pid in current:
                continue
            misses = row["misses"] + 1
            if misses < need:
                store.missed(pid, misses)
                continue
            store.gone(pid, now)
            listed = parse(row["listed_at"])
            # last_seen is the last time it was there, so that is when it went
            seen = parse(row["last_seen"]) or now
            duration = str(int((seen - listed).total_seconds())) if listed else None
            result.changes.append(Change("gone", to_listing(row), duration))
        return result
