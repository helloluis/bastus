"""OpenAI-compatible /chat/completions client (vLLM, OpenAI, most gateways).

Used for the real attacker (RunPod vLLM), target, and judge endpoints. Multimodal
turns attach image bytes as data URLs when a resolver is provided.
"""

from __future__ import annotations

import asyncio
import base64
import random
from collections.abc import Callable

import httpx

from bastus.providers.base import ProviderMessage

# Resolver maps a seed-image handle -> (mime_type, raw_bytes).
ImageResolver = Callable[[str], tuple[str, bytes]]

# Transient statuses worth retrying against commercial endpoints.
_RETRYABLE = {429, 500, 502, 503, 504}


class OpenAICompatProvider:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "EMPTY",
        *,
        image_resolver: ImageResolver | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        base_delay: float = 1.0,
        force_temperature: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.image_resolver = image_resolver
        self.max_retries = max_retries
        self.base_delay = base_delay
        # Some endpoints pin temperature (e.g. Kimi Code's k3 requires 1); when set,
        # this overrides whatever the caller requests.
        self.force_temperature = force_temperature
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

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
            "temperature": self.force_temperature if self.force_temperature is not None else temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.endpoint}/chat/completions"
        for attempt in range(self.max_retries + 1):
            resp = await self._client.post(url, json=payload, headers=headers)
            if resp.status_code < 400:
                return resp.json()["choices"][0]["message"]["content"]
            if resp.status_code in _RETRYABLE and attempt < self.max_retries:
                await asyncio.sleep(self._backoff(resp, attempt))
                continue
            resp.raise_for_status()
        resp.raise_for_status()  # exhausted retries
        raise RuntimeError("unreachable")

    def _backoff(self, resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after", "")
        if retry_after.replace(".", "", 1).isdigit():
            return min(float(retry_after), 30.0)
        return min(self.base_delay * (2**attempt), 30.0) + random.uniform(0, 0.3 * self.base_delay)

    async def aclose(self) -> None:
        await self._client.aclose()
