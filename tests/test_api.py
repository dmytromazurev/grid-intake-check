from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gridintake.api import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def data(vilnius_path):
    return vilnius_path.read_bytes()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_rulepacks(client):
    assert "default" in client.get("/v1/rulepacks").json()["rulepacks"]
    assert client.get("/v1/rulepacks/default").json()["snap_tolerance_m"] == 1.0
    assert client.get("/v1/rulepacks/nope").status_code == 404


def test_check_json(client, data):
    r = client.post("/v1/check", files={"file": ("vilnius.json", data, "application/json")}, params={"issue_limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["score"] == 45
    assert len(body["issues"]) == 5 and body["issues_total"] == 89


def test_check_csv_and_html(client, data):
    r = client.post("/v1/check", files={"file": ("v.json", data)}, params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv") and r.text.startswith("check,severity")
    r = client.post("/v1/check", files={"file": ("v.json", data)}, params={"format": "html"})
    assert "<svg" in r.text


def test_check_rejects_projected(client):
    gj = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [582510, 6061948]}}]}
    r = client.post("/v1/check", files={"file": ("p.geojson", json.dumps(gj))})
    assert r.status_code == 422 and "projected CRS" in r.json()["detail"]


def test_check_rejects_garbage(client):
    assert client.post("/v1/check", files={"file": ("x.json", b"not json")}).status_code == 422


def test_reconcile_simulated(client, data):
    r = client.post("/v1/reconcile", files={"file": ("v.json", data)}, data={"simulate": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic_detections"] is True and body["systematic_offsets"]


def test_formulas_with_override(client, data):
    r = client.post("/v1/formulas", files={"file": ("v.json", data)}, data={"mapping": json.dumps({"material": {"concrete": "CONC_12M"}})})
    assert '"CONC_12M"' in r.json()["formulas"][0]["formula"]


def test_customer_request(client, data):
    r = client.post("/v1/customer-request", files={"file": ("v.json", data)}, data={"recipient": "Ona"})
    assert r.text.startswith("Subject: Data review") and "Hi Ona," in r.text
