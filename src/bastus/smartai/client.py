"""HTTP client for the Smart AI api-test endpoints.

Two-stage auth: a web form login (session cookie, because the whole api-test path
sits behind the site login) plus an api-test key (msisdn + OTP). One send-message
call runs a full turn; memory is server-side, keyed by chat_id.
"""

from __future__ import annotations

import asyncio

import httpx


class SmartAIError(Exception):
    pass


class SmartAIClient:
    def __init__(
        self,
        base: str,
        login_url: str,
        web_user: str,
        web_pass: str,
        msisdn: str,
        otp: str = "123456",
        timeout: float = 300.0,
    ) -> None:
        self.base = base.rstrip("/")
        self.login_url = login_url
        self.web_user = web_user
        self.web_pass = web_pass
        self.msisdn = msisdn
        self.otp = otp
        self.api_key: str | None = None
        # follow_redirects so the web-login 302 is chased; the cookie jar persists.
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self._lock = asyncio.Lock()

    async def _authenticate(self) -> None:
        # 1) Web login → session cookie
        await self._client.post(
            self.login_url,
            data={"username": self.web_user, "password": self.web_pass, "next": "/base-smart/api-test/"},
        )
        # 2) api-test key (msisdn plan sim + OTP)
        r = await self._client.post(
            f"{self.base}/login/",
            json={"msisdn": self.msisdn, "otp": self.otp, "label": "bastus"},
        )
        try:
            data = r.json()
        except Exception as exc:
            raise SmartAIError(f"api login returned non-JSON ({r.status_code})") from exc
        key = data.get("api_key")
        if not key:
            raise SmartAIError(f"api login failed: {data.get('error') or r.text[:160]}")
        self.api_key = key

    async def ensure_auth(self) -> None:
        if self.api_key:
            return
        async with self._lock:
            if not self.api_key:
                await self._authenticate()

    async def send(self, message: str, chat_id: str | None = None, _retry: bool = True) -> dict:
        """Run one turn. Returns the parsed response dict; raises on API error."""
        await self.ensure_auth()
        body: dict = {"message": message}
        if chat_id:
            body["chat_id"] = chat_id
        r = await self._client.post(
            f"{self.base}/send-message/",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            data = r.json()
        except Exception:
            # Non-JSON usually means the session lapsed and we got the login page.
            if _retry:
                self.api_key = None
                await self.ensure_auth()
                return await self.send(message, chat_id, _retry=False)
            raise SmartAIError(f"send-message returned non-JSON ({r.status_code})")
        if not data.get("success", True) and data.get("error"):
            code = data["error"].get("code", "error")
            if code in ("invalid_api_key", "missing_api_key") and _retry:
                self.api_key = None
                await self.ensure_auth()
                return await self.send(message, chat_id, _retry=False)
            raise SmartAIError(f"{code}: {data['error'].get('message', '')}")
        return data

    async def aclose(self) -> None:
        await self._client.aclose()
