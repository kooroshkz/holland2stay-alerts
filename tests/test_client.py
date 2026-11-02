import json

import pytest
import requests

from h2s_alerts import USER_AGENT
from h2s_alerts.client import Blocked, Changed, Client, RateLimited, Unavailable, criteria


class Response:
    def __init__(self, status=200, body=None, headers=None, text=None):
        self.status_code = status
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(*responses):
    return Client(min_gap=0, session=Session(*responses))


def test_identifies_itself_and_sends_no_referer():
    c = client(Response(body={"items": []}))
    c.products([], "items[id]")
    assert c.session.headers["User-Agent"] == USER_AGENT
    assert "Referer" not in c.session.headers
    url, params = c.session.calls[0]
    assert url.endswith("/api/rest/V1/products-render-info")
    assert ("fields", "items[id]") in params


def test_null_items_means_nothing_found():
    assert client(Response(body={"items": None})).products([], "items[id]") == []


def test_criteria_groups():
    p = dict(criteria([("city", "29", "in")], page_size=10, page=2, sort=("entity_id", "DESC")))
    assert p["searchCriteria[filter_groups][0][filters][0][field]"] == "city"
    assert p["searchCriteria[filter_groups][0][filters][0][condition_type]"] == "in"
    assert p["searchCriteria[currentPage]"] == "2"
    assert p["searchCriteria[sortOrders][0][direction]"] == "DESC"


@pytest.mark.parametrize("response, error", [
    (Response(429, text="slow down", headers={"Retry-After": "120"}), RateLimited),
    (Response(403, text="<title>Just a moment...</title>", headers={"cf-mitigated": "challenge"}), Blocked),
    (Response(403, body={"code": "clearance_required"}), Blocked),
    (Response(404, text="<html>not found</html>"), Changed),
    (Response(502, text="bad gateway"), Unavailable),
    (Response(200, text="<html>hello</html>"), Changed),
    (Response(200, body={"something": "else"}), Changed),
])
def test_errors_are_classified(response, error):
    with pytest.raises(error):
        client(response).products([], "items[id]")


def test_retry_after_is_read():
    with pytest.raises(RateLimited) as e:
        client(Response(429, text="", headers={"Retry-After": "90"})).products([], "items[id]")
    assert e.value.retry_after == 90


def test_network_errors_are_unavailable():
    with pytest.raises(Unavailable):
        client(requests.ConnectionError("down")).products([], "items[id]")


def test_buckets():
    body = {"aggregations": {"buckets": [{"name": "city_bucket", "values": [
        {"value": "29", "metrics": [29, 18]}, {"value": "x", "metrics": [0, 1]}]}]}}
    assert client(Response(body=body)).buckets([]) == {"city_bucket": {29: 18}}
