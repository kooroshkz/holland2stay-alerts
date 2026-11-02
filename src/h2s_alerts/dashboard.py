"""Read-only web dashboard. Standard library only."""

from __future__ import annotations

import base64
import hmac
import json
import logging
import statistics
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from . import PROJECT_URL, __version__, catalog, schedule
from .config import Config
from .store import Store, iso, parse, utcnow

log = logging.getLogger("h2s_alerts")

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
ALERTS = ("new", "back", "bookable")


def _row(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "url": r["url"],
        "price": r["price"],
        "city": catalog.city_label(r["city"]) if r["city"] else "",
        "bedrooms": catalog.BEDROOMS.get(r["bedrooms"], "") if r["bedrooms"] else "",
        "contract": catalog.CONTRACTS.get(r["contract"], "") if r["contract"] else "",
        "furnishing": catalog.FURNISHING.get(r["furnishing"], "") if r["furnishing"] else "",
        "since": r["listed_at"] or r["first_seen"],
    }


def overview(store: Store, cfg: Config) -> dict:
    now = utcnow()
    week = iso(now - timedelta(days=7))
    month = iso(now - timedelta(days=30))
    day = iso(now - timedelta(days=1))

    def count(sql: str, args=()) -> int:
        return store.q(sql, args)[0][0]

    available = [_row(r) for r in store.q(
        "SELECT * FROM listings WHERE active=1 AND status='available' ORDER BY COALESCE(listed_at, first_seen) DESC")]
    lottery = [_row(r) for r in store.q(
        "SELECT * FROM listings WHERE active=1 AND status='lottery' ORDER BY price")]

    durations = [int(r["detail"]) for r in store.q(
        "SELECT detail FROM events WHERE kind='gone' AND status='available' AND at>=? AND detail IS NOT NULL",
        (month,)) if str(r["detail"]).isdigit()]

    events = []
    for r in store.q("""SELECT e.kind, e.at, e.price AS event_price, e.detail, l.name, l.url, l.city
                        FROM events e LEFT JOIN listings l ON l.id = e.listing_id
                        ORDER BY e.at DESC, e.id DESC LIMIT 40"""):
        name, city = r["name"] or "", catalog.city_label(r["city"]) if r["city"] else ""
        if r["kind"] == "building":
            try:
                info = json.loads(r["detail"])
                name, city = info["street"], catalog.city_label(info.get("city"))
            except (TypeError, ValueError, KeyError):
                name = r["detail"] or ""
        events.append({"kind": r["kind"], "at": r["at"], "name": name, "url": r["url"],
                       "city": city, "price": r["event_price"],
                       "detail": None if r["kind"] == "building" else r["detail"]})

    heat = [[0] * 24 for _ in range(7)]
    for r in store.q(f"SELECT at FROM events WHERE kind IN {ALERTS} AND status='available'"):
        t = schedule.local(parse(r["at"]))
        heat[t.weekday()][t.hour] += 1

    cities: dict[str, int] = {}
    for x in available:
        cities[x["city"] or "Unknown"] = cities.get(x["city"] or "Unknown", 0) + 1

    buildings = [{"street": r["street"], "city": catalog.city_label(r["city"]) if r["city"] else "",
                  "homes": r["homes"], "since": r["first_seen"]}
                 for r in store.q("SELECT * FROM buildings ORDER BY first_seen DESC, street LIMIT 8")]
    first_building = store.q("SELECT MIN(first_seen) FROM buildings")[0][0]
    # the first scan only learns what exists, so hide that batch
    buildings = [b for b in buildings if b["since"] != first_building]

    status = store.get("status", {})
    return {
        "version": __version__,
        "project": PROJECT_URL,
        "now": iso(now),
        "status": status,
        "search": {"summary": cfg.search.summary(), "lottery": cfg.search.lottery,
                   "deadline": iso(schedule.lottery_deadline()), "notify": len(cfg.notify.urls)},
        "stats": {
            "matching": len(available),
            "new_week": count(f"SELECT COUNT(*) FROM events WHERE kind IN {ALERTS} AND status='available' AND at>=?",
                              (week,)),
            "gone_week": count("SELECT COUNT(*) FROM events WHERE kind='gone' AND status='available' AND at>=?",
                               (week,)),
            "median_minutes": round(statistics.median(durations) / 60) if durations else None,
            "checks_day": count("SELECT COUNT(*) FROM checks WHERE at>=?", (day,)),
            "errors_day": count("SELECT COUNT(*) FROM checks WHERE at>=? AND ok=0", (day,)),
        },
        "available": available,
        "lottery": lottery,
        "events": events,
        "heatmap": heat,
        "cities": sorted(({"name": k, "count": v} for k, v in cities.items()), key=lambda c: -c["count"]),
        "buildings": buildings,
    }


def static_file(name: str) -> bytes:
    return resources.files("h2s_alerts").joinpath("web", name).read_bytes()


def make_handler(store: Store, cfg: Config, demo: bool = False):
    password = cfg.dashboard.password

    class Handler(BaseHTTPRequestHandler):
        server_version = "holland2stay-alerts"

        def log_message(self, fmt, *args):
            log.debug("dashboard: " + fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _authorized(self) -> bool:
            if not password:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                _, _, given = base64.b64decode(header[6:]).decode().partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            return hmac.compare_digest(given.encode(), password.encode())

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                state = store.get("status", {}).get("state", "starting")
                body = json.dumps({"ok": True, "state": state}).encode()
                return self._send(200, body, "application/json")
            if not self._authorized():
                return self._send(401, b"Password required", "text/plain",
                                  {"WWW-Authenticate": 'Basic realm="holland2stay-alerts"'})
            if path in ("/api/overview", "/api/overview.json"):
                try:
                    data = overview(store, cfg)
                    if demo:
                        data["demo"] = True
                    body = json.dumps(data).encode()
                except Exception:
                    log.exception("Dashboard data failed")
                    return self._send(500, b"{}", "application/json")
                return self._send(200, body, "application/json")
            if path in STATIC:
                name, ctype = STATIC[path]
                return self._send(200, static_file(name), ctype)
            return self._send(404, b"Not found", "text/plain")

    return Handler


def serve(store: Store, cfg: Config, block: bool = False, demo: bool = False) -> ThreadingHTTPServer | None:
    host, port = cfg.dashboard.host, cfg.dashboard.port
    try:
        server = ThreadingHTTPServer((host, port), make_handler(store, cfg, demo))
    except OSError as e:
        log.warning("Dashboard not started: port %s is not available (%s)", port, e.strerror or e)
        return None
    server.daemon_threads = True
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    log.info("Dashboard: http://%s:%s", shown, server.server_address[1])
    if block:
        server.serve_forever()
    else:
        threading.Thread(target=server.serve_forever, name="dashboard", daemon=True).start()
    return server
