"""Thin async client for the RunPod REST API (rest.runpod.io/v1).

Only the calls the provisioner needs: create pod, get pod, delete pod. Capacity /
availability failures are raised as RunPodCapacityError so the ladder can fall through
to the next GPU; anything else is a hard RunPodError.
"""

from __future__ import annotations

import httpx

BASE_URL = "https://rest.runpod.io/v1"

# Substrings that indicate "this GPU isn't available right now" (fall through) rather
# than a malformed request (hard fail).
_CAPACITY_HINTS = ("no instances", "not available", "unavailable", "capacity", "no gpu", "out of stock")


class RunPodError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RunPodCapacityError(RunPodError):
    """Requested GPU type has no available capacity."""


class RunPodClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 60.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def create_pod(self, payload: dict) -> dict:
        resp = await self._client.post("/pods", json=payload)
        if resp.status_code // 100 == 2:
            return resp.json()
        body = resp.text
        if resp.status_code in (400, 409, 422, 500) and any(h in body.lower() for h in _CAPACITY_HINTS):
            raise RunPodCapacityError(body, resp.status_code)
        raise RunPodError(f"create_pod failed ({resp.status_code}): {body}", resp.status_code)

    async def list_pods(self) -> list[dict]:
        resp = await self._client.get("/pods")
        if resp.status_code // 100 != 2:
            raise RunPodError(f"list_pods failed ({resp.status_code}): {resp.text}", resp.status_code)
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])

    async def get_pod(self, pod_id: str) -> dict:
        resp = await self._client.get(f"/pods/{pod_id}")
        if resp.status_code // 100 != 2:
            raise RunPodError(f"get_pod failed ({resp.status_code}): {resp.text}", resp.status_code)
        return resp.json()

    async def delete_pod(self, pod_id: str) -> None:
        resp = await self._client.delete(f"/pods/{pod_id}")
        if resp.status_code // 100 != 2 and resp.status_code != 404:
            raise RunPodError(f"delete_pod failed ({resp.status_code}): {resp.text}", resp.status_code)

    async def aclose(self) -> None:
        await self._client.aclose()
