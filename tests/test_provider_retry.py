"""OpenAICompatProvider retry/backoff against transient statuses."""

from __future__ import annotations

import httpx
import pytest

from bastus.providers.base import ProviderMessage
from bastus.providers.openai_compat import OpenAICompatProvider


def _provider(handler):
    return OpenAICompatProvider(
        "http://x/v1", "m", "k", transport=httpx.MockTransport(handler), base_delay=0.0
    )


async def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"e": "rate"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    p = _provider(handler)
    out = await p.complete([ProviderMessage("user", "hi")])
    assert out == "hi"
    assert calls["n"] == 2
    await p.aclose()


async def test_raises_after_exhausting_retries():
    p = _provider(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await p.complete([ProviderMessage("user", "hi")])
    await p.aclose()


async def test_force_temperature_overrides_requested():
    import json

    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    p = OpenAICompatProvider(
        "http://x/v1", "m", "k", transport=httpx.MockTransport(handler), force_temperature=1.0
    )
    await p.complete([ProviderMessage("user", "hi")], temperature=0.0)  # requests 0.0
    assert seen["temperature"] == 1.0  # but forced to 1.0
    await p.aclose()


async def test_drops_temperature_when_model_rejects_it():
    import json

    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "temperature is deprecated for this model"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    p = OpenAICompatProvider("http://x/v1", "m", "k", transport=httpx.MockTransport(handler), base_delay=0.0)
    out = await p.complete([ProviderMessage("user", "hi")], temperature=0.7)
    assert out == "ok"
    assert len(seen) == 2 and "temperature" in seen[0] and "temperature" not in seen[1]
    await p.aclose()


async def test_non_retryable_4xx_raises_immediately():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"e": "auth"})

    p = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await p.complete([ProviderMessage("user", "hi")])
    assert calls["n"] == 1  # no retries on auth failure
    await p.aclose()
