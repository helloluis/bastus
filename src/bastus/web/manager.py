"""Run manager: creates runs, executes them as background tasks, and holds the
RunControl for pause/abort. Numeric run ids come from the DB at creation time.
"""

from __future__ import annotations

import asyncio

from bastus.config import load_settings
from bastus.db import repo
from bastus.db.session import Database
from bastus.engine.control import RunAborted, RunControl
from bastus.engine.runner import Runner
from bastus.models.run import RunConfig
from bastus.web.broadcaster import Broadcaster
from bastus.web.provision import ATTACKER_MODEL, ServerManager
from bastus.web.sink import PersistSink


def invalid_run_reason(ok_turns: int, error_turns: int) -> str | None:
    """A run whose model calls all errored isn't a valid test — don't let it look
    like a clean '0 breaks' result."""
    if ok_turns == 0 and error_turns > 0:
        return (
            f"Invalid run: all {error_turns} model calls errored "
            "(check the target/judge API credits or rate limits)."
        )
    return None


class RunManager:
    def __init__(self, db: Database, broadcaster: Broadcaster, server_mgr: ServerManager | None = None) -> None:
        self.db = db
        self.broadcaster = broadcaster
        self.server_mgr = server_mgr
        self.controls: dict[int, RunControl] = {}
        self.tasks: dict[int, asyncio.Task] = {}

    @property
    def has_active_runs(self) -> bool:
        return any(not t.done() for t in self.tasks.values())

    async def start(self, config: RunConfig) -> int:
        run_id = await repo.create_run(self.db, config)
        config.run_id = run_id
        control = RunControl()
        self.controls[run_id] = control
        self.tasks[run_id] = asyncio.create_task(self._execute(run_id, config, control))
        return run_id

    async def _set_state(self, run_id: int, state: str, error: str = "") -> None:
        await repo.set_state(self.db, run_id, state, error)
        await self.broadcaster.publish(
            run_id, {"type": "run_state", "data": {"run_id": run_id, "state": state, "error": error}}
        )

    async def _execute(self, run_id: int, config: RunConfig, control: RunControl) -> None:
        sink = PersistSink(self.db, run_id, self.broadcaster)
        settings = load_settings()
        # For live runs, point the attacker at the provisioned pod's endpoint and hold
        # the idle watchdog off while the run is in flight.
        is_live = bool(
            not config.mock and self.server_mgr and self.server_mgr.status.attacker_endpoint
        )
        if is_live:
            settings.attacker_endpoint = self.server_mgr.status.attacker_endpoint
            # Use the model the pod is actually serving (may be an AWQ repo id).
            settings.attacker_model = self.server_mgr.status.model or ATTACKER_MODEL
            settings.attacker_api_key = "EMPTY"
            self.server_mgr.run_started()
        try:
            await self._set_state(run_id, "running")
            report = await Runner(sink=sink, settings=settings).run(config, control)
            await repo.set_totals(self.db, run_id, report.total_goals, report.total_breaks)
            turns = await repo.get_turns(self.db, run_id)
            ok = sum(1 for t in turns if t.verdict != "error")
            errs = sum(1 for t in turns if t.verdict == "error")
            reason = invalid_run_reason(ok, errs)
            if reason:
                await self._set_state(run_id, "failed", error=reason)
            else:
                await self._set_state(run_id, "report_ready")
        except RunAborted:
            await self._set_state(run_id, "aborted")
        except Exception as exc:  # noqa: BLE001 — surface any engine failure to the run row
            await self._set_state(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            if is_live:
                # Completed / aborted / failed → restart the idle countdown from now.
                self.server_mgr.run_finished()
            self.controls.pop(run_id, None)
            self.tasks.pop(run_id, None)

    def _control(self, run_id: int) -> RunControl | None:
        return self.controls.get(run_id)

    async def pause(self, run_id: int) -> bool:
        c = self._control(run_id)
        if not c:
            return False
        c.pause()
        await self._set_state(run_id, "paused")
        return True

    async def resume(self, run_id: int) -> bool:
        c = self._control(run_id)
        if not c:
            return False
        c.resume()
        await self._set_state(run_id, "running")
        return True

    def abort(self, run_id: int) -> bool:
        c = self._control(run_id)
        if not c:
            return False
        c.abort()
        return True
