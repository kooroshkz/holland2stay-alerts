"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sqlite3
import statistics
import sys
import threading
import time
import urllib.request
from collections import Counter
from datetime import timedelta
from pathlib import Path

from . import __version__, catalog, messages, schedule
from .client import Client, H2SError
from .config import Config, ConfigError, build, load
from .notify import Notifier, masked
from .runtime import AlreadyRunning, Lock, db_path, setup_logging
from .search import describe, discover_cities, fetch
from .store import Store, iso, parse, utcnow
from .term import bad, bold, dim, ok, table, warn

log = logging.getLogger("h2s_alerts")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _configured(cfg: Config) -> bool:
    return cfg.source is not None or any(k.startswith("H2S_") for k in os.environ)


# Commands

def cmd_watch(cfg: Config, args) -> int:
    from .dashboard import serve
    from .watcher import Watcher

    if getattr(args, "port", None):
        cfg.dashboard.port = args.port
    if getattr(args, "no_dashboard", False):
        cfg.dashboard.enabled = False
    setup_logging("DEBUG" if args.verbose else cfg.log_level)
    for w in cfg.warnings:
        log.warning(w)
    log.info("holland2stay-alerts %s", __version__)
    log.info("Search: %s", cfg.search.summary())
    notifier = Notifier(cfg.notify.urls)
    for url in notifier.invalid:
        log.warning("Skipping a notification link Apprise doesn't understand: %s", masked(url))
    if not notifier.enabled:
        log.warning("No notification links set, alerts only go to this log and the dashboard")

    try:
        with Lock(cfg.data_dir):
            store = Store(db_path(cfg))
            watcher = Watcher(cfg, store, notifier=notifier)
            if args.once:
                watcher.tick()
                store.close()
                return 0
            server = serve(store, cfg) if cfg.dashboard.enabled else None

            def stop(*_):
                watcher.stop.set()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            try:
                watcher.run()
            finally:
                if server:
                    server.shutdown()
                store.close()
                log.info("Stopped")
    except AlreadyRunning as e:
        print(bad(str(e)), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error) as e:
        reason = getattr(e, "strerror", None) or str(e)
        print(bad(f"Can't write to {cfg.data_dir}: {reason}"), file=sys.stderr)
        if Path("/.dockerenv").exists():
            print(dim("Mounted a folder at /data? Make it writable for user 1000: sudo chown 1000 ./data"),
                  file=sys.stderr)
        return 1
    return 0


def cmd_health(cfg: Config, args) -> int:
    """Exit 0 when the watcher's dashboard answers (used by the Docker health check)."""
    if not cfg.dashboard.enabled:
        return 0
    host = "127.0.0.1" if cfg.dashboard.host in ("0.0.0.0", "::", "") else cfg.dashboard.host
    try:
        with urllib.request.urlopen(f"http://{host}:{cfg.dashboard.port}/healthz", timeout=4) as r:
            return 0 if r.status == 200 else 1
    except OSError:
        return 1


def cmd_list(cfg: Config, args) -> int:
    if args.city:
        cfg.search.cities = build({"search": {"cities": args.city}}, {}).search.cities
        cfg.search.exclude_cities = []
    client = Client(cfg.base_url)
    status = "lottery" if args.lottery else "available"
    store = Store(db_path(cfg)) if db_path(cfg).exists() else None
    try:
        found = sorted(fetch(client, cfg.search, status).values(), key=lambda x: x.price or 0)
        if store:
            for x in found:
                store.known_details(x)
        extra = [int(c) for c in store.get("cities_seen", {})] if store else []
        describe(client, [x for x in found if None in (x.city, x.bedrooms, x.contract)], cfg.search, extra,
                 budget=40)
    except H2SError as e:
        print(bad(str(e)), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([{"name": x.name, "url": x.url, "price": x.price, "city": x.city_name,
                           "bedrooms": x.bedrooms_name, "contract": x.contract_name,
                           "furnishing": x.furnishing_name, "status": x.status} for x in found], indent=2))
        return 0
    print(dim(cfg.search.summary()))
    if not found:
        print("Nothing matches right now.")
        return 0
    rows = [[messages.money(x.price), x.name, x.city_name, x.bedrooms_name, x.contract_name] for x in found]
    print(table(rows, right={0}))
    print()
    for x in found[:3]:
        print(dim(x.url))
    more = f", {len(found) - 3} more links with --json" if len(found) > 3 else ""
    print(dim(f"{len(found)} home{'s' if len(found) != 1 else ''}{more}"))
    if args.lottery:
        print(dim(messages.deadline()))
    return 0


def cmd_cities(cfg: Config, args) -> int:
    names: dict[str, list[int]] = {}
    for cid, name in catalog.CITIES.items():
        names.setdefault(name, []).append(cid)
    rows = [[name, ", ".join(map(str, ids)), catalog.ABROAD.get(ids[0], "")] for name, ids in sorted(names.items())]
    print(table(rows))
    try:
        unknown = [c for c in discover_cities(Client(cfg.base_url)) if c not in catalog.CITIES]
    except H2SError:
        unknown = []
    if unknown:
        print()
        print(warn("New city ids on Holland2Stay: " + ", ".join(map(str, unknown))))
        print(dim("You can use the number in your config until the name is added."))
    return 0


def cmd_test(cfg: Config, args) -> int:
    if not cfg.notify.urls:
        print(warn("No notification links in your config. Run h2s-alerts init or set H2S_NOTIFY."))
        return 1
    results = Notifier(cfg.notify.urls).test(*messages.test())
    for url, sent in results:
        print(ok(url) if sent else bad(f"{url} (failed)"))
    return 0 if all(sent for _, sent in results) else 1


def cmd_doctor(cfg: Config, args) -> int:
    good = True
    print(ok(f"Config: {cfg.source}") if cfg.source else ok("Config: environment variables only"))
    for w in cfg.warnings:
        print(warn(w))
    print(ok(f"Search: {cfg.search.summary()}"))

    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        print(ok(f"Data folder: {cfg.data_dir}"))
    except OSError as e:
        good = False
        print(bad(f"Data folder {cfg.data_dir} is not writable ({e.strerror})"))

    notifier = Notifier(cfg.notify.urls)
    if notifier.invalid:
        good = False
        for url in notifier.invalid:
            print(bad(f"Notification link not understood: {masked(url)}"))
    if notifier.enabled:
        print(ok(f"Notifications: {len(notifier.apprise)} channel{'s' if len(notifier.apprise) != 1 else ''}"
                 " (send one with h2s-alerts test)"))
    else:
        print(warn("Notifications: none set, alerts only go to the log and the dashboard"))

    client = Client(cfg.base_url)
    started = time.monotonic()
    try:
        found = fetch(client, cfg.search, "available")
        ms = int((time.monotonic() - started) * 1000)
        print(ok(f"Holland2Stay: {len(found)} home{'s' if len(found) != 1 else ''} match right now ({ms} ms)"))
    except H2SError as e:
        good = False
        print(bad(f"Holland2Stay: {e}"))

    if cfg.dashboard.enabled:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((cfg.dashboard.host if cfg.dashboard.host != "localhost" else "127.0.0.1",
                        cfg.dashboard.port))
                print(ok(f"Dashboard port {cfg.dashboard.port} is free"))
            except OSError:
                print(warn(f"Dashboard port {cfg.dashboard.port} is in use (fine if the watcher is running)"))

    now = schedule.local()
    print(ok(f"Amsterdam time {now:%a %H:%M}, {schedule.window(now)}"))
    return 0 if good else 1


def cmd_stats(cfg: Config, args) -> int:
    path = db_path(cfg)
    if not path.exists():
        print("No data yet. Start the watcher first: h2s-alerts watch")
        return 1
    store = Store(path)
    first = store.q("SELECT MIN(at) FROM checks")[0][0]
    checks, errors = store.q("SELECT COUNT(*), SUM(ok=0) FROM checks WHERE at>=?",
                             (iso(utcnow() - timedelta(days=1)),))[0]
    active = store.q("SELECT COUNT(*) FROM listings WHERE active=1 AND status='available'")[0][0]
    week = iso(utcnow() - timedelta(days=7))
    new = store.q("SELECT COUNT(*) FROM events WHERE kind IN ('new','back','bookable') AND at>=?", (week,))[0][0]
    gone = [int(r[0]) for r in store.q(
        "SELECT detail FROM events WHERE kind='gone' AND status='available' AND detail IS NOT NULL")
        if str(r[0]).isdigit()]
    heat = Counter()
    for r in store.q("SELECT at FROM events WHERE kind IN ('new','back','bookable') AND status='available'"):
        t = schedule.local(parse(r[0]))
        heat[(t.weekday(), t.hour)] += 1

    print(dim(cfg.search.summary()))
    if first:
        print(f"Watching since   {schedule.local(parse(first)):%d %b %H:%M}")
    print(f"Last 24 hours    {checks} checks, {errors or 0} failed")
    print(f"Matching now     {active}")
    print(f"New this week    {new}")
    if gone:
        print(f"Time listed      typical {round(statistics.median(gone) / 60)} min, "
              f"fastest {round(min(gone) / 60)} min ({len(gone)} homes)")
    if heat:
        top = ", ".join(f"{DAYS[d]} {h:02d}:00" for (d, h), _ in heat.most_common(3))
        print(f"Busiest hours    {top}")
    rows = store.q("""SELECT e.kind, e.at, l.name, l.price FROM events e LEFT JOIN listings l ON l.id = e.listing_id
                      WHERE e.kind != 'building' ORDER BY e.id DESC LIMIT 10""")
    if rows:
        print()
        print(table([[f"{schedule.local(parse(r['at'])):%a %H:%M}", r["kind"], r["name"] or "",
                      messages.money(r["price"])] for r in rows], right={3}))
    store.close()
    return 0


def cmd_demo(args) -> int:
    from . import demo
    from .dashboard import serve

    if args.export:
        path = demo.export(Path(args.export))
        print(ok(f"Static demo written to {path}"))
        return 0
    setup_logging("WARNING")
    store, cfg, folder = demo.temp_store()
    cfg.dashboard.port = args.port
    server = serve(store, cfg, demo=True)
    if not server:
        print(bad(f"Port {args.port} is in use. Try --port 8081"))
        return 1
    print(f"Demo dashboard with sample data: {bold(f'http://localhost:{server.server_address[1]}')}")
    print(dim("Ctrl+C to stop"))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        store.close()
        demo.cleanup(folder)
    return 0


def cmd_mcp(cfg: Config, args) -> int:
    from .mcp_server import run
    run(cfg)
    return 0


# Parser

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="h2s-alerts",
                                description="Alerts for new Holland2Stay and Codomo homes.")
    p.add_argument("--config", metavar="PATH", help="config file (default: ./config.toml or ~/.config/...)")
    p.add_argument("-v", "--verbose", action="store_true", help="more logging")
    p.add_argument("--version", action="version", version=f"holland2stay-alerts {__version__}")
    # the config and verbose options also work after the command name
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", default=argparse.SUPPRESS, help="config file")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="more logging")
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.add_parser("init", parents=[common], help="set up your search and notifications")
    w = sub.add_parser("watch", parents=[common], help="check for new homes and send alerts")
    w.add_argument("--once", action="store_true", help="check once and exit")
    w.add_argument("--no-dashboard", action="store_true", help="don't start the dashboard")
    w.add_argument("--port", type=int, help="dashboard port")
    li = sub.add_parser("list", parents=[common], help="show what matches right now")
    li.add_argument("--lottery", action="store_true", help="lottery homes instead")
    li.add_argument("--city", action="append", help="only this city (repeat for more)")
    li.add_argument("--json", action="store_true", help="machine readable output")
    sub.add_parser("cities", parents=[common], help="city names you can use")
    sub.add_parser("test", parents=[common], help="send a test notification")
    sub.add_parser("doctor", parents=[common], help="check your setup")
    sub.add_parser("stats", parents=[common], help="what the watcher has seen so far")
    d = sub.add_parser("demo", help="try the dashboard with sample data")
    d.add_argument("--port", type=int, default=8080)
    d.add_argument("--export", metavar="DIR", help="write a static copy instead of serving it")
    sub.add_parser("mcp", parents=[common], help="MCP server for AI assistants")
    sub.add_parser("health", parents=[common], help="exit 0 when the watcher is running")
    return p


COMMANDS = {"watch": cmd_watch, "list": cmd_list, "cities": cmd_cities, "test": cmd_test,
            "doctor": cmd_doctor, "stats": cmd_stats, "mcp": cmd_mcp, "health": cmd_health}


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.command == "init":
        from .wizard import run
        try:
            return run(args.config)
        except KeyboardInterrupt:
            print()
            return 130
    if args.command == "demo":
        return cmd_demo(args)
    try:
        cfg = load(args.config)
    except ConfigError as e:
        print(bad(f"Config problem: {e}"), file=sys.stderr)
        return 2
    command = args.command or "watch"
    if command == "watch" and not args.command and not _configured(cfg):
        p.print_help()
        print(f"\nNew here? Run {bold('h2s-alerts init')} to set up your search.")
        return 1
    if command == "watch" and not hasattr(args, "once"):
        args.once, args.no_dashboard, args.port = False, False, None
    try:
        return COMMANDS[command](cfg, args)
    except KeyboardInterrupt:
        return 130
    except ConfigError as e:
        print(bad(f"Config problem: {e}"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
