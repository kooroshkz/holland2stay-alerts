"""The loop: check, compare, notify, wait. Backs off when Holland2Stay pushes back."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from . import catalog, messages, schedule
from .client import Blocked, Changed, Client, H2SError, RateLimited
from .config import Config
from .notify import Notifier
from .search import Listing, describe, discover_cities, fetch, newest, street_of
from .store import Store, iso, parse, to_listing, utcnow
from .tracker import Result, Tracker

log = logging.getLogger("h2s_alerts")

DISCOVER_EVERY = timedelta(hours=24)
BUILDINGS_EVERY = timedelta(hours=6)
SLOW_FAILURE_NOTICE = timedelta(hours=1)
ALERT_TTL = timedelta(hours=6)   # an alert that can't be sent for this long is dropped
MAX_PAUSE = 6 * 3600


class Watcher:
    def __init__(self, cfg: Config, store: Store, client: Client | None = None,
                 notifier: Notifier | None = None, clock=utcnow, rng: random.Random | None = None):
        self.cfg = cfg
        self.store = store
        self.client = client or Client(cfg.base_url)
        self.notifier = notifier or Notifier(cfg.notify.urls)
        self.tracker = Tracker(store, cfg.search.fingerprint())
        self.clock = clock
        self.rng = rng or random.Random()
        self.stop = threading.Event()

    # Status shown on the dashboard

    def status(self, state: str, message: str = "", next_at: datetime | None = None) -> None:
        current = self.store.get("status", {})
        current.update(state=state, message=message, next_check=iso(next_at) if next_at else None,
                       window=schedule.window(self.clock()))
        self.store.set("status", current)

    # Main loop

    def run(self) -> None:
        self.status("starting")
        while not self.stop.is_set():
            try:
                delay = self.tick()
            except Exception:  # the loop itself must survive anything
                log.exception("Unexpected error")
                delay = 300
            self.stop.wait(delay)
        self.status("stopped")

    def tick(self) -> float:
        now = self.clock()
        pause = parse(self.store.get("pause_until"))
        if pause and now < pause:
            current = self.store.get("status", {})
            if current.get("state") not in ("paused", "retrying"):
                self.status("paused", current.get("message") or "Waiting before the next try", pause)
            self.deliver(now)
            return (pause - now).total_seconds()

        started, before = time.monotonic(), self.client.requests
        try:
            matching = self.check(now)
        except H2SError as e:
            self.store.check(False, self._ms(started), None, self.client.requests - before, str(e))
            delay = self.failed(e, now)
            self.deliver(now)
            return delay
        except Exception as e:
            log.exception("Unexpected error")
            self.store.check(False, self._ms(started), None, self.client.requests - before, repr(e))
            self.status("retrying", "Something went wrong, see the logs", now + timedelta(minutes=5))
            self.deliver(now)
            return 300

        self.store.check(True, self._ms(started), matching, self.client.requests - before)
        self.store.set("status", {**self.store.get("status", {}), "last_check": iso(now)})
        self.recovered(now)
        self.deliver(now)
        self.store.prune()
        delay = schedule.next_delay(self.cfg.schedule, now, self.rng)
        self.status("watching", "", now + timedelta(seconds=delay))
        return delay

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def check(self, now: datetime) -> int:
        search = self.cfg.search
        self.discover(now)
        available = self.apply("available", fetch(self.client, search, "available"), now)
        results = [available]
        if available.baseline:
            self.started(available, now)
        if not search.lottery:
            self.lottery_off()
        elif self.due("lottery_checked", now, schedule.lottery_due_every(self.cfg.schedule, now)):
            results.append(self.apply("lottery", fetch(self.client, search, "lottery"), now))
            self.store.set("lottery_checked", iso(now))
        if self.due("buildings_checked", now, BUILDINGS_EVERY.total_seconds()):
            self.buildings(now)
            self.store.set("buildings_checked", iso(now))

        self.details([c.listing for r in results for c in r.changes if c.kind != "gone"])
        kinds: dict[str, int] = defaultdict(int)
        for r in results:
            for c in r.changes:
                kinds[c.kind] += 1
        extra = ", ".join(f"{n} {kind}" for kind, n in kinds.items())
        log.info("%d match%s", available.matching, f" ({extra})" if extra else "")
        return available.matching

    def apply(self, status: str, current: dict[int, Listing], now: datetime) -> Result:
        with self.store.transaction():
            result = self.tracker.apply(status, current, now)
            for c in result.changes:
                self.store.event(c.kind, c.listing.id, status, c.listing.price, c.detail, at=now)
        return result

    def due(self, key: str, now: datetime, every: float) -> bool:
        last = parse(self.store.get(key))
        return last is None or (now - last).total_seconds() >= every

    def details(self, listings: list[Listing]) -> None:
        """Best effort: an alert without the city is better than no alert."""
        for x in listings:
            self.store.known_details(x)
        need = [x for x in listings if None in (x.city, x.bedrooms, x.contract, x.furnishing)]
        if need:
            extra = [int(c) for c in self.store.get("cities_seen", {})]
            try:
                describe(self.client, need, self.cfg.search, extra)
            except H2SError as e:
                log.info("Couldn't look up all details: %s", e)
        for x in listings:
            self.store.details(x)

    def started(self, r: Result, now: datetime) -> None:
        summary = self.cfg.search.summary()
        if r.filters_changed:
            self.notifier.send(*messages.search_changed(summary, r.matching))
            return
        if self.store.get("welcomed"):
            return
        self.notifier.send(*messages.welcome(summary, r.matching))
        self.store.set("welcomed", iso(now))
        if self.cfg.notify.existing_on_start and r.matching:
            for row in self.store.active("available").values():
                self.store.event("new", row["id"], "available", row["price"], at=now)
            self.details([to_listing(row) for row in self.store.active("available").values()])

    def lottery_off(self) -> None:
        active = self.store.active("lottery")
        if active:
            for pid in active:
                self.store.retire(pid)
            self.store.set("baseline:lottery", None)

    def discover(self, now: datetime) -> None:
        if not self.due("cities_checked", now, DISCOVER_EVERY.total_seconds()):
            return
        try:
            seen = discover_cities(self.client)
        except Changed as e:
            log.debug("City discovery skipped: %s", e)
            seen = {}
        self.store.set("cities_seen", {str(k): v for k, v in seen.items()})
        self.store.set("cities_checked", iso(now))

    def buildings(self, now: datetime) -> None:
        last = self.store.get("newest_id")
        try:
            top, fresh = newest(self.client, self.cfg.search, last or 0)
        except H2SError as e:
            log.info("Skipped the new building check: %s", e)
            return
        self.store.set("newest_id", top)
        groups: dict[str, list[int]] = defaultdict(list)
        for row in fresh:
            groups[street_of(row["name"])].append(row["id"])
        new_streets = [(street, ids) for street, ids in groups.items()
                       if self.store.building(street, None, len(ids), now) and last is not None]
        if not new_streets:
            return
        reps = [Listing(id=ids[0], name=street, slug="", url="", price=None, status="")
                for street, ids in new_streets]
        extra = [int(c) for c in self.store.get("cities_seen", {})]
        try:
            describe(self.client, reps, self.cfg.search, extra, budget=12)
        except H2SError as e:
            log.info("Couldn't look up where the new buildings are: %s", e)
        for (street, ids), rep in zip(new_streets, reps, strict=True):
            self.store.building(street, rep.city, len(ids), now)
            detail = json.dumps({"street": street, "city": rep.city, "homes": len(ids)})
            self.store.event("building", None, detail=detail, at=now, notified=False)

    # Notifications

    def deliver(self, now: datetime) -> None:
        try:
            self._deliver(now)
        except Exception:
            log.exception("Delivering alerts failed")

    def _deliver(self, now: datetime) -> None:
        if schedule.quiet(self.cfg.notify.quiet_hours, now):
            return
        dropped = self.store.expire(now - ALERT_TTL)
        if dropped:
            log.warning("Dropped %d alert%s that couldn't be sent for hours", dropped, "s" if dropped > 1 else "")
        rows = self.store.pending(now - ALERT_TTL)
        if not rows:
            return
        buildings = [r for r in rows if r["kind"] == "building"]
        rows = [r for r in rows if r["kind"] != "building"]
        stale = [r["event_id"] for r in rows if not r["active"]]
        if stale:
            self.store.mark_sent(stale)  # taken while we waited, nothing to act on
        rows = [r for r in rows if r["active"]]
        lottery = [r for r in rows if r["kind"] == "lottery"]
        others = [r for r in rows if r["kind"] != "lottery"]
        for group in (others, lottery):
            if not group:
                continue
            if len(group) > self.cfg.notify.digest_after:
                title, body = messages.digest([(r["kind"], to_listing(r)) for r in group], now)
                self._sent([r["event_id"] for r in group], self.notifier.send(title, body))
            else:
                for r in group:
                    title, body = messages.alert(r["kind"], to_listing(r), r["detail"], now)
                    self._sent([r["event_id"]], self.notifier.send(title, body))
        for r in buildings:
            info = json.loads(r["detail"])
            title, body = messages.building(info["street"], catalog.city_label(info["city"]), info["homes"])
            self._sent([r["event_id"]], self.notifier.send(title, body))

    def _sent(self, ids: list[int], ok: bool) -> None:
        (self.store.mark_sent if ok else self.store.mark_failed)(ids)

    # Trouble

    def failed(self, e: H2SError, now: datetime) -> float:
        n = int(self.store.get("failures", 0)) + 1
        self.store.set("failures", n)
        since = parse(self.store.get("failing_since")) or now
        self.store.set("failing_since", iso(since))
        if isinstance(e, RateLimited):
            delay = e.retry_after or 300 * 2 ** (n - 1)
            delay = min(delay, 3600 if not e.retry_after else MAX_PAUSE)
        elif isinstance(e, Blocked):
            delay = min(MAX_PAUSE, 1800 * 2 ** (n - 1))
        elif isinstance(e, Changed):
            delay = min(MAX_PAUSE, 900 * 2 ** (n - 1))
        else:
            delay = min(900, 60 * 2 ** (n - 1))
        delay = max(60.0, float(delay))
        until = now + timedelta(seconds=delay)
        self.store.set("pause_until", iso(until))
        self.status("paused" if isinstance(e, Blocked | RateLimited) else "retrying", str(e), until)
        log.warning("%s. Next try at %s", e, f"{schedule.local(until):%H:%M}")

        serious = isinstance(e, Blocked | Changed) or (isinstance(e, RateLimited) and delay >= 900)
        if (self.cfg.notify.health and not self.store.get("health_notified")
                and (serious or now - since >= SLOW_FAILURE_NOTICE)
                and not schedule.quiet(self.cfg.notify.quiet_hours, now)):
            msg = messages.broken(str(e)) if isinstance(e, Changed) else messages.paused(str(e), until)
            if self.notifier.send(*msg):
                self.store.set("health_notified", True)
        return delay

    def recovered(self, now: datetime) -> None:
        if not self.store.get("failures"):
            return
        if (self.store.get("health_notified") and self.cfg.notify.health
                and not schedule.quiet(self.cfg.notify.quiet_hours, now)):
            self.notifier.send(*messages.resumed())
        for key in ("failures", "failing_since", "health_notified", "pause_until"):
            self.store.set(key, None)
        log.info("Holland2Stay answers again")
