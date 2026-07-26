"""Resistance metric + invalid-run guard."""

from __future__ import annotations

from bastus.engine.beam import GoalResult
from bastus.engine.report import RunReport
from bastus.models.goal import Goal
from bastus.models.run import RunConfig
from bastus.web.manager import invalid_run_reason


def _report(broken_flags):
    results = [GoalResult(goal=Goal(id=f"g{i}", category="S9", objective="x"), broken=b)
               for i, b in enumerate(broken_flags)]
    return RunReport(run_id=1, config=RunConfig(enabled_categories=["S9"]), results=results)


def test_resistance_is_complement_of_asr():
    r = _report([True, False, False, False, False, False])  # 1/6 broke
    assert round(r.attack_success_rate, 2) == 0.17
    assert round(r.resistance, 2) == 0.83
    assert round(r.summary()["resistance"], 2) == 0.83


def test_resistance_full_when_nothing_breaks():
    r = _report([False, False])
    assert r.resistance == 1.0


def test_invalid_run_when_all_calls_error():
    assert invalid_run_reason(ok_turns=0, error_turns=12) is not None


def test_valid_run_with_some_successes():
    assert invalid_run_reason(ok_turns=50, error_turns=3) is None


def test_valid_run_with_no_turns_at_all():
    # e.g. aborted before any call — not an "errored" run
    assert invalid_run_reason(ok_turns=0, error_turns=0) is None


def test_has_active_runs_property():
    from bastus.web.manager import RunManager

    m = RunManager.__new__(RunManager)  # bypass __init__ (no db needed)

    class _Task:
        def __init__(self, done):
            self._done = done

        def done(self):
            return self._done

    m.tasks = {}
    assert m.has_active_runs is False
    m.tasks = {1: _Task(False)}
    assert m.has_active_runs is True
    m.tasks = {1: _Task(True)}
    assert m.has_active_runs is False
