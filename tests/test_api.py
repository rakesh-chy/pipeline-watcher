"""FastAPI app - heartbeat ingest + JSON status."""

from __future__ import annotations

from fastapi.testclient import TestClient

from watcher.api import create_app
from watcher.models import Pipeline


def test_healthz(storage):
    app = create_app(storage=storage, settings=storage.settings)
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_register_and_heartbeat(storage):
    app = create_app(storage=storage, settings=storage.settings)
    client = TestClient(app)
    r = client.post(
        "/pipelines",
        json=Pipeline(name="orders", expected_interval_seconds=600).model_dump(),
    )
    assert r.status_code == 201
    r = client.post("/heartbeat", json={"pipeline": "orders", "status": "success"})
    assert r.status_code == 202


def test_heartbeat_for_unknown_pipeline_404s(storage):
    app = create_app(storage=storage, settings=storage.settings)
    client = TestClient(app)
    r = client.post("/heartbeat", json={"pipeline": "ghost", "status": "success"})
    assert r.status_code == 404


def test_status_json_lists_pipelines(storage):
    app = create_app(storage=storage, settings=storage.settings)
    client = TestClient(app)
    client.post(
        "/pipelines",
        json=Pipeline(name="orders", expected_interval_seconds=600).model_dump(),
    )
    client.post("/heartbeat", json={"pipeline": "orders", "status": "success"})
    r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert any(p["pipeline"] == "orders" for p in data["pipelines"])


def test_status_page_renders(storage):
    app = create_app(storage=storage, settings=storage.settings)
    client = TestClient(app)
    client.post(
        "/pipelines",
        json=Pipeline(name="orders", expected_interval_seconds=600).model_dump(),
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "pipeline-watcher" in r.text
    assert "orders" in r.text
