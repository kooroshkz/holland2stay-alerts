"""When to check. All times are Amsterdam time, whatever the server's clock zone is."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import MIN_INTERVAL, Schedule

AMS = ZoneInfo("Europe/Amsterdam")

# Most homes are released on weekdays during office hours, plus a small batch
# just after midnight when unpaid reservations go back on sale.
RELEASE_WINDOWS = [
    (range(0, 5), time(8, 30), time(18, 0)),
    (range(0, 7), time(0, 5), time(0, 45)),
]
DAY = (time(7, 0), time(23, 30))
# New lottery homes go live on Tuesday at 17:00, sometimes a bit later.
LOTTERY_OPENING = (1, time(16, 50), time(18, 30))
LOTTERY_DEADLINE = (6, time(20, 0))


def local(now: datetime | None = None) -> datetime:
    return (now or datetime.now(AMS)).astimezone(AMS)


def _within(t: time, start: time, end: time) -> bool:
    return start <= t < end if start <= end else (t >= start or t < end)


def window(now: datetime | None = None) -> str:
    n = local(now)
    for days, start, end in RELEASE_WINDOWS:
        if n.weekday() in days and _within(n.time(), start, end):
            return "release hours"
    if _within(n.time(), *DAY):
        return "daytime"
    return "night"


def _jitter(seconds: float, amount: float, rng: random.Random | None) -> float:
    r = (rng or random).uniform(1 - amount, 1 + amount)
    return max(MIN_INTERVAL, seconds * r)


def next_delay(s: Schedule, now: datetime | None = None, rng: random.Random | None = None) -> float:
    base = {"release hours": s.hot, "daytime": s.day, "night": s.night}[window(now)]
    return _jitter(base, s.jitter, rng)


def lottery_due_every(s: Schedule, now: datetime | None = None) -> float:
    n = local(now)
    day, start, end = LOTTERY_OPENING
    if n.weekday() == day and _within(n.time(), start, end):
        return max(MIN_INTERVAL, s.hot)
    return max(MIN_INTERVAL, s.lottery)


def lottery_deadline(now: datetime | None = None) -> datetime:
    """The next Sunday 20:00, when lottery sign-ups close."""
    n = local(now)
    day, at = LOTTERY_DEADLINE
    d = n + timedelta(days=(day - n.weekday()) % 7)
    deadline = d.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return deadline if deadline > n else deadline + timedelta(days=7)


def quiet(hours: tuple[time, time] | None, now: datetime | None = None) -> bool:
    return bool(hours) and _within(local(now).time(), *hours)
