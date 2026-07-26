"""Cooperative pause/abort control for a running red-team run.

The engine checks a RunControl at turn boundaries. The web layer holds the control
for each in-flight run and flips it from the abort/pause endpoints.
"""

from __future__ import annotations

import asyncio


class RunAborted(Exception):
    """Raised inside the engine when a run has been aborted."""


class RunControl:
    def __init__(self) -> None:
        self._resume = asyncio.Event()
        self._resume.set()  # not paused
        self.aborted = False

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def abort(self) -> None:
        self.aborted = True
        self._resume.set()  # wake any paused waiters so they can observe the abort

    async def checkpoint(self) -> None:
        """Block while paused; raise if aborted. Call at turn boundaries."""
        if self.aborted:
            raise RunAborted
        await self._resume.wait()
        if self.aborted:
            raise RunAborted


# A control that is never paused or aborted — default for CLI/offline runs.
NULL_CONTROL = RunControl()
