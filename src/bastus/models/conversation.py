"""Conversation primitives: messages, and the branch (one conversation path)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import count


class Role(str, Enum):
    SYSTEM = "system"
    ATTACKER = "attacker"  # maps to the target's "user" role
    TARGET = "target"  # maps to the target's "assistant" role


@dataclass
class Message:
    role: Role
    content: str
    # Handle into the seed-image bank for multimodal turns; bytes are attached by
    # the target caller, never stored inline here.
    image_ref: str | None = None


_branch_ids = count(1)


@dataclass
class Branch:
    """One path through the attack tree — a single multi-turn conversation."""

    goal_id: str
    messages: list[Message] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_branch_ids))
    parent_id: int | None = None
    alive: bool = True
    # Running heuristic value used by beam search to rank/prune frontier branches.
    value: float = 0.0
    depth: int = 0

    def child(self) -> Branch:
        return Branch(
            goal_id=self.goal_id,
            messages=list(self.messages),
            parent_id=self.id,
            depth=self.depth + 1,
        )

    def add(self, role: Role, content: str, image_ref: str | None = None) -> None:
        self.messages.append(Message(role=role, content=content, image_ref=image_ref))

    @property
    def last_target_reply(self) -> str | None:
        for msg in reversed(self.messages):
            if msg.role is Role.TARGET:
                return msg.content
        return None
