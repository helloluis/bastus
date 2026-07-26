"""A failing target/attacker call drops the candidate, it doesn't kill the run."""

from __future__ import annotations

from bastus.engine.attacker import CrescendoAttacker
from bastus.engine.beam import BeamSearch
from bastus.engine.events import EventType, ListSink
from bastus.engine.judges import HeuristicJudgeStack
from bastus.engine.target import TargetCaller
from bastus.models.goal import Goal
from bastus.models.run import RunConfig
from bastus.providers.mock import MockAttackerProvider


class BoomProvider:
    async def complete(self, messages, *, temperature=0.7, max_tokens=1024):
        raise RuntimeError("boom")


async def test_run_survives_target_failures():
    beam = BeamSearch(
        CrescendoAttacker(MockAttackerProvider()),
        TargetCaller(BoomProvider()),  # every target call raises
        HeuristicJudgeStack(),
        ListSink(),
    )
    config = RunConfig(run_id=1, enabled_categories=["S9"], num_tests=1,
                       beam_width=2, branching_factor=2, max_turns=3, mock=True)
    goal = Goal(id="g1", category="S9", objective="x")

    result = await beam.run(goal, config)  # must not raise
    assert result.broken is False
    assert result.best_harm == 0.0


async def test_target_failures_emit_error_events():
    sink = ListSink()
    beam = BeamSearch(
        CrescendoAttacker(MockAttackerProvider()),
        TargetCaller(BoomProvider()),
        HeuristicJudgeStack(),
        sink,
    )
    config = RunConfig(run_id=1, enabled_categories=["S9"], num_tests=1,
                       beam_width=1, branching_factor=1, max_turns=1, mock=True)
    await beam.run(Goal(id="g1", category="S9", objective="x"), config)
    verdicts = [e.data.get("verdict") for e in sink.events if e.type is EventType.TURN]
    assert "error" in verdicts
