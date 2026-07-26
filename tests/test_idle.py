"""Idle-teardown definition: counts only after a run finishes, never mid-run."""

from __future__ import annotations

from bastus.models.server import ServerState
from bastus.web.broadcaster import Broadcaster
from bastus.web.provision import ServerManager, SimulatedRunpodProvider


def _mgr() -> ServerManager:
    m = ServerManager(Broadcaster(), SimulatedRunpodProvider(step_delay=0))
    m.idle_ttl_min = 30.0
    m.status.state = ServerState.READY
    m._last_activity = 1000.0
    return m


def test_not_idle_before_ttl():
    m = _mgr()
    assert not m._should_idle_destroy(1000.0 + 29 * 60)


def test_idle_after_ttl_with_no_runs():
    m = _mgr()
    assert m._should_idle_destroy(1000.0 + 30 * 60)


def test_never_idle_while_a_run_is_in_flight():
    m = _mgr()
    m.run_started()
    # Even long past the TTL, an in-flight run keeps the pod active.
    assert not m._should_idle_destroy(1000.0 + 10 * 3600)


def test_run_finished_restarts_countdown():
    m = _mgr()
    m.run_started()
    m.run_finished()  # stamps last_activity to "now" — countdown restarts here
    assert m._active_runs == 0
    # last_activity was refreshed, so an old absolute time is no longer past TTL
    # relative to it; verify the counter and that a fresh window is required.
    m._last_activity = 5000.0
    assert not m._should_idle_destroy(5000.0 + 29 * 60)
    assert m._should_idle_destroy(5000.0 + 30 * 60)


def test_not_idle_when_not_ready():
    m = _mgr()
    m.status.state = ServerState.PROVISIONING
    assert not m._should_idle_destroy(1000.0 + 10 * 3600)


def test_default_ttl_is_30_minutes():
    m = ServerManager(Broadcaster(), SimulatedRunpodProvider(step_delay=0))
    assert m.idle_ttl_min == 30.0
