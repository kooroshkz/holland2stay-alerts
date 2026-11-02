"""MCP server: ask an AI assistant about Holland2Stay homes. Run with `h2s-alerts mcp`."""

from __future__ import annotations

import time

from . import catalog, messages
from .client import Client, H2SError
from .config import Config, ConfigError, build
from .runtime import db_path
from .search import describe, fetch
from .store import Store, to_listing

CACHE_SECONDS = 60
MAX_RESULTS = 25


def run(cfg: Config) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise SystemExit("The MCP server needs an extra: pip install 'holland2stay-alerts[mcp]'") from None

    server = FastMCP("holland2stay")
    client = Client(cfg.base_url, min_gap=2.0)
    store = Store(db_path(cfg))
    cache: dict[tuple, tuple[float, str]] = {}

    @server.tool()
    def search_homes(city: str = "", bedrooms: str = "", max_price: int = 0, lottery: bool = False) -> str:
        """Holland2Stay homes you can book right now (or sign up for, with lottery=true).

        city: a city name like "Eindhoven" or "The Hague", empty for all.
        bedrooms: studio, loft, 1, 2, 3, 4 or "2+", empty for any.
        max_price: monthly price in euro, 0 for no limit.
        """
        key = (city.strip().lower(), bedrooms.strip().lower(), max_price, lottery)
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            search = build({"search": {"cities": city or [], "bedrooms": bedrooms or [],
                                       "price_max": max_price or None}}, {}).search
        except ConfigError as e:
            return str(e)
        status = "lottery" if lottery else "available"
        try:
            found = sorted(fetch(client, search, status).values(),
                           key=lambda x: x.price or 0)[:MAX_RESULTS]
            for x in found:
                store.known_details(x)
            describe(client, [x for x in found if x.city is None or x.bedrooms is None], search, [], budget=10)
            for x in found:
                store.details(x)
        except H2SError as e:
            return f"Holland2Stay didn't answer: {e}"
        if not found:
            text = "Nothing matches right now."
        else:
            lines = [f"{x.name} · {messages.facts(x)} · {messages.terms(x)}\n{x.url}" for x in found]
            text = "\n\n".join(lines)
            if lottery:
                text += f"\n\n{messages.deadline()}"
        cache[key] = (time.monotonic(), text)
        return text

    @server.tool()
    def list_cities() -> str:
        """Cities where Holland2Stay has homes."""
        return ", ".join(sorted(set(catalog.CITIES.values())))

    @server.tool()
    def recent_activity(limit: int = 15) -> str:
        """What the local watcher saw lately: new homes, homes taken, lottery homes."""
        rows = store.q("""SELECT e.kind, e.at, e.detail, l.* FROM events e JOIN listings l ON l.id = e.listing_id
                          ORDER BY e.id DESC LIMIT ?""", (max(1, min(limit, 100)),))
        if not rows:
            return "No activity recorded. Start the watcher with `h2s-alerts watch` first."
        out = []
        for r in rows:
            x = to_listing(r)
            out.append(f"{r['at'][:16].replace('T', ' ')} UTC  {r['kind']}: {x.name} · {messages.facts(x)}")
        return "\n".join(out)

    server.run()
