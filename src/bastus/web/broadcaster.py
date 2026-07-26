"""In-memory pub/sub for live run events (control plane, single process).

Phase 2 runs the engine in-process, so an in-memory fan-out is sufficient. In
Phase 3 the remote runner POSTs events back and this same hub relays them.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict


class Broadcaster:
    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, run_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: int, q: asyncio.Queue) -> None:
        self._subs.get(run_id, set()).discard(q)

    async def publish(self, run_id: int, message: dict) -> None:
        for q in list(self._subs.get(run_id, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass  # a slow client must not stall the run
