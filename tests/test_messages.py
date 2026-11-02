from datetime import datetime

from h2s_alerts import messages, schedule
from h2s_alerts.search import Listing

NOW = datetime(2026, 11, 3, 17, 5, tzinfo=schedule.AMS)


def home(name="Kastanjelaan 1-135", **kw):
    data = dict(id=1, name=name, slug="k", url="https://www.holland2stay.com/residences/k.html", price=1998.0,
                status="available", city=29, bedrooms=6137, contract=21, furnishing=6261)
    data.update(kw)
    return Listing(**data)


def test_single_alert_is_short():
    title, body = messages.alert("new", home())
    assert title == "Kastanjelaan 1-135"
    assert body == ("Eindhoven · Loft · €1,998\n"
                    "Indefinite · Furnished\n"
                    "https://www.holland2stay.com/residences/k.html")


def test_missing_details_leave_no_gaps():
    title, body = messages.alert("back", home(city=None, bedrooms=None, contract=None, furnishing=None))
    assert title == "Back: Kastanjelaan 1-135"
    assert body == "€1,998\nhttps://www.holland2stay.com/residences/k.html"


def test_price_drop_shows_both_prices():
    _, body = messages.alert("price", home(price=1850.0), "1998")
    assert "€1,998 → €1,850" in body


def test_lottery_alert_has_deadline():
    title, body = messages.alert("lottery", home(status="lottery"), now=NOW)
    assert title.startswith("Lottery: ")
    assert "Sign up by Sun 20:00" in body


def test_digest_caps_length():
    items = [("new", home(f"Home {i}", id=i)) for i in range(14)]
    title, body = messages.digest(items)
    assert title == "14 new homes"
    assert "and 4 more" in body
    assert body.count("https://") == 10


def test_mixed_digest_labels_each_line():
    title, body = messages.digest([("new", home("A")), ("back", home("B")), ("bookable", home("C"))])
    assert title == "3 homes to look at"
    assert "Back: B" in body and "Now bookable: C" in body


def test_other_messages():
    assert messages.welcome("Eindhoven", 1)[1].startswith("Eindhoven\n1 home matches right now")
    assert messages.building("Elzenhagensingel", "Amsterdam", 90)[1] == "Amsterdam · 90 homes · not on sale yet"
    assert "14:30" in messages.paused("Cloudflare is blocking automated requests",
                                      datetime(2026, 11, 3, 14, 30, tzinfo=schedule.AMS))[1]
    assert messages.money(1135.5) == "€1,135.50"
