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
