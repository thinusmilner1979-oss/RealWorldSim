"""API tests with FastAPI's test client (no browser)."""
from fastapi.testclient import TestClient

from realworldsim.server import app as server


def client():
    server.clock.reset(seed=1)
    return TestClient(server.app)


def test_meta_state_and_geo():
    c = client()
    meta = c.get("/api/meta").json()
    assert len(meta["countries"]) >= 190 and "hormuz" in meta["chokepoints"]
    st = c.get("/api/state").json()
    assert st["state"]["day"] == 0
    geo = c.get("/api/geo")
    assert geo.status_code == 200 and b"FeatureCollection" in geo.content[:50]


def test_step_and_intervene():
    c = client()
    r = c.post("/api/control", json={"action": "step", "days": 45}).json()
    assert r["day"] == 45
    r = c.post("/api/intervene", json={"kind": "declare_war", "a": "chn", "b": "twn", "value": 0.5})
    assert r.status_code == 200
    st = c.get("/api/state").json()["state"]
    assert any(k["a"] == "CHN" for k in st["conflicts"])
    assert c.post("/api/intervene", json={"kind": "declare_war", "a": "XXX", "b": "TWN"}).status_code == 404
    assert c.post("/api/intervene", json={"kind": "bogus"}).status_code == 400
    assert c.get("/api/country/ZAF").json()["name"] == "South Africa"
    assert c.get("/api/history/country/zaf").status_code == 200
    assert len(c.get("/api/events").json()) > 0
    assert c.get("/api/export/csv").text.startswith("date,")


def test_index_served():
    c = client()
    r = c.get("/")
    assert r.status_code == 200 and b"RealWorldSim" in r.content
    assert c.get("/static/vendor/d3.min.js").status_code == 200
