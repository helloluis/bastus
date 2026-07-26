"""RunPod attacker-pod lifecycle + streaming, for the control plane.

Provision ONE attacker pod, run many red-team runs against it, then destroy it.
Provisioning streams state updates over a WebSocket, like runs do.

Providers:
- SimulatedRunpodProvider (default): walks the state machine with no GPU spend.
- RealRunpodProvider (bastus.runpod): deterministic GPU-ladder provisioning via the
  RunPod API. Enabled with BASTUS_RUNPOD_REAL=1 and a RUNPOD_API_KEY.

An idle watchdog destroys a real pod after BASTUS_POD_IDLE_TTL_MIN minutes with no run
activity — the guard against a forgotten pod billing indefinitely.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from bastus.models.server import ServerState
from bastus.web.broadcaster import Broadcaster

# Broadcaster channel for server (pod) events. Run ids are >= 1, so 0 is reserved.
SERVER_CHANNEL = 0

ATTACKER_MODEL = "huihui-ai/Qwen3-32B-abliterated"
DEFAULT_GPU = "RTX A6000 (48 GB)"

# States from which a fresh provision may start.
_STARTABLE = {ServerState.NOT_PROVISIONED, ServerState.ERROR}


@dataclass
class ServerStatus:
    state: ServerState = ServerState.NOT_PROVISIONED
    message: str = ""
    console_url: str | None = None
    pod_id: str | None = None
    gpu: str | None = None
    model: str | None = None
    attacker_endpoint: str | None = None  # OpenAI-compatible /v1 URL for live runs
    log: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "message": self.message,
            "console_url": self.console_url,
            "pod_id": self.pod_id,
            "gpu": self.gpu,
            "model": self.model,
            "attacker_endpoint": self.attacker_endpoint,
            "log": self.log[-50:],
        }


class SimulatedRunpodProvider:
    """Emits the provisioning state machine with realistic messages and pacing."""

    def __init__(self, step_delay: float | None = None) -> None:
        self.step_delay = (
            step_delay if step_delay is not None else float(os.getenv("BASTUS_SIM_STEP_DELAY", "1.3"))
        )

    async def _pause(self) -> None:
        if self.step_delay:
            await asyncio.sleep(self.step_delay)

    async def provision(self) -> AsyncIterator[tuple[ServerState, str, dict]]:
        pod_id = "sim-" + secrets.token_hex(4)
        yield ServerState.PROVISIONING, f"Requesting GPU pod ({DEFAULT_GPU})…", {"gpu": DEFAULT_GPU, "model": ATTACKER_MODEL}
        await self._pause()
        yield ServerState.PULLING_IMAGE, "Pulling vLLM serving image…", {}
        await self._pause()
        yield ServerState.DOWNLOADING_WEIGHTS, f"Downloading {ATTACKER_MODEL}…", {}
        await self._pause()
        yield ServerState.DOWNLOADING_WEIGHTS, "Weights cached on network volume (17.0 GB).", {}
        await self._pause()
        yield ServerState.LOADING_MODEL, "Loading model into GPU memory…", {}
        await self._pause()
        yield (
            ServerState.READY,
            "vLLM serving on :8000 — pod ready.",
            {
                "pod_id": pod_id,
                "console_url": f"https://www.runpod.io/console/pods/{pod_id}",
                "attacker_endpoint": f"https://{pod_id}-8000.proxy.runpod.net/v1",
            },
        )

    async def destroy(self, pod_id: str | None) -> None:
        await self._pause()


def make_provider():
    """Real RunPod provider when opted in; simulated otherwise."""
    if os.getenv("BASTUS_RUNPOD_REAL") == "1" and os.getenv("RUNPOD_API_KEY"):
        from bastus.runpod import ProvisionConfig, RealRunpodProvider, RunPodClient

        client = RunPodClient(os.environ["RUNPOD_API_KEY"])
        return RealRunpodProvider(client, ProvisionConfig.from_env())
    return SimulatedRunpodProvider()


class ServerManager:
    def __init__(self, broadcaster: Broadcaster, provider=None) -> None:
        self.broadcaster = broadcaster
        self.provider = provider or make_provider()
        self.status = ServerStatus()
        self.idle_ttl_min = float(os.getenv("BASTUS_POD_IDLE_TTL_MIN", "30"))
        self._task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._last_activity: float = 0.0
        self._active_runs: int = 0  # in-flight live runs; pod is never "idle" while > 0
        # Only real (billing) pods need the idle teardown watchdog.
        self._watchdog_enabled = type(self.provider).__name__ == "RealRunpodProvider"

    async def _publish(self) -> None:
        await self.broadcaster.publish(SERVER_CHANNEL, {"type": "server_state", "data": self.status.as_dict()})

    async def reconcile(self) -> None:
        """On startup, re-attach to an existing healthy pod so a restart doesn't orphan it."""
        if not hasattr(self.provider, "reconcile"):
            return
        try:
            info = await self.provider.reconcile()
        except Exception as exc:  # noqa: BLE001
            self.status.log.append(f"[reconcile] error: {exc}")
            return
        if info:
            self.status = ServerStatus(
                state=ServerState.READY,
                message="Re-attached to existing pod after restart.",
                pod_id=info["pod_id"],
                attacker_endpoint=info["attacker_endpoint"],
                console_url=info["console_url"],
                model=info.get("model"),
                gpu=info.get("gpu"),
            )
            self.status.log.append("[ready] Re-attached to existing pod after restart.")
            self.mark_activity()
            self._start_watchdog()
            await self._publish()

    def mark_activity(self) -> None:
        try:
            self._last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            pass

    def run_started(self) -> None:
        """A live run began — pod counts as active until it finishes."""
        self._active_runs += 1

    def run_finished(self) -> None:
        """A live run completed/aborted/failed — (re)start the idle countdown from now."""
        self._active_runs = max(0, self._active_runs - 1)
        self.mark_activity()

    def _should_idle_destroy(self, now: float) -> bool:
        """Idle = Ready, nothing in flight, and > TTL since the last activity."""
        return (
            self.status.state is ServerState.READY
            and self._active_runs == 0
            and (now - self._last_activity) >= self.idle_ttl_min * 60
        )

    async def provision(self) -> bool:
        if self.status.state not in _STARTABLE:
            return False
        self.status = ServerStatus(state=ServerState.PROVISIONING, message="Starting…", model=ATTACKER_MODEL)
        self.mark_activity()
        self._task = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        try:
            async for state, message, extra in self.provider.provision():
                self.status.state = state
                self.status.message = message
                for key in ("console_url", "pod_id", "gpu", "model", "attacker_endpoint"):
                    if extra.get(key):
                        setattr(self.status, key, extra[key])
                self.status.log.append(f"[{state.value}] {message}")
                await self._publish()
            if self.status.state is ServerState.READY:
                self.mark_activity()
                self._start_watchdog()
        except Exception as exc:  # noqa: BLE001 — surface provisioning failure to the UI
            self.status.state = ServerState.ERROR
            self.status.message = f"{type(exc).__name__}: {exc}"
            self.status.log.append(f"[error] {self.status.message}")
            await self._publish()

    def _start_watchdog(self) -> None:
        if self._watchdog_enabled and self.idle_ttl_min > 0 and (self._watchdog is None or self._watchdog.done()):
            self._watchdog = asyncio.create_task(self._idle_watchdog())

    async def _idle_watchdog(self) -> None:
        while self.status.state is ServerState.READY:
            await asyncio.sleep(60)
            if self.status.state is not ServerState.READY:
                break
            if self._should_idle_destroy(asyncio.get_running_loop().time()):
                self.status.log.append(
                    f"[idle] No runs for {self.idle_ttl_min:.0f} min — auto-destroying pod."
                )
                await self.destroy()
                break

    async def destroy(self) -> bool:
        if self.status.state is ServerState.NOT_PROVISIONED:
            return False
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        pod_id = self.status.pod_id
        self.status.state = ServerState.DESTROYING
        self.status.message = "Tearing down pod…"
        await self._publish()
        try:
            await self.provider.destroy(pod_id)
        finally:
            self.status = ServerStatus(message="Pod destroyed.")
            self.status.log.append("[not_provisioned] Pod destroyed.")
            await self._publish()
        return True

    @property
    def is_ready(self) -> bool:
        return self.status.state is ServerState.READY
