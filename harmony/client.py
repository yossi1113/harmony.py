"""Gateway (WebSocket) 接続とイベント配送を担う Client.

公式ドキュメント: docs/build/gateway.md / bot-quickstart.md
- Gateway URL: wss://<instance>/bot-gateway/gateway
- 接続直後に op 2 (Identify) を送り、READY で heartbeat_interval を受け取る
- op 1 でハートビート、op 11 は ACK。RESUME は無い (切断時は再接続+再Identify)
- close 4001 / 4004 (Token verification unavailable を除く) は再接続しない
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import websockets

from .errors import LoginFailure
from .http import HTTPClient
from .models import (
    Channel,
    ClientUser,
    Interaction,
    Member,
    Message,
    PartialMessage,
    ReactionEvent,
    Server,
    User,
)

log = logging.getLogger("harmony")

DEFAULT_BASE_URL = "https://har.mony.lol"

# Gateway イベント名 -> ライブラリの on_* 名
_EVENT_ALIASES = {
    "ready": ("READY",),
    "message": ("MESSAGE_CREATE",),
    "message_edit": ("MESSAGE_UPDATE",),
    "message_delete": ("MESSAGE_DELETE",),
    "reaction_add": ("MESSAGE_REACTION_ADD",),
    "reaction_remove": ("MESSAGE_REACTION_REMOVE",),
    "member_join": ("SERVER_MEMBER_ADD",),
    "member_remove": ("SERVER_MEMBER_REMOVE",),
    "interaction": ("INTERACTION_CREATE",),
}


class Client:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        preload_servers: list[str] | None = None,
    ):
        base = (base_url or os.environ.get("HARMONY_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.base_url = base
        ws_base = "wss://" + base.split("://", 1)[-1] if base.startswith("https://") else \
            "ws://" + base.split("://", 1)[-1] if base.startswith("http://") else base
        self.gateway_url = ws_base + "/bot-gateway/gateway"
        self.api_url = base + "/bot-gateway/api/v1"

        self.http = HTTPClient(self.api_url)
        self._token = token
        self._preload_servers = [str(s) for s in (preload_servers or [])]

        self.user: ClientUser | None = None
        self.session_id: str | None = None

        self._channels: dict[str, Channel] = {}
        self._servers: dict[str, Server] = {}
        self._listeners: dict[str, list] = {}

        self._ws = None  # websockets の接続
        self._heartbeat_task: asyncio.Task | None = None
        self._closed = True
        self._ready = asyncio.Event()

    # --- 基本情報 --------------------------------------------------------
    @property
    def name(self) -> str | None:
        """Bot のユーザー名 (サンプルコード互換: bot.name)."""
        return self.user.name if self.user else None

    @property
    def nick(self) -> str | None:
        """Bot のニックネーム (API 上 Bot に nick は無いので通常 None)."""
        return self.user.nick if self.user else None

    def is_ready(self) -> bool:
        return self._ready.is_set()

    async def wait_until_ready(self) -> None:
        await self._ready.wait()

    # --- イベント登録 ------------------------------------------------------
    def event(self, func):
        """@bot.event: on_<名前> という関数をイベントハンドラとして登録する.

        同じ名前の登録は前のものを置き換える (discord.py と同じ)。
        """
        name = func.__name__
        if not name.startswith("on_"):
            raise TypeError("event ハンドラは on_ で始まる名前にしてください (例: on_ready)")
        self._listeners[name[3:]] = [func]
        return func

    def add_listener(self, func, name: str | None = None):
        event_name = name or func.__name__.removeprefix("on_")
        self._listeners.setdefault(event_name, []).append(func)
        return func

    def dispatch(self, event_name: str, *args) -> None:
        handlers = list(self._listeners.get(event_name, ()))
        for raw, gateway_names in _EVENT_ALIASES.items():
            if event_name in gateway_names:
                handlers += self._listeners.get(raw, ())
        for handler in handlers:
            asyncio.ensure_future(self._run_handler(event_name, handler, *args))

    async def _run_handler(self, event_name: str, handler, *args) -> None:
        try:
            await handler(*args)
        except Exception as exc:  # noqa: BLE001 - on_error へ回すのが discord.py 流
            await self._run_on_error(event_name, exc, *args)

    async def _run_on_error(self, event_name: str, exc: Exception, *args) -> None:
        handlers = self._listeners.get("error", ())
        if not handlers:
            log.exception("イベント %s の処理中に例外が発生しました", event_name, exc_info=exc)
            return
        for handler in handlers:
            try:
                await handler(event_name, exc, *args)
            except Exception:  # noqa: BLE001
                log.exception("on_error ハンドラ自体が例外を出しました")

    # --- キャッシュ / 取得 -------------------------------------------------
    def _get_server(self, server_id) -> Server | None:
        return self._servers.get(str(server_id))

    def _cache_server(self, data: dict) -> Server:
        server_id = str(data.get("id"))
        server = self._servers.get(server_id)
        if server is None:
            server = Server(self, data)
            self._servers[server_id] = server
        else:
            server._update(data)
        return server

    def _cache_channel(self, data: dict, *, server=None) -> Channel:
        channel_id = str(data.get("id"))
        channel = self._channels.get(channel_id)
        if channel is None:
            channel = Channel(self, data, server=server)
            self._channels[channel_id] = channel
        else:
            channel._update(data)
            if server is not None:
                channel._server = server
                channel.server_id = server.id
        return channel

    def get_channel(self, channel_id) -> Channel:
        """チャンネルを返す。キャッシュに無い場合は ID だけの部分オブジェクト.

        REST には GET /channels/{id} が無いため、name が必要な場合は
        先に fetch_server() でサーバーのチャンネル一覧を取り込んでおくこと。
        部分オブジェクトでも send() はそのまま動く。
        """
        channel_id = str(channel_id)
        channel = self._channels.get(channel_id)
        if channel is not None:
            return channel
        channel = Channel.partial(self, channel_id)
        self._channels[channel_id] = channel
        return channel

    def get_server(self, server_id) -> Server:
        """サーバーを返す。キャッシュに無い場合は ID だけの部分オブジェクト."""
        server_id = str(server_id)
        server = self._servers.get(server_id)
        if server is not None:
            return server
        server = Server.partial(self, server_id)
        self._servers[server_id] = server
        return server

    # discord.py 互換の別名
    get_guild = get_server

    async def fetch_server(self, server_id, *, with_channels: bool = True) -> Server:
        """GET /servers/{id}。ついでにチャンネル一覧も取り込んでキャッシュする.

        MESSAGE_CREATE には server_id が含まれないため、ctx.server や
        ctx.channel.name を解決するには、この事前取り込みが実質必須になる。
        """
        data = await self.http.get_server(str(server_id))
        server = self._cache_server(data)
        if with_channels:
            await server.channels()
        return server

    fetch_guild = fetch_server

    async def fetch_user(self, user_id) -> User:
        data = await self.http.get_user(str(user_id))
        return User(self, data)

    # --- 起動 / 停止 -------------------------------------------------------
    def run(self, token: str | None = None, *, reconnect: bool = True) -> None:
        """ブロッキングで起動する。最後に呼ぶこと."""
        token = token or self._token or os.environ.get("HARMONY_BOT_TOKEN")
        if not token:
            raise LoginFailure(
                "トークンがありません。bot.run(token) か環境変数 HARMONY_BOT_TOKEN を指定してください"
            )
        try:
            asyncio.run(self.start(token, reconnect=reconnect))
        except KeyboardInterrupt:
            pass

    async def start(self, token: str | None = None, *, reconnect: bool = True) -> None:
        token = token or self._token or os.environ.get("HARMONY_BOT_TOKEN")
        if not token:
            raise LoginFailure("トークンがありません")
        self._token = token
        self._closed = False
        await self.http.login(token)
        try:
            me = await self.http.get_me()
            self.user = ClientUser(self, me)
            await self._on_before_gateway()
            for server_id in self._preload_servers:
                try:
                    await self.fetch_server(server_id)
                except Exception:  # noqa: BLE001
                    log.exception("preload_servers: サーバー %s の取得に失敗しました", server_id)
            await self._gateway_loop(reconnect=reconnect)
        finally:
            await self.close()

    async def close(self) -> None:
        self._closed = True
        self._ready.clear()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ws = None
        await self.http.close()

    # --- Gateway -----------------------------------------------------------
    async def _gateway_loop(self, *, reconnect: bool) -> None:
        attempt = 0
        while not self._closed:
            try:
                await self._connect_once()
                attempt = 0
            except LoginFailure:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Gateway 接続で例外が発生しました")
            if self._closed or not reconnect:
                break
            delay = min(60.0, 1.0 * (2 ** attempt))
            attempt += 1
            log.info("Gateway: %.0f 秒後に再接続します", delay)
            await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        # Gateway の WebSocket は websockets ライブラリで張る。
        # aiohttp の ws_connect はプロキシ経由だと 101 応答の検証で失敗する
        # ケースがあったため (実サーバー + Cloudflare + CONNECT プロキシで確認)。
        # websockets は環境変数プロキシも標準で解釈する。
        code = None
        reason = ""
        try:
            async with websockets.connect(self.gateway_url) as ws:
                self._ws = ws
                await ws.send(json.dumps({"op": 2, "d": {"token": self._token}}))
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "replace")
                        try:
                            payload = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        await self._handle_payload(payload)
                except websockets.ConnectionClosed as exc:
                    code, reason = exc.code, exc.reason or ""
                if code is None:
                    code, reason = ws.close_code, ws.close_reason or ""
        finally:
            self._ws = None
        if code == 4001 or (code == 4004 and reason != "Token verification unavailable"):
            raise LoginFailure(f"Gateway に接続を拒否されました: {code} {reason}".strip())
        log.info("Gateway が閉じました: %s %s", code, reason)

    async def _heartbeat_loop(self, interval_ms: int) -> None:
        interval = max(interval_ms, 1000) / 1000.0
        try:
            while not self._closed and self._ws is not None:
                await asyncio.sleep(interval)
                if self._ws is not None:
                    await self._ws.send(json.dumps({"op": 1}))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # 接続が閉じていれば次の再接続に任せる
            return

    async def _handle_payload(self, payload: dict) -> None:
        op = payload.get("op")
        if op == 11:  # Heartbeat ACK
            return
        if op != 0:
            return
        event = payload.get("t")
        data = payload.get("d") or {}

        if event == "READY":
            bot_data = data.get("bot") or {}
            if self.user is None:
                self.user = ClientUser(self, bot_data | {"username": bot_data.get("username")})
            else:
                if bot_data.get("id"):
                    self.user.id = str(bot_data["id"])
                if bot_data.get("username"):
                    self.user.name = bot_data["username"]
                    self.user.username = bot_data["username"]
            self.session_id = data.get("session_id")
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.ensure_future(
                self._heartbeat_loop(int(data.get("heartbeat_interval") or 30000))
            )
            self._ready.set()
            self.dispatch("ready")
            return

        if event == "MESSAGE_CREATE":
            message = Message(self, data)
            self.dispatch("message", message)
            await self._after_message_create(message)
            return

        if event == "MESSAGE_UPDATE":
            message = Message(self, data)
            self.dispatch("message_edit", message)
            return

        if event == "MESSAGE_DELETE":
            self.dispatch("message_delete", PartialMessage(self, data))
            return

        if event in ("MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE"):
            name = "reaction_add" if event.endswith("_ADD") else "reaction_remove"
            self.dispatch(name, ReactionEvent(self, data))
            return

        if event in ("SERVER_MEMBER_ADD", "SERVER_MEMBER_REMOVE"):
            user_data = data.get("user") or {}
            member = Member(
                self,
                {"user": user_data, "nick": None},
                server=self._servers.get(str(data.get("server_id"))),
            )
            name = "member_join" if event == "SERVER_MEMBER_ADD" else "member_remove"
            self.dispatch(name, member)
            return

        if event == "INTERACTION_CREATE":
            interaction = Interaction(self, data)
            self.dispatch("interaction", interaction)
            await self._after_interaction(interaction)
            return

        if event:
            self.dispatch(event.lower(), data)

    async def _after_message_create(self, message: Message) -> None:
        """commands.Bot がコマンド処理を差し込むためのフック."""

    async def _after_interaction(self, interaction: Interaction) -> None:
        """commands.Bot がスラッシュコマンド処理を差し込むためのフック."""

    async def _on_before_gateway(self) -> None:
        """start() 中、Gateway 接続の直前に呼ばれるフック (スラッシュコマンド登録用)."""
