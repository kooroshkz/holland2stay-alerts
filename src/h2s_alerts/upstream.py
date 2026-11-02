"""Does Holland2Stay still answer the way this tool expects? Run by maintainers and CI daily.

A failure means alerts are probably broken for everyone. A notice means something new
appeared (a city id, an option id, the Codomo site) that the code should learn about.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from . import USER_AGENT, catalog
from .client import Client, H2SError
from .config import Search
from .search import FIELDS, RESIDENCE_SKU, classify, fetch

CODOMO_URL = "https://www.codomoliving.com"
OPTION_BUCKETS = {
    "city_bucket": ("city", catalog.CITIES),
    "no_of_rooms_bucket": ("bedrooms", catalog.BEDROOMS),
    "type_of_contract_bucket": ("contract", catalog.CONTRACTS),
    "finishing_bucket": ("furnishing", catalog.FURNISHING),
    "maximum_number_of_persons_bucket": ("occupants", catalog.OCCUPANTS),
}


@dataclass
class Check:
    name: str
    status: str  # ok, fail, notice
    detail: str = ""


def _available(client: Client, extra=()) -> list[dict]:
    filters = [("available_to_book", str(catalog.STATUS["available"]), "eq"), RESIDENCE_SKU, *extra]
    return client.products(filters, FIELDS)


def run(client: Client | None = None, codomo: bool = True) -> list[Check]:
    client = client or Client(min_gap=2.0)
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str = "") -> bool:
        checks.append(Check(name, "ok" if ok else "fail", detail))
        return ok

    try:
        items = _available(client)
    except H2SError as e:
        add("Listing endpoint answers", False, str(e))
        return checks
    add("Listing endpoint answers", True, f"{len(items)} homes available to book")
    if not add("Homes are listed", bool(items), "" if items else "0 homes in the whole country is very unusual"):
        return checks

    first = items[0]
    shape = (isinstance(first.get("id"), int) and isinstance(first.get("name"), str)
             and str(first.get("url", "")).endswith(".html")
             and isinstance((first.get("price_info") or {}).get("final_price"), int | float))
    add("Listings have the expected fields", shape, "" if shape else f"got {sorted(first)}")

    try:
        none = _available(client, [("price", "1", "lteq")])
        add("Filters are applied", not none, "" if not none else "a filter for €1 still returned homes")

        everywhere = Search()
        found = fetch(client, everywhere, "available")
        # the first request returns at most one page of 300
        add("Full search matches the endpoint", len(found) == len(items) or len(items) == 300,
            f"{len(found)} vs {len(items)}")

        pid = first["id"]
        city = classify(client, [pid], "city", list(catalog.CITIES), [len(catalog.CITIES)])
        add("Details can be looked up", pid in city,
            catalog.city_label(city[pid]) if pid in city else f"no known city matched home {pid}")

        newest = client.products([RESIDENCE_SKU], "items[id]", page_size=5, sort=("entity_id", "DESC"))
        ids = [r["id"] for r in newest]
        add("Newest homes can be found", ids == sorted(ids, reverse=True) and len(ids) > 1, str(ids))

        buckets = client.buckets([("available_to_book", str(catalog.STATUS["available"]), "eq")])
        add("Search counts answer", "city_bucket" in buckets)
        for bucket, (label, known) in OPTION_BUCKETS.items():
            unknown = sorted(set(buckets.get(bucket, {})) - set(known))
            if unknown:
                checks.append(Check(f"New {label} ids", "notice",
                                    ", ".join(map(str, unknown)) + " (add them to catalog.py)"))
    except H2SError as e:
        add("Follow-up queries answer", False, str(e))

    if codomo:
        live = codomo_live()
        if live:
            checks.append(Check("Codomo listing endpoint is live", "notice",
                                f"{CODOMO_URL} answers with listings: time to support it"))
    return checks


def codomo_live() -> bool:
    url = f"{CODOMO_URL}/api/rest/V1/products-render-info"
    params = [("searchCriteria[pageSize]", "1"), ("fields", "items[id]")]
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        return r.status_code == 200 and "items" in r.json()
    except (requests.RequestException, ValueError):
        return False


def markdown(checks: list[Check]) -> str:
    icon = {"ok": "✅", "fail": "❌", "notice": "🆕"}
    lines = ["| | Check | Detail |", "|---|---|---|"]
    lines += [f"| {icon[c.status]} | {c.name} | {c.detail} |" for c in checks]
    return "\n".join(lines) + "\n"
