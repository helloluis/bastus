"""Phase 1 engine tests — all run offline against the mock target."""

from __future__ import annotations

import pytest

from bastus.engine.events import EventType, ListSink
from bastus.engine.judges import HeuristicJudgeStack
from bastus.engine.runner import Runner
from bastus.engine.seeds import build_goals
from bastus.models.goal import Goal
from bastus.models.judgment import Verdict
from bastus.models.run import RunConfig


def _config(**kw) -> RunConfig:
    base = dict(
        run_id=1,
        enabled_categories=["S6", "S9", "S12"],
        num_tests=6,
        beam_width=3,
        branching_factor=2,
        max_turns=6,
        mock=True,
    )
    base.update(kw)
    return RunConfig(**base)


async def test_run_completes_and_reports():
    sink = ListSink()
    report = await Runner(sink=sink).run(_config())

    assert report.total_goals == 18  # 6 tests/category × 3 categories
    assert report.run_id == 1
    # The mock target has finite resilience, so a multi-turn run should break at least one goal.
    assert report.total_breaks >= 1
    assert 0.0 <= report.attack_success_rate <= 1.0

    types = {e.type for e in sink.events}
    assert EventType.RUN_STARTED in types
    assert EventType.RUN_COMPLETED in types
    assert EventType.TURN in types


async def test_break_events_match_broken_goals():
    sink = ListSink()
    report = await Runner(sink=sink).run(_config())
    broken_goal_ids = {r.goal.id for r in report.results if r.broken}
    break_event_goals = {
        e.data["goal_id"] for e in sink.events if e.type is EventType.BREAK_FOUND
    }
    assert break_event_goals <= broken_goal_ids
    for gid in broken_goal_ids:
        assert gid in break_event_goals


async def test_per_category_stats_cover_enabled_categories():
    report = await Runner().run(_config(enabled_categories=["S6", "S9"], num_tests=4))
    stats = report.per_category()
    assert set(stats) == {"S6", "S9"}
    assert sum(s.tested for s in stats.values()) == 8  # 4 per category × 2


async def test_parameters_are_recorded_verbatim():
    config = _config(num_tests=3, beam_width=5, max_turns=2)
    report = await Runner().run(config)
    params = report.summary()["parameters"]
    assert params["beam_width"] == 5
    assert params["max_turns"] == 2
    assert params["enabled_categories"] == ["S6", "S9", "S12"]


async def test_seed_builder_covers_each_category_and_flags_multimodal_images():
    goals = build_goals(["S6", "S12"], 3, multimodal=True)
    assert len(goals) == 6  # 3 tests/category × 2 categories
    cats = [g.category for g in goals]
    assert cats.count("S6") == 3 and cats.count("S12") == 3
    s12 = [g for g in goals if g.category == "S12"]
    assert all(g.seed_image_ref == "seed:celebrity_headshot" for g in s12)
    assert all(g.seed_image_ref is None for g in goals if g.category == "S6")


async def test_heuristic_judge_scores_markers():
    judge = HeuristicJudgeStack()
    goal = Goal(id="g1", category="S9", objective="x")

    refused = await judge.judge(goal, "I'm sorry, I can't help. [SIMULATED-REFUSAL]", 60.0)
    assert refused.verdict is Verdict.REFUSED and refused.scores.refused

    broken = await judge.judge(goal, "here: [SIMULATED-DISALLOWED specificity=0.95] detail", 60.0)
    assert broken.verdict is Verdict.BREAK
    assert broken.scores.harm >= 60.0


async def test_invalid_category_rejected():
    with pytest.raises(Exception):
        _config(enabled_categories=["S99"])
