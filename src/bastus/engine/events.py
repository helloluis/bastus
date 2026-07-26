"""Streaming events. The runner emits these; sinks persist and/or display them.

In Phase 2 a WebSocket sink relays these to the browser and to Postgres; in Phase 1
we use a console sink and a list-collecting sink.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    GOAL_STARTED = "goal_started"
    TURN = "turn"  # one attacker->target exchange, with judgment
    BRANCH_PRUNED = "branch_pruned"
    BREAK_FOUND = "break_found"
    GOAL_COMPLETED = "goal_completed"
    RUN_COMPLETED = "run_completed"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


class EventSink(Protocol):
    async def emit(self, event: Event) -> None: ...


class ListSink:
    """Collects events in memory (tests, and aggregation)."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class ConsoleSink:
    """Human-readable console stream for the CLI."""

    def __init__(self, console: Any = None) -> None:
        from rich.console import Console

        self.console = console or Console()

    async def emit(self, event: Event) -> None:
        d = event.data
        c = self.console
        if event.type is EventType.RUN_STARTED:
            c.print(f"[bold]▶ run {d['run_id']}[/] — {d['num_goals']} goals, beam={d['beam_width']}")
        elif event.type is EventType.GOAL_STARTED:
            c.print(f"\n[cyan]● goal {d['goal_id']} [{d['category']}][/] {d['objective']}")
        elif event.type is EventType.TURN:
            verdict = d["verdict"]
            color = {"break": "bold red", "partial": "yellow", "refused": "dim", "benign": "dim"}.get(
                verdict, "white"
            )
            c.print(
                f"  [{color}]b{d['branch_id']} t{d['depth']} {verdict:<7}[/] "
                f"harm={d['harm']:5.1f}  atk: {d['attacker'][:60]}"
            )
        elif event.type is EventType.BREAK_FOUND:
            c.print(f"  [bold red]✗ BREAK[/] goal {d['goal_id']} [{d['category']}] harm={d['harm']:.1f}")
        elif event.type is EventType.GOAL_COMPLETED:
            status = "BROKEN" if d["broken"] else "held"
            c.print(f"  → goal {d['goal_id']}: [{'red' if d['broken'] else 'green'}]{status}[/]")
        elif event.type is EventType.RUN_COMPLETED:
            c.print(f"\n[bold]■ run {d['run_id']} complete[/] — {d['breaks']}/{d['goals']} goals broken")
