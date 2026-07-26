"""RunPod provisioning + live-run gating tests (simulated provider, 0 delay)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("BASTUS_SIM_STEP_DELAY", "0")  # instant provisioning
    import bastus.db.session as session

    session._db = None
    from bastus.web.app import app

    with TestClient(app) as c:
        yield c
    session._db = None


def _wait_server(client, states, tries=200):
    for _ in range(tries):
        s = client.get("/api/server").json()
        if s["state"] in states:
            return s
        time.sleep(0.02)
    raise AssertionError(f"server never reached {states}; last={s['state']}")


def test_server_starts_not_provisioned(client):
    assert client.get("/api/server").json()["state"] == "not_provisioned"


def test_provision_reaches_ready_with_inspect_link(client):
    assert client.post("/api/server/provision").status_code == 200
    s = _wait_server(client, {"ready", "error"})
    assert s["state"] == "ready"
    assert s["console_url"] and s["pod_id"]
    assert "abliterated" in (s["model"] or "")


def test_double_provision_conflicts(client):
    client.post("/api/server/provision")
    # Immediately requesting again while provisioning/ready must 409.
    assert client.post("/api/server/provision").status_code == 409


def test_live_run_blocked_until_provisioned(client):
    # Before provisioning: a live run is rejected.
    res = client.post("/api/runs", json={"enabled_categories": ["S9"], "num_tests": 1, "mock": False})
    assert res.status_code == 409

    # A mock run is always allowed.
    assert client.post("/api/runs", json={"enabled_categories": ["S9"], "num_tests": 1, "mock": True}).status_code == 200

    # After provisioning, the live run passes the gate (it may later fail for lack
    # of real endpoints, but creation is accepted).
    client.post("/api/server/provision")
    _wait_server(client, {"ready"})
    res = client.post("/api/runs", json={"enabled_categories": ["S9"], "num_tests": 1, "mock": False})
    assert res.status_code == 200
    assert res.json()["run_id"] >= 1


def test_destroy_resets_state(client):
    client.post("/api/server/provision")
    _wait_server(client, {"ready"})
    assert client.post("/api/server/destroy").status_code == 200
    _wait_server(client, {"not_provisioned"})
    assert client.post("/api/server/destroy").status_code == 409  # nothing to destroy
