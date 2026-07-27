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


def test_narrative_highlights_broken_categories():
    from bastus.engine.report import narrative_summary

    per_cat = {
        "S10": {"tested": 2, "broken": 2, "best_harm": 79},
        "S8": {"tested": 2, "broken": 1, "best_harm": 87},
        "S1": {"tested": 2, "broken": 0, "best_harm": 20},
    }
    text = narrative_summary(per_cat, state="report_ready")
    assert "ASR" in text and "resisted" in text
    # worst = S8 by best_harm; both broken cats named
    assert "S8 Intellectual Property" in text
    assert "S10 Hate" in text
    assert "breaking every attempt" in text or "S10" in text  # S10 broke 2/2
    assert 2 <= text.count(".") <= 4  # roughly 2-3 sentences


def test_narrative_clean_run():
    from bastus.engine.report import narrative_summary

    per_cat = {"S1": {"tested": 2, "broken": 0, "best_harm": 12}}
    text = narrative_summary(per_cat, state="report_ready")
    assert "No category was broken" in text


def test_narrative_failed_run_no_goals():
    from bastus.engine.report import narrative_summary

    assert "not a valid baseline" in narrative_summary({}, state="failed")


def test_narrative_failed_run_does_not_claim_resistance():
    from bastus.engine.report import narrative_summary

    # a failed run with partial data must NOT read as a clean "resisted X%" baseline
    per_cat = {"S1": {"tested": 2, "broken": 0, "best_harm": 0}}
    text = narrative_summary(per_cat, state="failed", error_turns=8)
    assert "not a valid baseline" in text
    assert "resisted" not in text
    assert "errored" in text


def test_narrative_notes_errors():
    from bastus.engine.report import narrative_summary

    per_cat = {"S1": {"tested": 2, "broken": 0, "best_harm": 5}}
    text = narrative_summary(per_cat, state="report_ready", error_turns=3)
    assert "errored" in text


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
