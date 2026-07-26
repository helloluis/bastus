"""Pause/abort control tests at the engine level (deterministic, no HTTP race)."""

from __future__ import annotations

import asyncio

import pytest

from bastus.engine.control import RunAborted, RunControl
from bastus.engine.runner import Runner
from bastus.models.run import RunConfig


def _config(**kw) -> RunConfig:
    base = dict(
        run_id=1,
        enabled_categories=["S6", "S9"],
        num_tests=4,
        beam_width=2,
        branching_factor=2,
        max_turns=6,
        mock=True,
    )
    base.update(kw)
    return RunConfig(**base)


async def test_abort_before_run_raises():
    control = RunControl()
    control.abort()
    with pytest.raises(RunAborted):
        await Runner().run(_config(), control)


async def test_pause_blocks_then_resume_completes():
    control = RunControl()
    control.pause()
    task = asyncio.create_task(Runner().run(_config(), control))
    await asyncio.sleep(0.15)
    assert not task.done()  # blocked at the first turn checkpoint

    control.resume()
    report = await asyncio.wait_for(task, timeout=5)
    assert report.total_goals == 8  # 4 tests/category × 2 categories


async def test_abort_midrun_stops_task():
    control = RunControl()
    control.pause()  # hold at first checkpoint so we can abort deterministically
    task = asyncio.create_task(Runner().run(_config(num_tests=8, max_turns=10), control))
    await asyncio.sleep(0.1)
    control.abort()
    with pytest.raises(RunAborted):
        await asyncio.wait_for(task, timeout=5)
