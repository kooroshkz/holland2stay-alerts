import base64
import json
import urllib.error
import urllib.request

import pytest

from h2s_alerts import demo
from h2s_alerts.config import build
from h2s_alerts.dashboard import overview, serve


@pytest.fixture
def running():
    servers = []

    def start(password=None):
        store, cfg = demo.sample()
        cfg.dashboard = build({"dashboard": {"port": 1, "password": password}}, {}).dashboard
        cfg.dashboard.port = 0
        server = serve(store, cfg)
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()


def get(url, auth=None):
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def test_overview_shape():
    store, cfg = demo.sample()
    data = overview(store, cfg)
    assert data["stats"]["matching"] == len(data["available"]) > 0
    assert len(data["heatmap"]) == 7 and all(len(row) == 24 for row in data["heatmap"])
    assert data["lottery"]
    assert [b["street"] for b in data["buildings"]] == ["Strijp Laan", "Noorderpark"]
    assert data["stats"]["median_minutes"] > 0


def test_pages_and_api(running):
    base = running()
    status, ctype, body = get(base + "/")
    assert status == 200 and "text/html" in ctype and b"holland2stay" in body
    assert get(base + "/app.js")[0] == 200
    status, _, body = get(base + "/api/overview")
    assert json.loads(body)["version"]
    assert json.loads(get(base + "/healthz")[2])["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/nope")
    assert e.value.code == 404


def test_password(running):
    base = running(password="secret")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/api/overview")
    assert e.value.code == 401
    assert get(base + "/api/overview", auth="me:secret")[0] == 200
    assert get(base + "/healthz")[0] == 200  # health checks need no password


def test_static_demo_export(tmp_path):
    out = demo.export(tmp_path / "demo")
    data = json.loads((out / "api" / "overview.json").read_text())
    assert data["demo"] is True
    assert (out / "index.html").exists() and (out / "app.css").exists()


def test_port_in_use_is_not_fatal(running):
    base = running()
    store, cfg = demo.sample()
    cfg.dashboard.port = int(base.rsplit(":", 1)[1])
    assert serve(store, cfg) is None
