"""Event sink that persists to Postgres and fans out to WebSocket subscribers.

Implements the same EventSink protocol the CLI's ConsoleSink uses, so the engine
is unchanged — it just emits events; this decides where they go.
"""

from __future__ import annotations

import asyncio

from bastus.db import repo
from bastus.db.session import Database
from bastus.engine.events import Event, EventType
from bastus.web.broadcaster import Broadcaster


class PersistSink:
    def __init__(self, db: Database, run_id: int, broadcaster: Broadcaster) -> None:
        self.db = db
        self.run_id = run_id
        self.broadcaster = broadcaster
        # Serialize writes: SQLite dislikes concurrent writers, and it keeps
        # persisted order aligned with broadcast order.
        self._lock = asyncio.Lock()

    async def emit(self, event: Event) -> None:
        d = event.data
        async with self._lock:
            if event.type is EventType.GOAL_STARTED:
                await repo.add_goal(
                    self.db, self.run_id, d["goal_id"], d["category"], d["objective"],
                    d.get("seed_image_ref"),
                )
            elif event.type is EventType.TURN:
                await repo.add_turn(
                    self.db, self.run_id, d["goal_id"], d["branch_id"], d["depth"],
                    d["attacker"], d["target"], d["verdict"], d["harm"], d["category"],
                )
            elif event.type is EventType.GOAL_COMPLETED:
                await repo.update_goal(
                    self.db, self.run_id, d["goal_id"], d["broken"], d.get("best_harm", 0.0)
                )
            await self.broadcaster.publish(
                self.run_id, {"type": event.type.value, "data": d}
            )
