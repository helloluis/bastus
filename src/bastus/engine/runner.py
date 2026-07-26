"""Top-level run driver: builds providers, runs beam search per goal, aggregates.

Goal concurrency is capped so a large run doesn't open unbounded connections to the
target; within each goal the beam expands its branches concurrently.
"""

from __future__ import annotations

import asyncio

from bastus.config import Settings, load_settings
from bastus.engine.attacker import CrescendoAttacker
from bastus.engine.beam import BeamSearch, GoalResult
from bastus.engine.control import NULL_CONTROL, RunControl
from bastus.engine.events import Event, EventSink, EventType, ListSink
from bastus.engine.judges import HeuristicJudgeStack, JudgeStack, LLMJudgeStack
from bastus.engine.report import RunReport
from bastus.engine.seeds import build_goals
from bastus.engine.target import TargetCaller
from bastus.models.run import RunConfig
from bastus.providers.mock import MockAttackerProvider, MockTargetProvider
from bastus.providers.openai_compat import OpenAICompatProvider

GOAL_CONCURRENCY = 4


def _build_components(
    config: RunConfig, settings: Settings
) -> tuple[CrescendoAttacker, TargetCaller, JudgeStack]:
    if config.mock:
        return (
            CrescendoAttacker(MockAttackerProvider()),
            TargetCaller(MockTargetProvider()),
            HeuristicJudgeStack(),
        )

    missing = [
        name
        for name, val in {
            "ATTACKER_ENDPOINT": settings.attacker_endpoint,
            "ATTACKER_MODEL": settings.attacker_model,
            "TARGET_ENDPOINT": settings.target_endpoint,
            "TARGET_MODEL": settings.target_model,
            "JUDGE_ENDPOINT": settings.judge_endpoint,
            "JUDGE_MODEL": settings.judge_model,
        }.items()
        if not val
    ]
    if missing:
        raise RuntimeError(f"Live run missing settings: {', '.join(missing)} (set them or use --mock)")

    attacker = OpenAICompatProvider(
        settings.attacker_endpoint, settings.attacker_model, settings.attacker_api_key,
        force_temperature=settings.attacker_force_temperature,
    )
    target = OpenAICompatProvider(
        settings.target_endpoint, settings.target_model, settings.target_api_key or "EMPTY",
        force_temperature=settings.target_force_temperature,
    )
    judge = OpenAICompatProvider(
        settings.judge_endpoint, settings.judge_model, settings.judge_api_key or "EMPTY",
        force_temperature=settings.judge_force_temperature,
    )
    return CrescendoAttacker(attacker), TargetCaller(target), LLMJudgeStack(judge)


class Runner:
    def __init__(self, sink: EventSink | None = None, settings: Settings | None = None) -> None:
        self.sink = sink or ListSink()
        self.settings = settings or load_settings()

    async def run(self, config: RunConfig, control: RunControl = NULL_CONTROL) -> RunReport:
        attacker, target, judges = _build_components(config, self.settings)
        goals = build_goals(config.enabled_categories, config.num_tests, multimodal=config.multimodal)
        beam = BeamSearch(attacker, target, judges, self.sink)

        await self.sink.emit(
            Event(
                EventType.RUN_STARTED,
                {
                    "run_id": config.run_id,
                    "num_goals": len(goals),
                    "beam_width": config.beam_width,
                    "parameters": config.parameters_summary(),
                },
            )
        )

        semaphore = asyncio.Semaphore(GOAL_CONCURRENCY)

        async def run_goal(goal) -> GoalResult:
            async with semaphore:
                return await beam.run(goal, config, control)

        results = await asyncio.gather(*(run_goal(g) for g in goals))
        report = RunReport(run_id=config.run_id, config=config, results=list(results))

        await self.sink.emit(
            Event(
                EventType.RUN_COMPLETED,
                {"run_id": config.run_id, "goals": report.total_goals, "breaks": report.total_breaks},
            )
        )
        return report
