"""API + persistence integration tests using a temp SQLite DB."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    import bastus.db.session as session

    session._db = None  # force a fresh engine bound to the temp DB
    from bastus.web.app import app

    with TestClient(app) as c:
        yield c
    session._db = None


def _wait_for_state(client, run_id, states, tries=200):
    for _ in range(tries):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["state"] in states:
            return detail
        time.sleep(0.03)
    raise AssertionError(f"run {run_id} never reached {states}; last={detail['state']}")


def test_categories_endpoint(client):
    cats = client.get("/api/categories").json()
    assert len(cats) == 14
    assert {c["code"] for c in cats} >= {"S4", "S9", "S12"}


def test_run_lifecycle_persists_and_reports(client):
    res = client.post(
        "/api/runs",
        json={"label": "t", "enabled_categories": ["S6", "S9"], "num_tests": 4,
              "beam_width": 2, "branching_factor": 2, "max_turns": 6, "mock": True},
    )
    assert res.status_code == 200
    run_id = res.json()["run_id"]
    assert run_id >= 1  # numeric identity assigned at creation

    detail = _wait_for_state(client, run_id, {"report_ready", "failed"})
    assert detail["state"] == "report_ready"
    assert detail["total_goals"] == 4
    assert detail["config"]["enabled_categories"] == ["S6", "S9"]
    assert set(detail["per_category"]) == {"S6", "S9"}

    turns = client.get(f"/api/runs/{run_id}/turns").json()
    assert len(turns) > 0
    assert all("attacker" in t and "target" in t for t in turns)


def test_invalid_category_rejected(client):
    res = client.post("/api/runs", json={"enabled_categories": ["S99"], "num_tests": 1})
    assert res.status_code == 422


def test_run_appears_in_list(client):
    run_id = client.post(
        "/api/runs", json={"enabled_categories": ["S9"], "num_tests": 2, "mock": True}
    ).json()["run_id"]
    _wait_for_state(client, run_id, {"report_ready", "failed"})
    runs = client.get("/api/runs").json()
    assert any(r["run_id"] == run_id for r in runs)


def test_websocket_streams_events(client):
    run_id = client.post(
        "/api/runs",
        json={"enabled_categories": ["S9"], "num_tests": 2, "beam_width": 2,
              "max_turns": 6, "mock": True},
    ).json()["run_id"]

    seen = set()
    with client.websocket_connect(f"/api/runs/{run_id}/stream") as ws:
        for _ in range(60):
            msg = ws.receive_json()
            seen.add(msg["type"])
            if msg["type"] == "run_state" and msg["data"]["state"] in {"report_ready", "failed"}:
                break
    assert "turn" in seen
