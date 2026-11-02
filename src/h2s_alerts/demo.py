"""Sample data so the dashboard can be tried without contacting Holland2Stay."""

from __future__ import annotations

import json
import random
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from .config import Config, Search
from .dashboard import overview, static_file
from .search import Listing
from .store import Store, iso, utcnow

STREETS = ["Parklaan", "Kanaalstraat", "Stationsplein", "Molenweg", "Havenkade", "Lindelaan",
           "Torenstraat", "Brugstraat", "Singelpark", "Vondelkade", "Lichttoren", "Dijkgraaf"]
CITIES = [29, 25, 24]
PRICES = {104: (780, 1250), 6137: (1150, 1650), 105: (1250, 1795)}
DEMO_URL = "https://www.holland2stay.com/residences"


def demo_config() -> Config:
    cfg = Config()
    cfg.search = Search(cities=CITIES, bedrooms=list(PRICES), price_max=1800, contracts=[21, 6125, 20])
    return cfg


def _home(rng: random.Random, pid: int, status: str = "available") -> Listing:
    bedrooms = rng.choice(list(PRICES))
    lo, hi = PRICES[bedrooms]
    street = rng.choice(STREETS)
    return Listing(id=pid, name=f"{street} {rng.randint(1, 240)}{rng.choice(['', '', '-A', '-B', ' K2'])}",
                   slug="", url=DEMO_URL, price=float(rng.randrange(lo, hi, 5)), status=status,
                   city=rng.choice(CITIES), bedrooms=bedrooms, contract=rng.choice([21, 21, 21, 6125]),
                   furnishing=rng.choice([70, 6261, 6261, 72]))


def _release_time(rng: random.Random, days_ago: int):
    now = utcnow()
    day = now - timedelta(days=days_ago)
    if rng.random() < 0.2:
        hour, minute = 22, rng.randint(15, 22)  # 00:15 in Amsterdam is 22:15 or 23:15 UTC
    else:
        hour = rng.choice([7, 7, 8, 8, 8, 10, 10, 11, 13, 13, 14, 15])
        minute = rng.randint(0, 59)
    t = day.replace(hour=hour, minute=minute, second=rng.randint(0, 59), microsecond=0)
    while t.weekday() >= 5 and rng.random() < 0.85:
        t -= timedelta(days=1)
    return min(t, now - timedelta(minutes=3))


def fill(store: Store, seed: int = 7) -> None:
    rng = random.Random(seed)
    now = utcnow()
    pid = 1000
    history = []
    for days_ago in range(30, 0, -1):
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            pid += 1
            history.append((_release_time(rng, days_ago), _home(rng, pid)))
    history.sort(key=lambda h: h[0])
    for at, x in history:
        store.activate(x, at, new_period=True)
        store.event("new", x.id, "available", x.price, at=at, notified=True)
        minutes = int(rng.choice([rng.uniform(1, 15), rng.uniform(10, 90), rng.uniform(60, 600)]))
        gone = at + timedelta(minutes=minutes)
        if gone < now:
            store.x("UPDATE listings SET last_seen=? WHERE id=?", (iso(gone), x.id))
            store.gone(x.id, gone)
            store.event("gone", x.id, "available", x.price, str(minutes * 60), at=gone)

    for minutes_ago in (4, 38, 95, 180, 260, 410):
        pid += 1
        x = _home(rng, pid)
        at = now - timedelta(minutes=minutes_ago)
        store.activate(x, at, new_period=True)
        store.event("new", x.id, "available", x.price, at=at, notified=True)
    back = _home(rng, pid + 1)
    store.activate(back, now - timedelta(minutes=22), new_period=True)
    store.event("back", back.id, "available", back.price, at=now - timedelta(minutes=22), notified=True)
    pid += 2
    for i in range(3):
        x = _home(rng, pid + i, "lottery")
        store.activate(x, now - timedelta(days=2), new_period=True)
        store.event("lottery", x.id, "lottery", x.price, at=now - timedelta(days=2), notified=True)

    first = now - timedelta(days=60)
    store.building("Oude Haven", 25, 40, first)  # learned on the first scan, hidden
    store.building("Noorderpark", 24, 96, now - timedelta(days=9))
    store.building("Strijp Laan", 29, 34, now - timedelta(days=3))
    store.event("building", None, detail=json.dumps({"street": "Strijp Laan", "city": 29, "homes": 34}),
                at=now - timedelta(days=3))
    store.set("status", {"state": "watching", "message": "", "last_check": iso(now),
                         "next_check": iso(now + timedelta(seconds=97)), "window": "release hours"})


def sample(seed: int = 7) -> tuple[Store, Config]:
    store = Store(":memory:")
    fill(store, seed)
    return store, demo_config()


def export(directory: Path, seed: int = 7) -> Path:
    """Write a static copy of the dashboard with sample data (used for the website demo)."""
    store, cfg = sample(seed)
    data = overview(store, cfg)
    data["demo"] = True
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "api").mkdir(exist_ok=True)
    for name in ("index.html", "app.css", "app.js", "favicon.svg"):
        (directory / name).write_bytes(static_file(name))
    (directory / "api" / "overview.json").write_text(json.dumps(data), encoding="utf-8")
    return directory


def temp_store(seed: int = 7) -> tuple[Store, Config, Path]:
    folder = Path(tempfile.mkdtemp(prefix="h2s-demo-"))
    store = Store(folder / "demo.sqlite3")
    fill(store, seed)
    return store, demo_config(), folder


def cleanup(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)

