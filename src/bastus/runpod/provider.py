"""RealRunpodProvider — deterministic GPU-ladder provisioning of the attacker pod.

Flow: walk the GPU preference ladder, creating a pod on the first type with capacity;
poll the vLLM OpenAI endpoint (via RunPod's HTTP proxy) until it serves; report READY
with the attacker endpoint. No LLM in the loop — availability is handled by trying the
next rung, which is bounded, testable, and cheap to reason about.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import httpx

from bastus.models.server import ServerState
from bastus.runpod.client import RunPodCapacityError, RunPodClient

DEFAULT_MODEL = "huihui-ai/Qwen3-32B-abliterated"

# Preference order. 80GB tier first because a BF16 32B needs it on a single card.
# Override with BASTUS_GPU_LADDER (comma-separated) — e.g. a 48GB tier for a 4-bit quant.
DEFAULT_LADDER = [
    "NVIDIA A100 80GB PCIe",
    "NVIDIA A100-SXM4-80GB",
    "NVIDIA H100 PCIe",
    "NVIDIA H100 80GB HBM3",
]


@dataclass
class ProvisionConfig:
    model: str = DEFAULT_MODEL
    gpu_ladder: list[str] = field(default_factory=lambda: list(DEFAULT_LADDER))
    image: str = "vllm/vllm-openai:latest"
    quantization: str | None = None  # e.g. "awq" / "gptq" for a quantized checkpoint
    port: int = 8000
    container_disk_gb: int = 120  # BF16 32B weights are ~66GB; leave headroom
    max_model_len: int = 8192
    gpu_mem_util: float = 0.92
    network_volume_id: str | None = None  # optional weight-cache volume (pins datacenter)
    hf_token: str | None = None

    @classmethod
    def from_env(cls) -> ProvisionConfig:
        ladder_env = os.getenv("BASTUS_GPU_LADDER")
        return cls(
            model=os.getenv("BASTUS_ATTACKER_MODEL", DEFAULT_MODEL),
            gpu_ladder=[g.strip() for g in ladder_env.split(",")] if ladder_env else list(DEFAULT_LADDER),
            image=os.getenv("BASTUS_VLLM_IMAGE", "vllm/vllm-openai:latest"),
            quantization=os.getenv("BASTUS_QUANTIZATION") or None,
            container_disk_gb=int(os.getenv("BASTUS_CONTAINER_DISK_GB", "120")),
            max_model_len=int(os.getenv("BASTUS_MAX_MODEL_LEN", "8192")),
            gpu_mem_util=float(os.getenv("BASTUS_GPU_MEM_UTIL", "0.92")),
            network_volume_id=os.getenv("BASTUS_NETWORK_VOLUME_ID") or None,
            hf_token=os.getenv("HF_TOKEN") or None,
        )

    def docker_args(self) -> list[str]:
        args = [
            "--model", self.model,
            "--host", "0.0.0.0",
            "--port", str(self.port),
            "--max-model-len", str(self.max_model_len),
            "--gpu-memory-utilization", str(self.gpu_mem_util),
        ]
        if self.quantization:
            args += ["--quantization", self.quantization]
        return args

    def pod_payload(self, gpu_type_id: str) -> dict:
        payload = {
            "name": "bastus-attacker",
            "imageName": self.image,
            "gpuTypeIds": [gpu_type_id],
            "gpuCount": 1,
            "containerDiskInGb": self.container_disk_gb,
            "ports": [f"{self.port}/http"],
            "dockerStartCmd": self.docker_args(),
            "cloudType": "SECURE",
        }
        if self.hf_token:
            payload["env"] = {"HF_TOKEN": self.hf_token, "HUGGING_FACE_HUB_TOKEN": self.hf_token}
        if self.network_volume_id:
            payload["networkVolumeId"] = self.network_volume_id
            payload["volumeMountPath"] = "/root/.cache/huggingface"
        return payload


def proxy_url(pod_id: str, port: int) -> str:
    """RunPod exposes HTTP ports at https://{podId}-{port}.proxy.runpod.net."""
    return f"https://{pod_id}-{port}.proxy.runpod.net"


async def _default_health_check(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(f"{base_url}/v1/models")
            return r.status_code == 200
    except Exception:
        return False


class RealRunpodProvider:
    def __init__(
        self,
        client: RunPodClient,
        config: ProvisionConfig | None = None,
        *,
        health_check: Callable[[str], "asyncio.Future[bool]"] | None = None,
        poll_interval: float = 12.0,
        max_wait: float = 1500.0,  # 25 min: image pull + weight download + load
    ) -> None:
        self.client = client
        self.config = config or ProvisionConfig.from_env()
        self.health_check = health_check or _default_health_check
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    async def provision(self) -> AsyncIterator[tuple[ServerState, str, dict]]:
        cfg = self.config
        yield ServerState.PROVISIONING, f"Selecting GPU (ladder of {len(cfg.gpu_ladder)})…", {"model": cfg.model}

        pod = None
        chosen = None
        for gpu in cfg.gpu_ladder:
            yield ServerState.PROVISIONING, f"Requesting {gpu}…", {}
            try:
                pod = await self.client.create_pod(cfg.pod_payload(gpu))
                chosen = gpu
                break
            except RunPodCapacityError:
                yield ServerState.PROVISIONING, f"{gpu} has no capacity — trying next rung…", {}
                continue

        if pod is None:
            raise RuntimeError(f"No capacity across GPU ladder: {', '.join(cfg.gpu_ladder)}")

        pod_id = pod["id"]
        console = f"https://www.runpod.io/console/pods/{pod_id}"
        base = proxy_url(pod_id, cfg.port)
        yield ServerState.PULLING_IMAGE, f"Pod {pod_id} created on {chosen}. Pulling image…", {
            "pod_id": pod_id, "gpu": chosen, "console_url": console,
        }
        yield ServerState.DOWNLOADING_WEIGHTS, f"Downloading {cfg.model} & starting vLLM…", {}

        waited = 0.0
        while waited < self.max_wait:
            if await self.health_check(base):
                yield ServerState.READY, "vLLM serving — pod ready.", {
                    "attacker_endpoint": f"{base}/v1", "console_url": console,
                }
                return
            await asyncio.sleep(self.poll_interval)
            waited += self.poll_interval
            yield ServerState.LOADING_MODEL, f"Loading model… ({int(waited)}s elapsed)", {}

        raise TimeoutError(f"vLLM did not become ready within {int(self.max_wait)}s (pod {pod_id})")

    async def destroy(self, pod_id: str | None) -> None:
        if pod_id:
            await self.client.delete_pod(pod_id)
