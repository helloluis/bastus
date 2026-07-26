"""Target caller: sends a branch's conversation to the target model+harness."""

from __future__ import annotations

from bastus.models.conversation import Branch, Role
from bastus.providers.base import ChatProvider, ProviderMessage


class TargetCaller:
    def __init__(self, provider: ChatProvider) -> None:
        self.provider = provider

    async def send(self, branch: Branch) -> str:
        msgs: list[ProviderMessage] = []
        for m in branch.messages:
            if m.role is Role.ATTACKER:
                msgs.append(ProviderMessage("user", m.content, image_ref=m.image_ref))
            elif m.role is Role.TARGET:
                msgs.append(ProviderMessage("assistant", m.content))
        return await self.provider.complete(msgs, temperature=0.7, max_tokens=1024)
