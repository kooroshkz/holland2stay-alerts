from __future__ import annotations

import fnmatch
from datetime import UTC, datetime, timedelta

import pytest

from h2s_alerts.config import build
from h2s_alerts.store import Store

FIELDS = {
    "available_to_book": "status",
    "entity_id": "id",
    "no_of_rooms": "bedrooms",
    "type_of_contract": "contract",
    "maximum_number_of_persons": "occupants",
    "finishing": "furnishing",
}


def home(pid: int, name: str | None = None, *, status: int = 179, city: int = 29, bedrooms: int = 104,
         contract: int = 21, furnishing: int = 6261, occupants: int = 22, price: float = 1200.0,
         sku: str | None = None, start: str = "2026-12-01 00:00:00") -> dict:
    return {"id": pid, "name": name or f"Teststraat {pid}", "url_key": f"teststraat-{pid}", "status": status,
            "city": city, "bedrooms": bedrooms, "contract": contract, "furnishing": furnishing,
            "occupants": occupants, "price": price, "sku": sku or f"r-tst-{pid}",
            "next_contract_startdate": start}


def _match(p: dict, flt: tuple[str, str, str]) -> bool:
    field, value, cond = flt
    actual = p.get(FIELDS.get(field, field))
    if cond == "eq":
        return str(actual) == value
    if cond == "in":
        return str(actual) in value.split(",")
    if cond == "nin":
        return str(actual) not in value.split(",")
    if cond == "like":
        return fnmatch.fnmatchcase(str(actual), value.replace("%", "*"))
    if cond in ("gteq", "lteq"):
        a, b = (float(actual), float(value)) if field == "price" else (str(actual), value)
        return a >= b if cond == "gteq" else a <= b
    raise AssertionError(cond)


class FakeH2S:
    base_url = "https://www.holland2stay.com"

    def __init__(self, homes: list[dict] | None = None):
        self.db = {h["id"]: h for h in homes or []}
        self.requests = 0
        self.fail: Exception | None = None
        self.calls: list[list] = []

    def add(self, *homes: dict) -> None:
        for h in homes:
            self.db[h["id"]] = h

    def remove(self, *ids: int) -> None:
        for i in ids:
            self.db.pop(i, None)

    def products(self, filters, fields, page_size=300, page=1, sort=None):
        self.requests += 1
        self.calls.append(filters)
        if self.fail:
            raise self.fail
        rows = [p for p in self.db.values() if all(_match(p, f) for f in filters)]
        rows.sort(key=lambda p: p["id"], reverse=bool(sort and sort[1] == "DESC"))
        rows = rows[(page - 1) * page_size: page * page_size]
        return [{"id": p["id"], "name": p["name"], "url": f"https://account.holland2stay.com/{p['url_key']}.html",
                 "price_info": {"final_price": p["price"]}} for p in rows]

    def buckets(self, filters):
        self.requests += 1
        if self.fail:
            raise self.fail
        counts: dict[int, int] = {}
        for p in self.db.values():
            if all(_match(p, f) for f in filters):
                counts[p["city"]] = counts.get(p["city"], 0) + 1
        return {"city_bucket": counts}


class FakeNotifier:
    def __init__(self, ok: bool = True):
        self.sent: list[tuple[str, str]] = []
        self.ok = ok
        self.invalid: list[str] = []
        self.enabled = True

    def send(self, title, body):
        if self.ok:
            self.sent.append((title, body))
        return self.ok

    def titles(self) -> list[str]:
        return [t for t, _ in self.sent]


class Clock:
    def __init__(self, start: datetime | None = None):
        # a Tuesday at 10:00 in Amsterdam (08:00 UTC in winter time)
        self.now = start or datetime(2026, 11, 3, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw) -> datetime:
        self.now += timedelta(**kw)
        return self.now


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def make_cfg(tmp_path):
    def make(search: dict | None = None, notify: dict | None = None, **general):
        raw = {"search": search or {"cities": ["Eindhoven"]}, "notify": notify or {},
               "general": {"data_dir": str(tmp_path), **general}}
        return build(raw, {})
    return make
