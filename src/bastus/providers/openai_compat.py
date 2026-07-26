"""OpenAI-compatible /chat/completions client (vLLM, OpenAI, most gateways).

Used for the real attacker (RunPod vLLM), target, and judge endpoints. Multimodal
turns attach image bytes as data URLs when a resolver is provided.
"""

from __future__ import annotations

import base64
from collections.abc import Callable

import httpx

from bastus.providers.base import ProviderMessage

# Resolver maps a seed-image handle -> (mime_type, raw_bytes).
ImageResolver = Callable[[str], tuple[str, bytes]]


class OpenAICompatProvider:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "EMPTY",
        *,
        image_resolver: ImageResolver | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.image_resolver = image_resolver
        self._client = httpx.AsyncClient(timeout=timeout)

    def _render(self, msg: ProviderMessage) -> dict:
        if msg.image_ref and self.image_resolver is not None:
            mime, raw = self.image_resolver(msg.image_ref)
            b64 = base64.b64encode(raw).decode("ascii")
            return {
                "role": msg.role,
                "content": [
                    {"type": "text", "text": msg.content},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        return {"role": msg.role, "content": msg.content}

    async def complete(
        self,
        messages: list[ProviderMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [self._render(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = await self._client.post(
            f"{self.endpoint}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def aclose(self) -> None:
        await self._client.aclose()
