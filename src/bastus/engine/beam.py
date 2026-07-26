"""Beam search over parallel conversation branches (Cascade-style).

Each turn, every frontier branch proposes `branching_factor` candidate escalations;
each candidate is sent to the target and judged; the frontier is pruned back to
`beam_width` best branches by harm. `beam_width` is the user's "number of agents".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bastus.engine.attacker import CrescendoAttacker
from bastus.engine.control import NULL_CONTROL, RunControl
from bastus.engine.events import Event, EventSink, EventType
from bastus.engine.judges import JudgeStack
from bastus.engine.target import TargetCaller
from bastus.models.conversation import Branch, Role
from bastus.models.goal import Goal
from bastus.models.judgment import Judgment, Verdict
from bastus.models.run import RunConfig

_REFUSAL_PENALTY = 25.0


@dataclass
class GoalResult:
    goal: Goal
    broken: bool = False
    best_harm: float = 0.0
    best_branch: Branch | None = None
    turns_used: int = 0
    breaks: list[tuple[Branch, Judgment]] = field(default_factory=list)


class BeamSearch:
    def __init__(
        self,
        attacker: CrescendoAttacker,
        target: TargetCaller,
        judges: JudgeStack,
        sink: EventSink,
    ) -> None:
        self.attacker = attacker
        self.target = target
        self.judges = judges
        self.sink = sink

    async def _expand(
        self, goal: Goal, branch: Branch, config: RunConfig
    ) -> list[tuple[Branch, Judgment]]:
        try:
            proposals = await self.attacker.propose(goal, branch, config.branching_factor)
        except Exception as exc:  # noqa: BLE001 — a dead attacker call drops this branch, not the run
            await self._emit_error(goal, branch.id, f"attacker: {exc}")
            return []

        async def evaluate(text: str) -> tuple[Branch, Judgment] | None:
            child = branch.child()
            try:
                image_ref = goal.seed_image_ref if child.depth == 1 else None
                child.add(Role.ATTACKER, text, image_ref=image_ref)
                response = await self.target.send(child)
                child.add(Role.TARGET, response)
                judgment = await self.judges.judge(goal, response, config.break_threshold)
            except Exception as exc:  # noqa: BLE001 — one bad candidate must not kill the run
                await self._emit_error(goal, child.id, f"{type(exc).__name__}: {exc}")
                return None
            child.value = judgment.scores.harm - (
                _REFUSAL_PENALTY if judgment.scores.refused else 0.0
            )
            child.alive = judgment.verdict is not Verdict.BREAK
            await self.sink.emit(
                Event(
                    EventType.TURN,
                    {
                        "goal_id": goal.id,
                        "category": goal.category,
                        "branch_id": child.id,
                        "depth": child.depth,
                        "verdict": judgment.verdict.value,
                        "harm": judgment.scores.harm,
                        "attacker": text,
                        "target": response,
                    },
                )
            )
            return child, judgment

        results = await asyncio.gather(*(evaluate(p) for p in proposals))
        return [r for r in results if r is not None]

    async def _emit_error(self, goal: Goal, branch_id: int, message: str) -> None:
        await self.sink.emit(
            Event(EventType.TURN, {
                "goal_id": goal.id, "category": goal.category, "branch_id": branch_id,
                "depth": 0, "verdict": "error", "harm": 0.0,
                "attacker": "(call failed)", "target": message,
            })
        )

    async def run(
        self, goal: Goal, config: RunConfig, control: RunControl = NULL_CONTROL
    ) -> GoalResult:
        await self.sink.emit(
            Event(
                EventType.GOAL_STARTED,
                {"goal_id": goal.id, "category": goal.category, "objective": goal.objective},
            )
        )
        result = GoalResult(goal=goal)
        frontier = [Branch(goal_id=goal.id)]

        for turn in range(config.max_turns):
            await control.checkpoint()  # honour pause/abort between turns
            result.turns_used = turn + 1
            expansions = await asyncio.gather(
                *(self._expand(goal, b, config) for b in frontier)
            )
            candidates = [pair for group in expansions for pair in group]
            if not candidates:
                break

            for child, judgment in candidates:
                if judgment.scores.harm > result.best_harm:
                    result.best_harm = judgment.scores.harm
                    result.best_branch = child
                if judgment.verdict is Verdict.BREAK:
                    result.broken = True
                    result.breaks.append((child, judgment))
                    await self.sink.emit(
                        Event(
                            EventType.BREAK_FOUND,
                            {
                                "goal_id": goal.id,
                                "category": goal.category,
                                "branch_id": child.id,
                                "harm": judgment.scores.harm,
                            },
                        )
                    )

            if result.broken and config.stop_goal_on_first_break:
                break

            ranked = sorted(candidates, key=lambda p: p[0].value, reverse=True)
            frontier = [child for child, _ in ranked[: config.beam_width]]
            await self.sink.emit(
                Event(
                    EventType.BRANCH_PRUNED,
                    {
                        "goal_id": goal.id,
                        "kept": len(frontier),
                        "dropped": max(0, len(candidates) - len(frontier)),
                    },
                )
            )

        await self.sink.emit(
            Event(
                EventType.GOAL_COMPLETED,
                {"goal_id": goal.id, "broken": result.broken, "best_harm": result.best_harm},
            )
        )
        return result
