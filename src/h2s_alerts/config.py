"""Settings from config.toml and H2S_* environment variables (env wins)."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date, time
from pathlib import Path

from . import catalog

MIN_INTERVAL = 60
PRESETS = {
    # seconds between checks: release hours, rest of the day, night
    "relaxed": (300, 600, 1800),
    "normal": (120, 300, 900),
    "eager": (60, 180, 600),
}
DEFAULT_BASE_URL = "https://www.holland2stay.com"


class ConfigError(Exception):
    pass


@dataclass
class Search:
    cities: list[int] = field(default_factory=list)
    exclude_cities: list[int] = field(default_factory=list)
    bedrooms: list[int] = field(default_factory=list)
    contracts: list[int] = field(default_factory=list)
    occupants: list[int] = field(default_factory=list)
    furnishing: list[int] = field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None
    move_in_before: date | None = None
    lottery: bool = True

    def fingerprint(self) -> str:
        data = asdict(self)
        data.pop("lottery")
        data["move_in_before"] = str(self.move_in_before or "")
        return json.dumps(data, sort_keys=True)

    def summary(self) -> str:
        parts = []
        if self.cities:
            parts.append(", ".join(dict.fromkeys(catalog.city_label(c) for c in self.cities)))
        else:
            parts.append("All cities")
        if self.exclude_cities:
            names = dict.fromkeys(catalog.city_label(c) for c in self.exclude_cities)
            parts.append("not " + ", ".join(names))
        if self.bedrooms:
            keys = [k for k in catalog.BEDROOM_ORDER if catalog.BEDROOM_KEYS[k] in self.bedrooms]
            tail = catalog.BEDROOM_ORDER[catalog.BEDROOM_ORDER.index(keys[0]):]
            if keys == tail and len(keys) > 1 and keys[0].isdigit():
                parts.append(f"{keys[0]}+ bedrooms")
            else:
                parts.append(", ".join(catalog.BEDROOMS[b] for b in self.bedrooms))
        if self.price_min and self.price_max:
            parts.append(f"€{self.price_min:,} to €{self.price_max:,}")
        elif self.price_max:
            parts.append(f"up to €{self.price_max:,}")
        elif self.price_min:
            parts.append(f"from €{self.price_min:,}")
        if self.contracts:
            if sorted(self.contracts) == sorted(catalog.CONTRACT_KEYS["long"]):
                parts.append("Long stay")
            elif sorted(self.contracts) == sorted(catalog.CONTRACT_KEYS["short"]):
                parts.append("Short stay")
            else:
                parts.append(", ".join(catalog.CONTRACTS[c] for c in self.contracts))
        if self.furnishing:
            parts.append(", ".join(catalog.FURNISHING[f] for f in self.furnishing))
        if self.occupants:
            parts.append(", ".join(catalog.OCCUPANTS[o] for o in self.occupants))
        if self.move_in_before:
            parts.append(f"move in by {self.move_in_before:%d %b}")
        return " · ".join(parts)


@dataclass
class Notify:
    urls: list[str] = field(default_factory=list)
    quiet_hours: tuple[time, time] | None = None
    existing_on_start: bool = False
    health: bool = True
    digest_after: int = 4


@dataclass
class Schedule:
    preset: str = "normal"
    hot: int = PRESETS["normal"][0]
    day: int = PRESETS["normal"][1]
    night: int = PRESETS["normal"][2]
    lottery: int = 600
    jitter: float = 0.25


@dataclass
class Dashboard:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    password: str | None = None


@dataclass
class Config:
    search: Search = field(default_factory=Search)
    notify: Notify = field(default_factory=Notify)
    schedule: Schedule = field(default_factory=Schedule)
    dashboard: Dashboard = field(default_factory=Dashboard)
    base_url: str = DEFAULT_BASE_URL
    data_dir: Path = field(default_factory=lambda: default_data_dir())
    log_level: str = "INFO"
    source: Path | None = None
    warnings: list[str] = field(default_factory=list)


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "holland2stay-alerts"


def config_candidates() -> list[Path]:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [Path("config.toml"), xdg / "holland2stay-alerts" / "config.toml"]


def find_config(path: str | None, env: dict) -> Path | None:
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise ConfigError(f"Config file not found: {p}")
        return p
    if env.get("H2S_CONFIG"):
        p = Path(env["H2S_CONFIG"]).expanduser()
        if not p.exists():
            raise ConfigError(f"H2S_CONFIG points to a missing file: {p}")
        return p
    return next((p for p in config_candidates() if p.exists()), None)


# Parsing helpers

def _list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, int | float):
        return [str(value)]
    return [str(v).strip() for v in value if str(v).strip()]


def _bool(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    raise ConfigError(f"{name}: expected true or false, got {value!r}")


def _int(value, name: str, lo: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(str(value).replace("€", "").replace(",", "").replace("_", "").strip())
    except ValueError:
        raise ConfigError(f"{name}: expected a whole number, got {value!r}") from None
    if lo is not None and n < lo:
        raise ConfigError(f"{name}: must be at least {lo}")
    return n


def _resolve(values: list[str], fn, name: str, options: str) -> list[int]:
    out: list[int] = []
    for v in values:
        try:
            r = fn(v)
        except KeyError:
            raise ConfigError(f"{name}: unknown value {v!r}. Use {options}") from None
        out.extend(r if isinstance(r, list) else [r])
    return list(dict.fromkeys(out))


def _cities(values: list[str], name: str) -> list[int]:
    known = ", ".join(sorted(set(catalog.CITIES.values())))
    return _resolve(values, catalog.city_id, name, f"a city name ({known}) or a numeric id")


def _clock(text: str, name: str) -> time:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ConfigError(f"{name}: expected HH:MM, got {text!r}")
    return time(int(m[1]), int(m[2]))


def _quiet(value, name: str) -> tuple[time, time] | None:
    if not value:
        return None
    parts = str(value).split("-")
    if len(parts) != 2:
        raise ConfigError(f"{name}: expected a range like 23:00-07:00")
    return _clock(parts[0], name), _clock(parts[1], name)


def _urls(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [u for u in re.split(r"[\s;]+", value) if u]
    return [str(u).strip() for u in value if str(u).strip()]


# Loading

def load(path: str | None = None, env: dict | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    source = find_config(path, env)
    raw: dict = {}
    if source:
        try:
            raw = tomllib.loads(source.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{source}: {e}") from None
    return build(raw, env, source)


def build(raw: dict, env: dict, source: Path | None = None) -> Config:
    s, n, sc, d, g = (raw.get(k, {}) for k in ("search", "notify", "schedule", "dashboard", "general"))
    for section, value in (("search", s), ("notify", n), ("schedule", sc), ("dashboard", d), ("general", g)):
        if not isinstance(value, dict):
            raise ConfigError(f"[{section}] must be a table")

    def pick(env_key: str, table: dict, key: str, default=None):
        return env[env_key] if env.get(env_key, "") != "" else table.get(key, default)

    cfg = Config(source=source)

    search = Search()
    search.cities = _cities(_list(pick("H2S_CITIES", s, "cities")), "cities")
    search.exclude_cities = _cities(_list(pick("H2S_EXCLUDE_CITIES", s, "exclude_cities")), "exclude_cities")
    search.bedrooms = _resolve(_list(pick("H2S_BEDROOMS", s, "bedrooms")), catalog.bedroom_ids,
                               "bedrooms", "studio, loft, 1, 2, 3, 4, 2+ or 1-3")
    search.contracts = _resolve(_list(pick("H2S_CONTRACT", s, "contract")), catalog.contract_ids,
                                "contract", "long, short, indefinite, 2y, 1y, 6m or 4m")
    search.occupants = _resolve(_list(pick("H2S_OCCUPANTS", s, "occupants")), catalog.occupant_id,
                                "occupants", "one, couple, two, family, three or four")
    search.furnishing = _resolve(_list(pick("H2S_FURNISHING", s, "furnishing")), catalog.furnishing_id,
                                 "furnishing", "fully-furnished, furnished, semi-furnished or unfurnished")
    search.price_min = _int(pick("H2S_PRICE_MIN", s, "price_min"), "price_min", 0) or None
    search.price_max = _int(pick("H2S_PRICE_MAX", s, "price_max"), "price_max", 1) or None
    if search.price_min and search.price_max and search.price_min > search.price_max:
        raise ConfigError("price_min is higher than price_max")
    move = pick("H2S_MOVE_IN_BEFORE", s, "move_in_before")
    if move not in (None, ""):
        try:
            search.move_in_before = move if isinstance(move, date) else date.fromisoformat(str(move))
        except ValueError:
            raise ConfigError(f"move_in_before: expected YYYY-MM-DD, got {move!r}") from None
    search.lottery = _bool(pick("H2S_LOTTERY", s, "lottery", True), "lottery")
    overlap = set(search.cities) & set(search.exclude_cities)
    if overlap:
        names = ", ".join(catalog.city_label(c) for c in overlap)
        raise ConfigError(f"{names} is both in cities and exclude_cities")
    cfg.search = search

    notify = Notify()
    urls = pick("H2S_NOTIFY", n, "urls")
    if env.get("H2S_NOTIFY_FILE"):
        try:
            urls = Path(env["H2S_NOTIFY_FILE"]).read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigError(f"H2S_NOTIFY_FILE: {e}") from None
    notify.urls = _urls(urls)
    notify.quiet_hours = _quiet(pick("H2S_QUIET_HOURS", n, "quiet_hours"), "quiet_hours")
    notify.existing_on_start = _bool(pick("H2S_NOTIFY_EXISTING", n, "existing_on_start", False),
                                     "existing_on_start")
    notify.health = _bool(pick("H2S_NOTIFY_HEALTH", n, "health", True), "health")
    notify.digest_after = _int(pick("H2S_DIGEST_AFTER", n, "digest_after", 4), "digest_after", 1)
    cfg.notify = notify

    sched = Schedule()
    preset = str(pick("H2S_SCHEDULE", sc, "preset", "normal")).strip().lower()
    if preset not in PRESETS:
        raise ConfigError(f"schedule preset: use {', '.join(PRESETS)}")
    sched.preset = preset
    sched.hot, sched.day, sched.night = PRESETS[preset]
    for key in ("hot", "day", "night", "lottery"):
        value = _int(pick(f"H2S_{key.upper()}_SECONDS", sc, f"{key}_seconds"), f"{key}_seconds", 1)
        if value is None:
            continue
        if value < MIN_INTERVAL:
            cfg.warnings.append(f"{key}_seconds raised to {MIN_INTERVAL}: checking faster gets you blocked")
            value = MIN_INTERVAL
        setattr(sched, key, value)
    cfg.schedule = sched

    dash = Dashboard()
    dash.enabled = _bool(pick("H2S_DASHBOARD", d, "enabled", True), "dashboard")
    dash.host = str(pick("H2S_HOST", d, "host", "127.0.0.1"))
    dash.port = _int(pick("H2S_PORT", d, "port", 8080), "port", 1)
    if dash.port > 65535:
        raise ConfigError("port: must be 65535 or lower")
    password = pick("H2S_DASHBOARD_PASSWORD", d, "password")
    dash.password = str(password) if password not in (None, "") else None
    cfg.dashboard = dash

    base = str(pick("H2S_BASE_URL", g, "base_url", DEFAULT_BASE_URL)).rstrip("/")
    if not base.startswith("https://"):
        raise ConfigError("base_url must start with https://")
    cfg.base_url = base
    data_dir = pick("H2S_DATA_DIR", g, "data_dir")
    cfg.data_dir = Path(data_dir).expanduser() if data_dir else default_data_dir()
    cfg.log_level = str(pick("H2S_LOG_LEVEL", g, "log_level", "INFO")).upper()
    return cfg
