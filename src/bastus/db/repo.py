"""Data-access helpers over the ORM."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from bastus.db.models import GoalRow, RunRow, TurnRow
from bastus.db.session import Database
from bastus.models.run import RunConfig


async def create_run(db: Database, config: RunConfig) -> int:
    """Insert a run in REQUESTED state and return its numeric id."""
    async with db.session() as s:
        row = RunRow(label=config.label, state="requested", config=config.parameters_summary())
        s.add(row)
        await s.commit()
        # Now that the numeric id exists, store it inside the config snapshot too.
        config.run_id = row.id
        row.config = config.parameters_summary()
        await s.commit()
        return row.id


async def set_state(db: Database, run_id: int, state: str, error: str = "") -> None:
    async with db.session() as s:
        row = await s.get(RunRow, run_id)
        if row is None:
            return
        row.state = state
        if error:
            row.error = error
        if state in {"report_ready", "aborted", "failed", "destroyed"}:
            row.finished_at = datetime.now(timezone.utc)
        await s.commit()


async def set_totals(db: Database, run_id: int, goals: int, breaks: int) -> None:
    async with db.session() as s:
        row = await s.get(RunRow, run_id)
        if row:
            row.total_goals = goals
            row.total_breaks = breaks
            await s.commit()


async def add_goal(db: Database, run_id: int, goal_key: str, category: str, objective: str,
                   seed_image_ref: str | None) -> None:
    async with db.session() as s:
        s.add(GoalRow(run_id=run_id, goal_key=goal_key, category=category,
                      objective=objective, seed_image_ref=seed_image_ref))
        await s.commit()


async def update_goal(db: Database, run_id: int, goal_key: str, broken: bool, best_harm: float) -> None:
    async with db.session() as s:
        res = await s.execute(
            select(GoalRow).where(GoalRow.run_id == run_id, GoalRow.goal_key == goal_key)
        )
        goal = res.scalar_one_or_none()
        if goal:
            goal.broken = broken
            goal.best_harm = best_harm
            await s.commit()


async def add_turn(db: Database, run_id: int, goal_key: str, branch_id: int, depth: int,
                   attacker_text: str, target_text: str, verdict: str, harm: float,
                   category: str) -> None:
    async with db.session() as s:
        s.add(TurnRow(run_id=run_id, goal_key=goal_key, branch_id=branch_id, depth=depth,
                      attacker_text=attacker_text, target_text=target_text, verdict=verdict,
                      harm=harm, category=category))
        await s.commit()


async def get_run(db: Database, run_id: int) -> RunRow | None:
    async with db.session() as s:
        return await s.get(RunRow, run_id)


async def list_runs(db: Database, limit: int = 50) -> list[RunRow]:
    async with db.session() as s:
        res = await s.execute(select(RunRow).order_by(RunRow.id.desc()).limit(limit))
        return list(res.scalars().all())


async def get_goals(db: Database, run_id: int) -> list[GoalRow]:
    async with db.session() as s:
        res = await s.execute(
            select(GoalRow).where(GoalRow.run_id == run_id).order_by(GoalRow.id)
        )
        return list(res.scalars().all())


async def get_turns(db: Database, run_id: int, limit: int = 2000) -> list[TurnRow]:
    async with db.session() as s:
        res = await s.execute(
            select(TurnRow).where(TurnRow.run_id == run_id).order_by(TurnRow.id).limit(limit)
        )
        return list(res.scalars().all())
