"""The words people read: notification titles and bodies."""

from __future__ import annotations

from datetime import datetime

from . import PROJECT_URL, schedule
from .search import Listing

DIGEST_LIMIT = 10


def money(value: float | None) -> str:
    if value is None:
        return ""
    return f"€{value:,.0f}" if value == int(value) else f"€{value:,.2f}"


def facts(x: Listing) -> str:
    return " · ".join(p for p in (x.city_name, x.bedrooms_name, money(x.price)) if p)


def terms(x: Listing) -> str:
    return " · ".join(p for p in (x.contract_name, x.furnishing_name) if p)


def deadline(now: datetime | None = None) -> str:
    return f"Sign up by {schedule.lottery_deadline(now):%a %H:%M}"


TITLES = {
    "new": "{name}",
    "back": "Back: {name}",
    "bookable": "Now bookable: {name}",
    "price": "Price drop: {name}",
    "lottery": "Lottery: {name}",
}


def alert(kind: str, x: Listing, detail: str | None = None, now: datetime | None = None) -> tuple[str, str]:
    lines = [facts(x)]
    if kind == "price" and detail:
        lines = [" · ".join(p for p in (x.city_name, x.bedrooms_name) if p),
                 f"{money(float(detail))} → {money(x.price)}"]
    if terms(x):
        lines.append(terms(x))
    if kind == "lottery":
        lines.append(deadline(now))
    lines.append(x.url)
    return TITLES[kind].format(name=x.name), "\n".join(line for line in lines if line)


def digest(items: list[tuple[str, Listing]], now: datetime | None = None) -> tuple[str, str]:
    lottery = all(kind == "lottery" for kind, _ in items)
    n = len(items)
    if lottery:
        title = f"Lottery: {n} homes match"
    elif all(kind == "new" for kind, _ in items):
        title = f"{n} new homes"
    else:
        title = f"{n} homes to look at"
    blocks = []
    for kind, x in items[:DIGEST_LIMIT]:
        label = "" if kind in ("new", "lottery") else {"back": "Back: ", "bookable": "Now bookable: ",
                                                         "price": "Price drop: "}[kind]
        blocks.append(f"{label}{x.name} · {facts(x)}\n{x.url}")
    if n > DIGEST_LIMIT:
        blocks.append(f"and {n - DIGEST_LIMIT} more")
    if lottery:
        blocks.append(deadline(now))
    return title, "\n\n".join(blocks)


def welcome(summary: str, matching: int) -> tuple[str, str]:
    homes = "1 home matches" if matching == 1 else f"{matching} homes match"
    return "Watching Holland2Stay", f"{summary}\n{homes} right now. You'll get a message when a new one shows up."


def search_changed(summary: str, matching: int) -> tuple[str, str]:
    homes = "1 home matches" if matching == 1 else f"{matching} homes match"
    return "Search updated", f"{summary}\n{homes} right now."


def paused(reason: str, until: datetime) -> tuple[str, str]:
    return "Alerts paused", f"{reason}. Trying again at {schedule.local(until):%H:%M}."


def resumed() -> tuple[str, str]:
    return "Alerts back on", "Holland2Stay answers again."


def broken(reason: str) -> tuple[str, str]:
    return "Alerts may be broken", f"{reason}. Check for an update: {PROJECT_URL}/releases"


def building(street: str, city: str, homes: int) -> tuple[str, str]:
    where = " · ".join(p for p in (city, f"{homes} homes" if homes > 1 else "1 home") if p)
    return f"New building: {street}", f"{where} · not on sale yet"


def test() -> tuple[str, str]:
    return "holland2stay-alerts", "Test message. Notifications work."
