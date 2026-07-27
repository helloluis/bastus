"""SmartAITarget — plugs the Smart AI api-test API into the engine as a target.

Sends only the latest attacker turn plus the branch's chat_id (the server keeps
memory), and surfaces the API's own `blocked`/`governance` as the guardrail signal.
Requires linear conversations (branching_factor=1) — see runner.
"""

from __future__ import annotations

from bastus.engine.target import TargetResult
from bastus.models.conversation import Branch, Role
from bastus.smartai.client import SmartAIClient


class SmartAITarget:
    def __init__(self, client: SmartAIClient) -> None:
        self.client = client

    async def send(self, branch: Branch) -> TargetResult:
        message = next(
            (m.content for m in reversed(branch.messages) if m.role is Role.ATTACKER), ""
        )
        data = await self.client.send(message, chat_id=branch.chat_id)
        if data.get("chat_id"):
            branch.chat_id = data["chat_id"]  # capture/continue the server-side conversation
        response = data.get("response") or {}
        return TargetResult(
            text=response.get("text") or "",
            blocked=bool(data.get("blocked")),
            governance=data.get("governance"),
        )
