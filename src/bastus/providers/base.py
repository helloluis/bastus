"""Provider protocol: anything that can take a chat history and return a completion.

Attacker, target, and judge are all just ChatProviders, which is what makes the
attacker endpoint pluggable (RunPod vLLM vs. cloud OpenAI-compatible vs. mock).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ProviderMessage:
    """A provider-neutral chat message. `image_ref` is a handle into the seed bank."""

    role: str  # "system" | "user" | "assistant"
    content: str
    image_ref: str | None = None


@runtime_checkable
class ChatProvider(Protocol):
    async def complete(
        self,
        messages: list[ProviderMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Return the assistant completion for the given chat history."""
        ...
