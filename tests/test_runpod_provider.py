"""RealRunpodProvider tests with a fake RunPod client (no real API, no spend)."""

from __future__ import annotations

import pytest

from bastus.models.server import ServerState
from bastus.runpod.client import RunPodCapacityError
from bastus.runpod.provider import ProvisionConfig, RealRunpodProvider


class FakeClient:
    def __init__(self, unavailable=()) -> None:
        self.unavailable = set(unavailable)
        self.created: list[dict] = []
        self.deleted: list[str] = []

    async def create_pod(self, payload: dict) -> dict:
        gpu = payload["gpuTypeIds"][0]
        if gpu in self.unavailable:
            raise RunPodCapacityError("no instances currently available")
        self.created.append(payload)
        return {"id": "pod123"}

    async def delete_pod(self, pod_id: str) -> None:
        self.deleted.append(pod_id)


async def _always_ready(url: str) -> bool:
    return True


async def _collect(provider):
    return [x async for x in provider.provision()]


async def test_picks_first_available_and_reports_endpoint():
    client = FakeClient()
    prov = RealRunpodProvider(
        client, ProvisionConfig(gpu_ladder=["GPU-A", "GPU-B"]),
        health_check=_always_ready, poll_interval=0,
    )
    events = await _collect(prov)
    assert events[-1][0] is ServerState.READY
    assert client.created[0]["gpuTypeIds"] == ["GPU-A"]
    ready_extra = events[-1][2]
    assert ready_extra["attacker_endpoint"] == "https://pod123-8000.proxy.runpod.net/v1"
    assert ready_extra["console_url"].endswith("pod123")


async def test_ladder_falls_through_unavailable():
    client = FakeClient(unavailable={"GPU-A", "GPU-B"})
    prov = RealRunpodProvider(
        client, ProvisionConfig(gpu_ladder=["GPU-A", "GPU-B", "GPU-C"]),
        health_check=_always_ready, poll_interval=0,
    )
    events = await _collect(prov)
    assert client.created[0]["gpuTypeIds"] == ["GPU-C"]
    assert events[-1][0] is ServerState.READY


async def test_no_capacity_across_ladder_raises():
    client = FakeClient(unavailable={"GPU-A"})
    prov = RealRunpodProvider(
        client, ProvisionConfig(gpu_ladder=["GPU-A"]), health_check=_always_ready, poll_interval=0,
    )
    with pytest.raises(RuntimeError):
        await _collect(prov)
    assert client.created == []


async def test_becomes_ready_after_polling():
    client = FakeClient()
    calls = {"n": 0}

    async def eventually(url: str) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    prov = RealRunpodProvider(
        client, ProvisionConfig(gpu_ladder=["G"]), health_check=eventually, poll_interval=0, max_wait=100,
    )
    events = await _collect(prov)
    assert events[-1][0] is ServerState.READY
    assert any(s is ServerState.LOADING_MODEL for s, _, _ in events)


async def test_timeout_when_never_ready():
    async def never(url: str) -> bool:
        return False

    prov = RealRunpodProvider(
        FakeClient(), ProvisionConfig(gpu_ladder=["G"]), health_check=never, poll_interval=0, max_wait=0.0,
    )
    with pytest.raises(TimeoutError):
        await _collect(prov)


async def test_destroy_deletes_pod():
    client = FakeClient()
    prov = RealRunpodProvider(client, ProvisionConfig(), health_check=_always_ready)
    await prov.destroy("podX")
    assert client.deleted == ["podX"]


def test_pod_payload_shape():
    cfg = ProvisionConfig(model="m/x", quantization="awq", hf_token="tok")
    p = cfg.pod_payload("NVIDIA A100 80GB PCIe")
    assert p["imageName"] == "vllm/vllm-openai:latest"
    assert p["gpuTypeIds"] == ["NVIDIA A100 80GB PCIe"]
    assert "8000/http" in p["ports"]
    assert "--model" in p["dockerStartCmd"] and "m/x" in p["dockerStartCmd"]
    assert "--quantization" in p["dockerStartCmd"] and "awq" in p["dockerStartCmd"]
    assert p["env"]["HF_TOKEN"] == "tok"
