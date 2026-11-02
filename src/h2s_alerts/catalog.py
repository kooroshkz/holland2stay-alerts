"""Option ids used by Holland2Stay, with readable labels and the names people type."""

from __future__ import annotations

STATUS = {
    "available": 179,
    "lottery": 336,
    "lottery_soon": 6204,
    "coming_soon": 6253,
    "reserved": 6203,
    "occupied": 180,
}

CITIES: dict[int, str] = {
    24: "Amsterdam",
    25: "Rotterdam",
    26: "Delft",
    27: "Utrecht",
    28: "Den Bosch",
    29: "Eindhoven",
    90: "The Hague",
    110: "Diemen",
    320: "Arnhem",
    545: "Groningen",
    616: "Haarlem",
    619: "Capelle aan den IJssel",
    620: "Dordrecht",
    6051: "Nieuwegein",
    6088: "Zoetermeer",
    6090: "Maastricht",
    6093: "Tilburg",
    6099: "Helmond",
    6145: "Zeist",
    6186: "Delft",
    6209: "Maarssen",
    6211: "Sittard",
    6217: "Nijmegen",
    6224: "Rijswijk",
    6249: "Amersfoort",
    6265: "Velp",
    6267: "Granada",
    6293: "Leiden",
    6309: "Carcavelos",
    6310: "Linz",
}

ABROAD = {6267: "Spain", 6309: "Portugal", 6310: "Austria"}

CITY_ALIASES = {
    "den haag": "the hague",
    "hague": "the hague",
    "'s-gravenhage": "the hague",
    "s-gravenhage": "the hague",
    "'s-hertogenbosch": "den bosch",
    "s-hertogenbosch": "den bosch",
    "hertogenbosch": "den bosch",
    "capelle": "capelle aan den ijssel",
    "lisbon": "carcavelos",
}

BEDROOMS = {104: "Studio", 6137: "Loft", 105: "1 bedroom", 106: "2 bedrooms", 108: "3 bedrooms", 382: "4 bedrooms"}
BEDROOM_KEYS = {"studio": 104, "loft": 6137, "1": 105, "2": 106, "3": 108, "4": 382}
BEDROOM_ORDER = ["studio", "loft", "1", "2", "3", "4"]

CONTRACTS = {21: "Indefinite", 6125: "2 years", 20: "Max 1 year", 318: "Max 6 months", 606: "Max 4 months"}
CONTRACT_KEYS = {
    "indefinite": [21],
    "2y": [6125],
    "1y": [20],
    "6m": [318],
    "4m": [606],
    "long": [21, 6125, 20],
    "short": [318, 606],
}

OCCUPANTS = {22: "1 person", 23: "Couple", 500: "2 people", 380: "Family", 501: "3 people", 502: "4 people"}
OCCUPANT_KEYS = {"one": 22, "couple": 23, "two": 500, "family": 380, "three": 501, "four": 502}

FURNISHING = {70: "Fully furnished", 6261: "Furnished", 71: "Semi-furnished", 72: "Unfurnished"}
FURNISHING_KEYS = {"fully-furnished": 70, "furnished": 6261, "semi-furnished": 71, "unfurnished": 72}


def norm(text: str) -> str:
    return " ".join(str(text).strip().lower().replace("’", "'").split())


def city_id(name: str) -> list[int]:
    """Ids for a city name or numeric id. Delft has two ids, so this returns a list."""
    key = norm(name)
    if key.isdigit():
        return [int(key)]
    key = CITY_ALIASES.get(key, key)
    ids = [i for i, label in CITIES.items() if norm(label) == key]
    if not ids:
        raise KeyError(name)
    return ids


def city_label(cid: int | None) -> str:
    if cid is None:
        return ""
    return CITIES.get(cid, f"City {cid}")


def bedroom_ids(value: str) -> list[int]:
    """'studio', '2', '2+' (two or more), '1-3'."""
    key = norm(value).replace("bedrooms", "").replace("bedroom", "").strip()
    if key.endswith("+") and key[:-1] in BEDROOM_KEYS:
        start = BEDROOM_ORDER.index(key[:-1])
        return [BEDROOM_KEYS[k] for k in BEDROOM_ORDER[start:]]
    if "-" in key:
        a, b = (p.strip() for p in key.split("-", 1))
        if a in BEDROOM_KEYS and b in BEDROOM_KEYS:
            i, j = BEDROOM_ORDER.index(a), BEDROOM_ORDER.index(b)
            return [BEDROOM_KEYS[k] for k in BEDROOM_ORDER[min(i, j) : max(i, j) + 1]]
    if key in BEDROOM_KEYS:
        return [BEDROOM_KEYS[key]]
    raise KeyError(value)


def contract_ids(value: str) -> list[int]:
    key = norm(value).replace(" ", "").replace("_", "")
    key = {"shortstay": "short", "longstay": "long", "1year": "1y", "2years": "2y"}.get(key, key)
    if key not in CONTRACT_KEYS:
        raise KeyError(value)
    return CONTRACT_KEYS[key]


def occupant_id(value: str) -> int:
    key = norm(value)
    key = {"1": "one", "2": "two", "3": "three", "4": "four", "single": "one"}.get(key, key)
    if key not in OCCUPANT_KEYS:
        raise KeyError(value)
    return OCCUPANT_KEYS[key]


def furnishing_id(value: str) -> int:
    key = norm(value).replace(" ", "-")
    key = {"fully": "fully-furnished", "semi": "semi-furnished", "none": "unfurnished"}.get(key, key)
    if key not in FURNISHING_KEYS:
        raise KeyError(value)
    return FURNISHING_KEYS[key]
