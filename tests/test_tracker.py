from datetime import UTC, datetime, timedelta

from h2s_alerts.search import Listing
from h2s_alerts.tracker import Tracker

T0 = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def L(pid, price=1000.0, status="available"):
    return Listing(pid, f"Home {pid}", f"home-{pid}", f"https://x/{pid}", price, status)


def snap(*listings):
    return {x.id: x for x in listings}


def kinds(result):
    return [(c.kind, c.listing.id) for c in result.changes]


def test_first_run_is_quiet(store):
    t = Tracker(store, "fp")
    r = t.apply("available", snap(L(1), L(2)), T0)
    assert r.baseline and not r.filters_changed and r.changes == []
    assert set(store.active("available")) == {1, 2}


def test_new_home(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1)), T0)
    r = t.apply("available", snap(L(1), L(2)), T0 + timedelta(minutes=2))
    assert kinds(r) == [("new", 2)]


def test_gone_needs_two_misses(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1), L(2)), T0)
    assert kinds(t.apply("available", snap(L(1)), T0 + timedelta(minutes=2))) == []
    r = t.apply("available", snap(L(1)), T0 + timedelta(minutes=4))
    assert kinds(r) == [("gone", 2)]


def test_one_odd_answer_changes_nothing(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1), L(2)), T0)
    t.apply("available", snap(L(1)), T0 + timedelta(minutes=2))
    r = t.apply("available", snap(L(1), L(2)), T0 + timedelta(minutes=4))
    assert r.changes == []


def test_empty_answer_is_doubted_longer(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(*[L(i) for i in range(6)]), T0)
    assert t.apply("available", {}, T0 + timedelta(minutes=2)).changes == []
    assert t.apply("available", {}, T0 + timedelta(minutes=4)).changes == []
    assert len(t.apply("available", {}, T0 + timedelta(minutes=6)).changes) == 6


def test_back_after_a_while_but_not_after_a_blink(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1), L(2)), T0)
    t.apply("available", snap(L(2)), T0 + timedelta(minutes=1))
    t.apply("available", snap(L(2)), T0 + timedelta(minutes=2))  # 1 is gone now
    assert t.apply("available", snap(L(1), L(2)), T0 + timedelta(minutes=3)).changes == []  # blink
    t.apply("available", snap(L(2)), T0 + timedelta(minutes=4))
    t.apply("available", snap(L(2)), T0 + timedelta(minutes=5))
    r = t.apply("available", snap(L(1), L(2)), T0 + timedelta(hours=3))
    assert kinds(r) == [("back", 1)]


def test_lottery_home_becomes_bookable(store):
    t = Tracker(store, "fp")
    t.apply("available", {}, T0)
    t.apply("lottery", snap(L(7, status="lottery")), T0)
    r = t.apply("available", snap(L(7)), T0 + timedelta(minutes=2))
    assert kinds(r) == [("bookable", 7)]
    assert t.apply("lottery", {}, T0 + timedelta(minutes=4)).changes == []


def test_new_lottery_home(store):
    t = Tracker(store, "fp")
    t.apply("lottery", {}, T0)
    assert kinds(t.apply("lottery", snap(L(9, status="lottery")), T0 + timedelta(minutes=2))) == [("lottery", 9)]


def test_price_drop(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1, 1500)), T0)
    assert t.apply("available", snap(L(1, 1500.4)), T0 + timedelta(minutes=2)).changes == []
    r = t.apply("available", snap(L(1, 1400)), T0 + timedelta(minutes=4))
    assert kinds(r) == [("price", 1)] and r.changes[0].detail == "1500"
    assert t.apply("available", snap(L(1, 1450)), T0 + timedelta(minutes=6)).changes == []


def test_new_filters_start_quietly(store):
    Tracker(store, "old").apply("available", snap(L(1), L(2)), T0)
    r = Tracker(store, "new").apply("available", snap(L(2), L(3)), T0 + timedelta(minutes=2))
    assert r.baseline and r.filters_changed and r.changes == []
    assert set(store.active("available")) == {2, 3}
    assert store.listing(1)["gone_at"] is None  # left the search, was not taken


def test_time_on_market(store):
    t = Tracker(store, "fp")
    t.apply("available", {}, T0)
    t.apply("available", snap(L(1)), T0 + timedelta(minutes=10))
    t.apply("available", {}, T0 + timedelta(minutes=12))
    r = t.apply("available", {}, T0 + timedelta(minutes=14))
    assert kinds(r) == [("gone", 1)]
    assert r.changes[0].detail == "0"  # it was last seen when it appeared

    t.apply("available", snap(L(2)), T0 + timedelta(minutes=20))
    t.apply("available", snap(L(2)), T0 + timedelta(minutes=50))
    t.apply("available", {}, T0 + timedelta(minutes=52))
    r = t.apply("available", {}, T0 + timedelta(minutes=54))
    assert r.changes[0].detail == str(30 * 60)


def test_homes_from_the_first_run_have_no_known_start(store):
    t = Tracker(store, "fp")
    t.apply("available", snap(L(1)), T0)
    t.apply("available", {}, T0 + timedelta(minutes=2))
    r = t.apply("available", {}, T0 + timedelta(minutes=4))
    assert r.changes[0].detail is None
