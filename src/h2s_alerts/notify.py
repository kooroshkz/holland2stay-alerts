"""Send notifications through Apprise (Telegram, Discord, ntfy, Slack, email and many more)."""

from __future__ import annotations

import logging

import apprise

log = logging.getLogger("h2s_alerts")
logging.getLogger("apprise").setLevel(logging.WARNING)


def _short(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/")


def masked(url: str) -> str:
    server = apprise.Apprise.instantiate(url)
    if server is None:
        return url.split("://", 1)[0] + "://…"
    return _short(server.url(privacy=True))


class Notifier:
    def __init__(self, urls: list[str]):
        self.urls = urls
        self.apprise = apprise.Apprise()
        self.invalid = [u for u in urls if not self.apprise.add(u)]

    @property
    def enabled(self) -> bool:
        return len(self.apprise) > 0

    def send(self, title: str, body: str) -> bool:
        if not self.enabled:
            log.info("%s | %s", title, body.replace("\n", " | "))
            return True
        # Per channel: if one works and another is broken, the message counts as sent,
        # so the working channel is not sent the same alert again.
        delivered = False
        for server in self.apprise:
            try:
                ok = bool(server.notify(title=title, body=body, body_format=apprise.NotifyFormat.TEXT))
            except Exception:  # a broken plugin must never stop the watcher
                ok = False
            if ok:
                delivered = True
            else:
                log.warning("Couldn't send to %s", _short(server.url(privacy=True)))
        return delivered

    def test(self, title: str, body: str) -> list[tuple[str, bool]]:
        results = [(masked(u), False) for u in self.invalid]
        for server in self.apprise:
            try:
                ok = bool(server.notify(title=title, body=body, body_format=apprise.NotifyFormat.TEXT))
            except Exception:
                ok = False
            results.append((_short(server.url(privacy=True)), ok))
        return results
