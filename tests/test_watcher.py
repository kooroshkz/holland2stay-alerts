import random

import pytest
from conftest import Clock, FakeH2S, FakeNotifier, home

from h2s_alerts.client import Blocked, Changed, RateLimited, Unavailable
from h2s_alerts.watcher import Watcher


@pytest.fixture
def setup(store, make_cfg):
    def make(homes=(), search=None, notify=None, notifier=None):
        h2s = FakeH2S(list(homes))
        clock = Clock()
        n = notifier or FakeNotifier()
        cfg = make_cfg(search=search, notify=notify)
        w = Watcher(cfg, store, client=h2s, notifier=n, clock=clock, rng=random.Random(0))
        return w, h2s, n, clock
    return make


def test_first_check_says_hello_and_nothing_else(setup):
    w, h2s, n, clock = setup([home(1), home(2)])
    delay = w.tick()
    assert n.titles() == ["Watching Holland2Stay"]
    assert "2 homes match right now" in n.sent[0][1]
    assert 60 <= delay <= 200
    assert w.store.get("status")["state"] == "watching"


def test_new_home_is_announced_with_details(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.add(home(2, name="Kastanjelaan 1-135", bedrooms=6137, price=1998))
    clock.advance(minutes=2)
    w.tick()
    title, body = n.sent[-1]
    assert title == "Kastanjelaan 1-135"
    assert body.startswith("Eindhoven · Loft · €1,998\nIndefinite · Furnished\n")
    w.tick()
    assert len(n.sent) == 2  # never twice


def test_taken_homes_are_quiet(setup):
    w, h2s, n, clock = setup([home(1), home(2)])
    w.tick()
    h2s.remove(2)
    for _ in range(3):
        clock.advance(minutes=2)
        w.tick()
    assert n.titles() == ["Watching Holland2Stay"]
    assert w.store.q("SELECT COUNT(*) FROM events WHERE kind='gone'")[0][0] == 1


def test_many_new_homes_come_as_one_message(setup):
    w, h2s, n, clock = setup()
    w.tick()
    h2s.add(*[home(i) for i in range(10, 16)])
    clock.advance(minutes=2)
    w.tick()
    assert n.titles()[-1] == "6 new homes"


def test_lottery_homes(setup):
    w, h2s, n, clock = setup()
    w.tick()
    h2s.add(home(30, status=336))
    clock.advance(minutes=15)
    w.tick()
    assert n.titles()[-1] == "Lottery: Teststraat 30"
    assert "Sign up by" in n.sent[-1][1]


def test_lottery_off(setup):
    w, h2s, n, clock = setup(search={"cities": ["Eindhoven"], "lottery": False})
    w.tick()
    assert all("336" not in str(call) for call in h2s.calls)


def test_blocked_pauses_tells_once_and_recovers(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.fail = Blocked("Cloudflare is blocking automated requests")
    clock.advance(minutes=2)
    delay = w.tick()
    assert delay == 1800
    assert n.titles()[-1] == "Alerts paused"
    assert w.store.get("status")["state"] == "paused"

    before = h2s.requests
    clock.advance(minutes=10)
    w.tick()
    assert h2s.requests == before  # waits, does not ask again

    clock.advance(minutes=25)
    assert w.tick() == 3600  # still blocked: waits longer
    assert n.titles().count("Alerts paused") == 1

    h2s.fail = None
    clock.advance(hours=2)
    w.tick()
    assert n.titles()[-1] == "Alerts back on"
    assert w.store.get("failures") is None


def test_rate_limit_respects_retry_after(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.fail = RateLimited("slow down", retry_after=240)
    clock.advance(minutes=2)
    assert w.tick() == 240
    assert n.titles() == ["Watching Holland2Stay"]  # short pause, no notice


def test_short_outages_stay_quiet(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.fail = Unavailable("down")
    clock.advance(minutes=2)
    assert w.tick() == 60
    clock.advance(minutes=2)
    assert w.tick() == 120
    assert n.titles() == ["Watching Holland2Stay"]


def test_site_change_is_reported(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.fail = Changed("Holland2Stay moved or removed the listing endpoint")
    clock.advance(minutes=2)
    w.tick()
    assert n.titles()[-1] == "Alerts may be broken"


def test_failed_messages_are_retried(setup):
    flaky = FakeNotifier(ok=False)
    w, h2s, n, clock = setup([home(1)], notifier=flaky)
    w.tick()
    h2s.add(home(2))
    clock.advance(minutes=2)
    w.tick()
    assert flaky.sent == []
    flaky.ok = True
    clock.advance(minutes=2)
    w.tick()
    assert flaky.titles() == ["Teststraat 2"]


def test_quiet_hours_hold_messages_and_drop_stale_ones(setup):
    w, h2s, n, clock = setup([home(1)], notify={"quiet_hours": "09:00-12:00"})
    w.tick()  # 10:00 Amsterdam: quiet, but the welcome is not a listing alert
    h2s.add(home(2), home(3))
    clock.advance(minutes=2)
    w.tick()
    assert [t for t in n.titles() if t.startswith("Teststraat")] == []
    h2s.remove(3)
    for _ in range(2):
        clock.advance(minutes=2)
        w.tick()
    clock.advance(hours=2)
    w.tick()
    assert [t for t in n.titles() if t.startswith("Teststraat")] == ["Teststraat 2"]


def test_changing_the_search_does_not_flood(setup, store, make_cfg):
    w, h2s, n, clock = setup([home(1), home(2, city=25)])
    w.tick()
    cfg = make_cfg(search={"cities": ["Eindhoven", "Rotterdam"]})
    w2 = Watcher(cfg, store, client=h2s, notifier=n, clock=clock)
    clock.advance(minutes=5)
    w2.tick()
    assert n.titles() == ["Watching Holland2Stay", "Search updated"]


def test_existing_homes_on_first_start(setup):
    w, h2s, n, clock = setup([home(1), home(2)], notify={"existing_on_start": True})
    w.tick()
    assert n.titles() == ["Watching Holland2Stay", "Teststraat 1", "Teststraat 2"]


def test_new_building_is_announced(setup):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.add(*[home(100 + i, name=f"Elzenhagensingel {i}", status=6203, price=5000) for i in range(5)])
    clock.advance(hours=7)
    w.tick()
    assert ("New building: Elzenhagensingel", "Eindhoven · 5 homes · not on sale yet") in n.sent


def test_pause_survives_restart(setup, store, make_cfg):
    w, h2s, n, clock = setup([home(1)])
    w.tick()
    h2s.fail = Blocked("blocked")
    clock.advance(minutes=2)
    w.tick()
    h2s.fail = None
    again = Watcher(make_cfg(), store, client=h2s, notifier=n, clock=clock)
    before = h2s.requests
    clock.advance(minutes=1)
    again.tick()
    assert h2s.requests == before
