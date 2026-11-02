"""Turn a Search into REST queries and the answers into Listings."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from . import catalog
from .client import Client, Filter
from .config import Search

log = logging.getLogger("h2s_alerts")

FIELDS = "items[id,name,url,price_info[final_price]]"
MAX_PAGES = 5
RESIDENCE_SKU = ("sku", "r-%", "like")  # parking is p-, other items c-


@dataclass
class Listing:
    id: int
    name: str
    slug: str
    url: str
    price: float | None
    status: str
    city: int | None = None
    bedrooms: int | None = None
    contract: int | None = None
    furnishing: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def city_name(self) -> str:
        return catalog.city_label(self.city)

    @property
    def bedrooms_name(self) -> str:
        return catalog.BEDROOMS.get(self.bedrooms, "") if self.bedrooms else ""

    @property
    def contract_name(self) -> str:
        return catalog.CONTRACTS.get(self.contract, "") if self.contract else ""

    @property
    def furnishing_name(self) -> str:
        return catalog.FURNISHING.get(self.furnishing, "") if self.furnishing else ""


ATTRIBUTES = {
    # listing field: (H2S attribute, all options, Search field)
    "city": ("city", lambda: list(catalog.CITIES), "cities"),
    "bedrooms": ("no_of_rooms", lambda: list(catalog.BEDROOMS), "bedrooms"),
    "contract": ("type_of_contract", lambda: list(catalog.CONTRACTS), "contracts"),
    "furnishing": ("finishing", lambda: list(catalog.FURNISHING), "furnishing"),
}


def _ids(values) -> str:
    return ",".join(str(v) for v in values)


def filters_for(search: Search, status: str) -> list[Filter]:
    f: list[Filter] = [("available_to_book", str(catalog.STATUS[status]), "eq"), RESIDENCE_SKU]
    if search.cities:
        f.append(("city", _ids(search.cities), "in"))
    if search.exclude_cities:
        f.append(("city", _ids(search.exclude_cities), "nin"))
    if search.bedrooms:
        f.append(("no_of_rooms", _ids(search.bedrooms), "in"))
    if search.contracts:
        f.append(("type_of_contract", _ids(search.contracts), "in"))
    if search.occupants:
        f.append(("maximum_number_of_persons", _ids(search.occupants), "in"))
    if search.furnishing:
        f.append(("finishing", _ids(search.furnishing), "in"))
    if search.price_min:
        f.append(("price", str(search.price_min), "gteq"))
    if search.price_max:
        f.append(("price", str(search.price_max), "lteq"))
    if search.move_in_before:
        f.append(("next_contract_startdate", search.move_in_before.isoformat() + " 23:59:59", "lteq"))
    return f


def slug_of(url: str) -> str:
    slug = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return slug[:-5] if slug.endswith(".html") else slug


def fetch(client: Client, search: Search, status: str) -> dict[int, Listing]:
    """Every residence that matches the search right now, by product id."""
    out: dict[int, Listing] = {}
    filters = filters_for(search, status)
    for page in range(1, MAX_PAGES + 1):
        # a fixed order keeps pages from overlapping or skipping homes
        items = client.products(filters, FIELDS, page=page, sort=("entity_id", "ASC"))
        for it in items:
            try:
                pid = int(it["id"])
            except (KeyError, TypeError, ValueError):
                continue
            slug = slug_of(it.get("url", ""))
            price = (it.get("price_info") or {}).get("final_price")
            out[pid] = Listing(
                id=pid,
                name=(it.get("name") or slug).strip(),
                slug=slug,
                url=f"{client.base_url}/residences/{slug}.html",
                price=float(price) if price is not None else None,
                status=status,
            )
        if len(items) < 300:
            break
    else:
        log.warning("More than %d homes match, only the first ones are watched. Narrow the search.",
                    MAX_PAGES * 300)
    for listing in out.values():
        fill_known(listing, search)
    return out


def fill_known(listing: Listing, search: Search) -> None:
    """When the search allows only one value, there is nothing to look up."""
    for attr, (_, _, search_field) in ATTRIBUTES.items():
        values = getattr(search, search_field)
        names = {catalog.city_label(v) for v in values} if attr == "city" else set(values)
        if len(values) == 1 or (attr == "city" and values and len(names) == 1):
            setattr(listing, attr, values[0])


def classify(client: Client, ids: list[int], attribute: str, options: list[int],
             budget: list[int]) -> dict[int, int]:
    """Which option each product has, one small query per option. Stops early.

    `budget` is a one-item list with the number of requests still allowed.
    """
    found: dict[int, int] = {}
    todo = set(ids)
    for opt in options:
        if not todo or budget[0] <= 0:
            break
        budget[0] -= 1
        rows = client.products([("entity_id", _ids(sorted(todo)), "in"), (attribute, str(opt), "eq")],
                               "items[id]", page_size=len(todo))
        for row in rows:
            pid = int(row["id"])
            if pid in todo:
                found[pid] = opt
                todo.discard(pid)
    return found


def describe(client: Client, listings: list[Listing], search: Search, extra_cities: list[int],
             budget: int = 24) -> None:
    """Fill city, bedrooms, contract and furnishing on new listings, within a request budget."""
    left = [budget]
    for attr, (h2s_attr, all_options, search_field) in ATTRIBUTES.items():
        todo = [x for x in listings if getattr(x, attr) is None]
        if not todo:
            continue
        options = list(getattr(search, search_field)) or all_options()
        if attr == "city" and not search.cities:
            options = list(dict.fromkeys(extra_cities + options))
            options = [o for o in options if o not in search.exclude_cities]
        result = classify(client, [x.id for x in todo], h2s_attr, options, left)
        for x in todo:
            if x.id in result:
                setattr(x, attr, result[x.id])


def street_of(name: str) -> str:
    """'Elzenhagensingel 303' -> 'Elzenhagensingel', 'Kon. Wilhelminaplein 29 K3' -> 'Kon. Wilhelminaplein'."""
    words = []
    for w in name.split():
        if re.search(r"\d", w):
            break
        words.append(w)
    return " ".join(words) or name


def newest(client: Client, search: Search, after_id: int, limit: int = 200) -> tuple[int, list[dict]]:
    """Residences added to the catalog after `after_id` (new buildings show up long before sale)."""
    filters: list[Filter] = [RESIDENCE_SKU]
    if search.cities:
        filters.append(("city", _ids(search.cities), "in"))
    if search.exclude_cities:
        filters.append(("city", _ids(search.exclude_cities), "nin"))
    rows = client.products(filters, "items[id,name]", page_size=limit, sort=("entity_id", "DESC"))
    top = max([int(r["id"]) for r in rows] + [after_id])
    fresh = [{"id": int(r["id"]), "name": r.get("name") or ""} for r in rows if int(r["id"]) > after_id]
    return top, fresh


def discover_cities(client: Client) -> dict[int, int]:
    """City ids that currently have anything listed, with rough counts (parking included)."""
    buckets = client.buckets([("available_to_book", str(catalog.STATUS["available"]), "eq")])
    return buckets.get("city_bucket", {})
