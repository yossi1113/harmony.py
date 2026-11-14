"""Harmony Bot REST API への薄い非同期クライアント.

公式ドキュメント: docs/build/rest.md (y4my4my4m/harmony)
- Base URL: https://<instance>/bot-gateway/api/v1
- 認証: Authorization: Bot <token>
- ID はすべて UUID 文字列
"""

from __future__ import annotations

import asyncio
import urllib.parse

import aiohttp

from .errors import Forbidden, HTTPError, LoginFailure, NotFound, RateLimited

_UNSET = object()


class HTTPClient:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None

    async def login(self, token: str) -> None:
        self._token = token
        if self._session is None or self._session.closed:
            # trust_env=True: HTTPS_PROXY などの環境変数プロキシを尊重する
            self._session = aiohttp.ClientSession(trust_env=True)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def request(self, method: str, path: str, **kwargs):
        """path は api_url からの相対パス (例: '/users/@me')."""
        if self._session is None:
            raise RuntimeError("HTTPClient.login() が呼ばれていません")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bot {self._token}"
        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")
        url = self.api_url + path

        for attempt in range(4):
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 204:
                    return None
                try:
                    data = await resp.json()
                except Exception:
                    data = None
                if 200 <= resp.status < 300:
                    return data
                message = ""
                retry_after = 1.0
                if isinstance(data, dict):
                    message = str(data.get("error") or "")
                    try:
                        retry_after = float(data.get("retry_after") or retry_after)
                    except (TypeError, ValueError):
                        pass
                if resp.status == 429 and attempt < 3:
                    await asyncio.sleep(min(retry_after, 60.0))
                    continue
                if resp.status == 401:
                    raise LoginFailure(message or "Invalid or expired token")
                if resp.status == 403:
                    raise Forbidden(resp.status, message, payload=data)
                if resp.status == 404:
                    raise NotFound(resp.status, message, payload=data)
                if resp.status == 429:
                    raise RateLimited(resp.status, message, payload=data, retry_after=retry_after)
                raise HTTPError(resp.status, message, payload=data)
        raise HTTPError(429, "Rate limit exceeded")  # pragma: no cover

    # --- users ---------------------------------------------------------
    async def get_me(self):
        return await self.request("GET", "/users/@me")

    async def get_user(self, user_id: str):
        return await self.request("GET", f"/users/{user_id}")

    # --- messages ------------------------------------------------------
    async def create_message(self, channel_id: str, payload: dict):
        return await self.request("POST", f"/channels/{channel_id}/messages", json=payload)

    async def get_channel_messages(self, channel_id: str, *, limit=50, before=None, after=None):
        params = {"limit": limit}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        return await self.request("GET", f"/channels/{channel_id}/messages", params=params)

    async def get_message(self, message_id: str):
        return await self.request("GET", f"/messages/{message_id}")

    async def edit_message(self, message_id: str, payload: dict):
        return await self.request("PATCH", f"/messages/{message_id}", json=payload)

    async def delete_message(self, message_id: str):
        return await self.request("DELETE", f"/messages/{message_id}")

    async def add_reaction(self, message_id: str, emoji: str):
        quoted = urllib.parse.quote(str(emoji), safe="")
        return await self.request("PUT", f"/messages/{message_id}/reactions/{quoted}")

    async def remove_reaction(self, message_id: str, emoji: str):
        quoted = urllib.parse.quote(str(emoji), safe="")
        return await self.request("DELETE", f"/messages/{message_id}/reactions/{quoted}")

    async def trigger_typing(self, channel_id: str):
        return await self.request("POST", f"/channels/{channel_id}/typing")

    # --- threads -------------------------------------------------------
    async def create_thread(self, channel_id: str, payload: dict):
        return await self.request("POST", f"/channels/{channel_id}/threads", json=payload)

    async def get_thread(self, thread_id: str):
        return await self.request("GET", f"/threads/{thread_id}")

    # --- servers / channels / categories / roles -----------------------
    async def get_server(self, server_id: str):
        return await self.request("GET", f"/servers/{server_id}")

    async def list_members(self, server_id: str, *, limit=100, after=None):
        params = {"limit": limit}
        if after is not None:
            params["after"] = after
        return await self.request("GET", f"/servers/{server_id}/members", params=params)

    async def list_channels(self, server_id: str):
        return await self.request("GET", f"/servers/{server_id}/channels")

    async def create_channel(self, server_id: str, payload: dict):
        return await self.request("POST", f"/servers/{server_id}/channels", json=payload)

    async def edit_channel(self, channel_id: str, payload: dict):
        return await self.request("PATCH", f"/channels/{channel_id}", json=payload)

    async def list_categories(self, server_id: str):
        return await self.request("GET", f"/servers/{server_id}/categories")

    async def create_category(self, server_id: str, payload: dict):
        return await self.request("POST", f"/servers/{server_id}/categories", json=payload)

    async def edit_category(self, server_id: str, category_id: str, payload: dict):
        return await self.request(
            "PATCH", f"/servers/{server_id}/categories/{category_id}", json=payload
        )

    async def list_roles(self, server_id: str):
        return await self.request("GET", f"/servers/{server_id}/roles")

    async def create_role(self, server_id: str, payload: dict):
        return await self.request("POST", f"/servers/{server_id}/roles", json=payload)

    async def edit_role(self, server_id: str, role_id: str, payload: dict):
        return await self.request("PATCH", f"/servers/{server_id}/roles/{role_id}", json=payload)

    async def delete_role(self, server_id: str, role_id: str):
        return await self.request("DELETE", f"/servers/{server_id}/roles/{role_id}")

    async def get_invite_preview(self, code: str):
        return await self.request("GET", f"/invites/{code}/preview")

    # --- slash commands / interactions ----------------------------------
    async def list_commands(self):
        return await self.request("GET", "/commands")

    async def replace_commands(self, commands: list):
        return await self.request("PUT", "/commands", json=commands)

    async def upsert_command(self, command: dict):
        return await self.request("POST", "/commands", json=command)

    async def delete_command(self, command_id: str):
        return await self.request("DELETE", f"/commands/{command_id}")

    async def interaction_callback(self, interaction_id: str, payload: dict):
        return await self.request(
            "POST", f"/interactions/{interaction_id}/callback", json=payload
        )

    async def interaction_response(self, interaction_id: str, payload: dict):
        return await self.request(
            "PATCH", f"/interactions/{interaction_id}/response", json=payload
        )

    async def interaction_followup(self, interaction_id: str, payload: dict):
        return await self.request(
            "POST", f"/interactions/{interaction_id}/followups", json=payload
        )
