"""Target callers: send a branch's conversation to the target model+harness.

A target returns a TargetResult so it can surface its own guardrail decision
(`blocked` + `governance`) when it has one — the judge uses that as a first-class
refusal signal, rather than always inferring refusal from text.
"""

from __future__ import annotations

from dataclasses import dataclass

from bastus.models.conversation import Branch, Role
from bastus.providers.base import ChatProvider, ProviderMessage


@dataclass
class TargetResult:
    text: str
    blocked: bool | None = None  # None = target has no explicit guardrail signal
    governance: dict | None = None


class TargetCaller:
    """OpenAI-compatible target: sends the full conversation each turn."""

    def __init__(self, provider: ChatProvider) -> None:
        self.provider = provider

    async def send(self, branch: Branch) -> TargetResult:
        msgs: list[ProviderMessage] = []
        for m in branch.messages:
            if m.role is Role.ATTACKER:
                msgs.append(ProviderMessage("user", m.content, image_ref=m.image_ref))
            elif m.role is Role.TARGET:
                msgs.append(ProviderMessage("assistant", m.content))
        text = await self.provider.complete(msgs, temperature=0.7, max_tokens=1024)
        return TargetResult(text=text)
