"""Things that go wrong in real life: failures mid-check, broken channels, odd settings."""

import base64
import os
import random
import urllib.error
import urllib.request

import pytest
from conftest import Clock, FakeH2S, FakeNotifier, home

from h2s_alerts import cli, demo
from h2s_alerts.client import RateLimited, _retry_after
from h2s_alerts.config import build
from h2s_alerts.dashboard import serve
from h2s_alerts.notify import Notifier
from h2s_alerts.watcher import MAX_PAUSE, Watcher


class FailOnLottery(FakeH2S):
    """Answers the normal search, then fails on the lottery search."""

    lottery_fail = None

    def products(self, filters, fields, page_size=300, page=1, sort=None):
        if ("available_to_book", "336", "eq") in filters and self.lottery_fail:
            self.requests += 1
            raise self.lottery_fail
        return super().products(filters, fields, page_size, page, sort)


def watcher(store, make_cfg, h2s, notifier=None, **cfg):
    clock = Clock()
    n = notifier or FakeNotifier()
    w = Watcher(make_cfg(**cfg), store, client=h2s, notifier=n, clock=clock, rng=random.Random(0))
    return w, n, clock


def test_alert_survives_a_failure_later_in_the_same_check(store, make_cfg):
    h2s = FailOnLottery([home(1)])
    w, n, clock = watcher(store, make_cfg, h2s)
    w.tick()
    h2s.add(home(2))
    h2s.lottery_fail = RateLimited("slow down", retry_after=120)
    clock.advance(minutes=15)  # the lottery is due again
    assert w.tick() == 120  # the check failed and backs off
    assert "Teststraat 2" in n.titles()  # but the new home was stored first and still sent


def test_one_broken_channel_does_not_repeat_alerts_elsewhere():
    class Server:
        def __init__(self, ok):
            self.ok, self.calls = ok, 0

        def notify(self, **kw):
            self.calls += 1
            return self.ok

        def url(self, privacy=True):
            return "fake://x"

    good, broken = Server(True), Server(False)
    n = Notifier([])
    n.apprise = [good, broken]
    assert n.send("t", "b") is True
    n.apprise = [Server(False)]
    assert n.send("t", "b") is False


def test_building_notices_wait_for_quiet_hours(store, make_cfg):
    h2s = FakeH2S([home(1)])
    w, n, clock = watcher(store, make_cfg, h2s, notify={"quiet_hours": "13:00-18:00"})
    w.tick()  # 10:00
    h2s.add(*[home(100 + i, name=f"Nieuwbouw {i}", status=6203, price=5000) for i in range(3)])
    clock.advance(hours=6)  # 16:00, quiet
    w.tick()
    assert not any(t.startswith("New building") for t in n.titles())
    clock.advance(hours=3)  # 19:00
    w.tick()
    assert "New building: Nieuwbouw" in n.titles()


def test_turning_the_lottery_off_clears_it(store, make_cfg):
    h2s = FakeH2S([home(1), home(2, status=336)])
    w, n, clock = watcher(store, make_cfg, h2s)
    w.tick()
    assert store.active("lottery")
    off = Watcher(make_cfg(search={"cities": ["Eindhoven"], "lottery": False}), store, client=h2s,
                  notifier=n, clock=clock)
    clock.advance(minutes=2)
    off.tick()
    assert not store.active("lottery")


def test_huge_retry_after_is_capped(store, make_cfg):
    h2s = FakeH2S([home(1)])
    w, n, clock = watcher(store, make_cfg, h2s)
    w.tick()
    h2s.fail = RateLimited("slow down", retry_after=10**9)
    clock.advance(minutes=2)
    assert w.tick() == MAX_PAUSE
    assert _retry_after("inf") is None


def test_transaction_rolls_back(store):
    with pytest.raises(RuntimeError), store.transaction():
        store.set("x", 1)
        raise RuntimeError
    assert store.get("x") is None


def test_password_with_accents_and_numbers():
    store, cfg = demo.sample()
    cfg.dashboard = build({"dashboard": {"password": 1234}}, {}).dashboard
    assert cfg.dashboard.password == "1234"
    cfg.dashboard.password = "pässwort"
    cfg.dashboard.port = 0
    server = serve(store, cfg)
    base = f"http://127.0.0.1:{server.server_address[1]}/api/overview"
    try:
        def get(secret):
            req = urllib.request.Request(base)
            req.add_header("Authorization", "Basic " + base64.b64encode(f"u:{secret}".encode()).decode())
            return urllib.request.urlopen(req, timeout=5).status

        assert get("pässwort") == 200
        with pytest.raises(urllib.error.HTTPError):
            get("wrong")
    finally:
        server.shutdown()


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs file permissions")
def test_unwritable_data_folder_is_explained(tmp_path, capsys):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    config = tmp_path / "config.toml"
    config.write_text(f'[general]\ndata_dir = "{locked / "data"}"\n[search]\ncities = ["Eindhoven"]\n')
    try:
        assert cli.main(["watch", "--once", "--no-dashboard", "--config", str(config)]) == 1
    finally:
        locked.chmod(0o700)
    assert "Can't write to" in capsys.readouterr().err


def test_health_command(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[dashboard]\nenabled = false\n")
    assert cli.main(["health", "--config", str(config)]) == 0
    config.write_text("[dashboard]\nport = 1\n")
    assert cli.main(["health", "--config", str(config)]) == 1
