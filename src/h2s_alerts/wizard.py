"""`h2s-alerts init`: a few questions, then a config file."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import apprise

from . import PROJECT_URL, catalog, messages
from .client import Client, H2SError
from .config import ConfigError, build, load
from .notify import Notifier
from .search import fetch
from .term import ask, bad, bold, dim, ok, warn, yes

EXAMPLES = [
    ("Telegram", "tgram://BOT_TOKEN/CHAT_ID"),
    ("Discord", "discord://WEBHOOK_ID/WEBHOOK_TOKEN"),
    ("ntfy", "ntfy://pick-a-long-secret-topic"),
    ("Email", "mailtos://you:app-password@gmail.com"),
]


def default_path() -> Path:
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "holland2stay-alerts" / "config.toml"


def _valid(section: str, key: str, value) -> str | None:
    try:
        build({section: {key: value}}, {})
    except ConfigError as e:
        return str(e)
    return None


def _ask_list(question: str, key: str, default: str = "") -> list[str]:
    while True:
        answer = ask(question, default)
        values = [v.strip() for v in answer.split(",") if v.strip()]
        error = _valid("search", key, values)
        if not error:
            return values
        print(bad(error))


def _ask_price() -> int | None:
    while True:
        answer = ask("Max price per month in euro (empty for no limit):")
        if not answer:
            return None
        clean = "".join(c for c in answer if c not in "€,. ")
        error = _valid("search", "price_max", clean)
        if not error:
            return int(clean)
        print(bad(error))


def _ask_urls() -> list[str]:
    print()
    print("Where should alerts go? Paste one link per line, empty line to finish.")
    for name, example in EXAMPLES:
        print(dim(f"  {name:9} {example}"))
    print(dim("  More apps: https://github.com/caronc/apprise/wiki"))
    urls: list[str] = []
    while True:
        url = ask(">")
        if not url:
            return urls
        if apprise.Apprise().add(url):
            urls.append(url)
            print(ok("Added"))
        else:
            print(bad("That doesn't look like a valid link, try again"))


def _toml(search: dict, urls: list[str]) -> str:
    def value(v) -> str:
        return json.dumps(v, ensure_ascii=False) if not isinstance(v, bool) else str(v).lower()

    lines = [f"# holland2stay-alerts settings. All options: {PROJECT_URL}#configuration", "", "[search]"]
    for key, v in search.items():
        if v not in (None, [], ""):
            lines.append(f"{key} = {value(v)}")
    lines += ["", "[notify]", f"urls = {value(urls)}", "", "[schedule]", 'preset = "normal"', "",
              "[dashboard]", "enabled = true", "port = 8080", ""]
    return "\n".join(lines)


def run(path: str | None = None) -> int:
    target = Path(path).expanduser() if path else default_path()
    print(bold("holland2stay-alerts setup"))
    print(dim("Press enter to skip a question.\n"))
    if target.exists() and not yes(f"{target} exists. Replace it?", default=False):
        print("Nothing changed.")
        return 1

    known = sorted(set(catalog.CITIES.values()))
    print(dim("Cities: " + ", ".join(known)))
    cities = _ask_list("Which cities? (comma separated, empty for all):", "cities")
    bedrooms = _ask_list("Bedrooms? studio, loft, 1, 2, 3, 4 or 2+ (empty for any):", "bedrooms")
    price_max = _ask_price()
    contract = ask("Contract? long, short or any:", "any").strip().lower()
    while contract not in ("long", "short", "any"):
        contract = ask("Please type long, short or any:", "any").strip().lower()
    lottery = yes("Also tell you about lottery homes?", default=True)
    urls = _ask_urls()

    search = {"cities": cities, "bedrooms": bedrooms, "price_max": price_max,
              "contract": [] if contract == "any" else [contract], "lottery": lottery}
    target.parent.mkdir(parents=True, exist_ok=True)
    # notification links are secrets: private from the first byte
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_toml(search, urls))
    with contextlib.suppress(OSError):
        os.chmod(target, 0o600)  # the file may have existed with wider permissions
    print()
    print(ok(f"Saved {target}"))

    cfg = load(str(target))
    print(dim(cfg.search.summary()))
    try:
        found = fetch(Client(cfg.base_url), cfg.search, "available")
        print(ok(f"{len(found)} home{'s' if len(found) != 1 else ''} match right now"))
        for x in sorted(found.values(), key=lambda x: x.price or 0)[:5]:
            print(dim(f"  {messages.money(x.price):>7}  {x.name}"))
    except H2SError as e:
        print(warn(f"Couldn't check Holland2Stay right now: {e}"))

    if urls and yes("Send a test message?", default=True):
        for url, sent in Notifier(urls).test(*messages.test()):
            print(ok(url) if sent else bad(f"{url} (failed)"))
    elif not urls:
        print(warn("No notification links: alerts will only show in the log and the dashboard"))

    flag = "" if target == default_path() else f" --config {target}"
    print()
    print(f"Start watching:  {bold('h2s-alerts' + flag + ' watch')}")
    return 0
