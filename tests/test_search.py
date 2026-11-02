from conftest import FakeH2S, home

from h2s_alerts.config import build
from h2s_alerts.search import Listing, describe, fetch, filters_for, newest, slug_of, street_of


def search(**kw):
    return build({"search": kw}, {}).search


def test_filters_cover_every_option():
    s = search(cities=["Eindhoven"], exclude_cities=[], bedrooms=["studio", "1"], contract="long",
               occupants=["one"], furnishing=["furnished"], price_min=500, price_max=1500,
               move_in_before="2027-01-31")
    f = filters_for(s, "available")
    assert ("available_to_book", "179", "eq") in f
    assert ("sku", "r-%", "like") in f
    assert ("city", "29", "in") in f
    assert ("no_of_rooms", "104,105", "in") in f
    assert ("type_of_contract", "21,6125,20", "in") in f
    assert ("maximum_number_of_persons", "22", "in") in f
    assert ("finishing", "6261", "in") in f
    assert ("price", "500", "gteq") in f and ("price", "1500", "lteq") in f
    assert ("next_contract_startdate", "2027-01-31 23:59:59", "lteq") in f
    assert filters_for(search(exclude_cities=["Maastricht"]), "lottery")[2] == ("city", "6090", "nin")


def test_fetch_only_residences_that_match():
    h2s = FakeH2S([
        home(1, price=900),
        home(2, price=2500),
        home(3, city=25),
        home(4, sku="p-park-4", name="Parking 4"),
        home(5, status=336),
    ])
    found = fetch(h2s, search(cities=["Eindhoven"], price_max=2000), "available")
    assert list(found) == [1]
    x = found[1]
    assert x.url == "https://www.holland2stay.com/residences/teststraat-1.html"
    assert x.city == 29  # one city in the search, so it is known without asking
    assert x.bedrooms is None


def test_describe_looks_up_details_once():
    h2s = FakeH2S([home(1, bedrooms=106, contract=318, furnishing=72), home(2, bedrooms=104)])
    found = fetch(h2s, search(cities=["Eindhoven"]), "available")
    before = h2s.requests
    describe(h2s, list(found.values()), search(cities=["Eindhoven"]), [])
    assert found[1].bedrooms == 106 and found[1].contract == 318 and found[1].furnishing == 72
    assert found[2].bedrooms == 104
    assert h2s.requests - before <= 12


def test_describe_respects_budget():
    h2s = FakeH2S([home(1, city=6310)])
    x = Listing(1, "x", "x", "u", 1, "available")
    describe(h2s, [x], search(), [], budget=2)
    assert h2s.requests == 2


def test_describe_finds_new_city_ids():
    h2s = FakeH2S([home(1, city=7777)])
    x = Listing(1, "x", "x", "u", 1, "available")
    describe(h2s, [x], search(), [7777])
    assert x.city == 7777
    assert x.city_name == "City 7777"


def test_newest_and_street_names():
    h2s = FakeH2S([home(i, name=f"Elzenhagensingel {i}") for i in range(10, 20)] + [home(5)])
    top, fresh = newest(h2s, search(), after_id=12)
    assert top == 19
    assert {r["id"] for r in fresh} == set(range(13, 20))
    assert street_of("Kon. Wilhelminaplein 29 K3") == "Kon. Wilhelminaplein"
    assert street_of("Elzenhagensingel 303") == "Elzenhagensingel"
    assert slug_of("https://account.holland2stay.com/kastanjelaan-1-135.html") == "kastanjelaan-1-135"
