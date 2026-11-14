"""Harmony のデータモデル.

公式APIの実態に合わせた注意点:
- ID は int ではなく UUID 文字列 (例: "3f6c1d2e-...")
- MESSAGE_CREATE イベントには server_id が含まれない。
  そのため Message.server / Context.server は、Bot が事前に
  fetch_server() などで掴んだキャッシュから解決できた場合のみ返る。
  解決できない場合は None になる (推測で埋めることはしない)。
- チャンネルのリネーム/削除、サーバーのリネームは Bot API に
  ルートが存在しない。該当メソッドは NotSupportedError を送出する。
"""

from __future__ import annotations

from .errors import NotSupportedError

_UNSET = object()


class _DeleteAction:
    """`await obj.delete` でも `await obj.delete()` でも動くためのラッパー.

    サンプルコードの `await ctx.delete` (括弧なし) という書き方に合わせている。
    """

    def __init__(self, factory):
        self._factory = factory

    def __call__(self):
        return self._factory()

    def __await__(self):
        return self._factory().__await__()


class User:
    """ユーザー / Bot / メッセージの author."""

    def __init__(self, state, data: dict, *, nickname=_UNSET):
        self._state = state
        self.id: str = str(data.get("id"))
        self.name: str | None = data.get("username")
        self.username = self.name
        self.display_name: str | None = data.get("display_name")
        self.avatar: str | None = data.get("avatar") or data.get("avatar_url")
        self.bot: bool = bool(data.get("bot", False))
        self._nickname = nickname if nickname is not _UNSET else data.get("nickname")

    @property
    def nick(self) -> str | None:
        """サーバー内ニックネーム。無い場合は表示名→ユーザー名の順で代替する."""
        return self._nickname or self.display_name or self.name

    @property
    def mention(self) -> str:
        return f"@{self.name}"

    def __str__(self) -> str:
        return self.name or self.id

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.name!r}>"


class ClientUser(User):
    """ログイン中の Bot 自身 (GET /users/@me + READY から構築)."""

    def __init__(self, state, data: dict):
        super().__init__(state, {**data, "bot": True})
        self.discriminator: str | None = data.get("discriminator")
        self.verified: bool = bool(data.get("verified", False))
        self.public: bool = bool(data.get("public", False))

    @property
    def nick(self) -> str | None:
        # Bot にニックネームの概念が API 上ないため、表示名が無ければ None。
        # サンプルコードの f'{bot.name}({bot.nick})' が落ちないよう属性自体は用意する。
        return self._nickname or self.display_name


class Member(User):
    """サーバーのメンバー (list_members の行から構築)."""

    def __init__(self, state, data: dict, *, server=None):
        user_data = data.get("user") or {}
        super().__init__(state, user_data, nickname=data.get("nick"))
        self.server = server
        self.guild = server
        self.roles: list = data.get("roles") or []
        self.joined_at = data.get("joined_at")


class Role:
    def __init__(self, state, data: dict, *, server=None):
        self._state = state
        self.server = server
        self.id: str = str(data.get("id"))
        self.name: str | None = data.get("name")
        self.color = data.get("color")
        self.position: int = data.get("position", 0)
        self.permissions: str = str(data.get("permissions", "0"))
        self.mentionable: bool = bool(data.get("mentionable", False))
        self.hoist: bool = bool(data.get("hoist", False))
        self.is_default: bool = bool(data.get("is_default", False))
        self.is_admin: bool = bool(data.get("is_admin", False))

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r}>"


class Category:
    def __init__(self, state, data: dict, *, server=None):
        self._state = state
        self.server = server
        self.id: str = str(data.get("id"))
        self.server_id: str | None = data.get("server_id") or (server.id if server else None)
        self.name: str | None = data.get("name")
        self.order: int = data.get("order", 0)

    async def rename(self, name: str):
        """カテゴリのリネームは API で可能 (PATCH categories)."""
        data = await self._state.http.edit_category(
            self.server_id, self.id, {"name": name}
        )
        if isinstance(data, dict):
            self.name = data.get("name", name)
        return self

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r}>"


class Channel:
    """テキスト/ボイスチャンネル.

    REST には単体取得ルート (GET /channels/{id}) が無いため、
    name などが分からない「部分オブジェクト」の場合がある。
    その場合 name は None。send() など ID だけで済む操作はそのまま動く。
    """

    # REST のチャンネルオブジェクトの type 番号 (Discord 互換の番号付け)
    TYPE_TEXT = 0
    TYPE_VOICE = 2
    TYPE_CATEGORY = 4

    def __init__(self, state, data: dict, *, server=None):
        self._state = state
        self.id: str = str(data.get("id"))
        self.name: str | None = data.get("name")
        self.type: int = data.get("type", 0)
        self.server_id: str | None = (
            data.get("guild_id") or data.get("server_id") or (server.id if server else None)
        )
        self.category_id = data.get("category_id") or data.get("parent_id")
        self.position: int = data.get("position", data.get("order", 0))
        self._server = server

    @classmethod
    def partial(cls, state, channel_id, *, server=None):
        return cls(state, {"id": str(channel_id)}, server=server)

    @property
    def server(self):
        if self._server is not None:
            return self._server
        if self.server_id is not None:
            return self._state._get_server(self.server_id)
        return None

    @property
    def guild(self):
        return self.server

    @property
    def mention(self) -> str:
        return f"#{self.name or self.id}"

    def _update(self, data: dict):
        if data.get("name") is not None:
            self.name = data["name"]
        if data.get("type") is not None:
            self.type = data["type"]
        if data.get("guild_id") or data.get("server_id"):
            self.server_id = data.get("guild_id") or data.get("server_id")
        if "category_id" in data or "parent_id" in data:
            self.category_id = data.get("category_id") or data.get("parent_id")
        if data.get("position") is not None or data.get("order") is not None:
            self.position = data.get("position", data.get("order", self.position))
        return self

    async def send(self, content=None, *, reply_to=None, thread_id=None, metadata=None):
        """このチャンネルにメッセージを送る。Message を返す."""
        payload: dict = {}
        if content is not None:
            payload["content"] = content
        if reply_to is not None:
            payload["reply_to"] = str(getattr(reply_to, "id", reply_to))
        if thread_id is not None:
            payload["thread_id"] = str(getattr(thread_id, "id", thread_id))
        if metadata is not None:
            payload["metadata"] = metadata
        data = await self._state.http.create_message(self.id, payload)
        return Message(self._state, data, channel=self)

    async def history(self, *, limit: int = 50, before=None, after=None):
        """新しい順にメッセージを取得する."""
        rows = await self._state.http.get_channel_messages(
            self.id, limit=limit, before=before, after=after
        )
        return [Message(self._state, row, channel=self) for row in (rows or [])]

    async def create_thread(self, name: str, *, message_id=None):
        payload: dict = {"name": name}
        if message_id is not None:
            payload["message_id"] = str(getattr(message_id, "id", message_id))
        data = await self._state.http.create_thread(self.id, payload)
        return Thread(self._state, data, channel=self)

    async def edit(self, *, order=None, category_id=_UNSET):
        """並び順とカテゴリの変更だけが API で可能."""
        payload: dict = {}
        if order is not None:
            payload["order"] = order
        if category_id is not _UNSET:
            payload["category_id"] = (
                None if category_id is None else str(getattr(category_id, "id", category_id))
            )
        if not payload:
            from .errors import InvalidArgument

            raise InvalidArgument("edit() には order か category_id が必要です")
        data = await self._state.http.edit_channel(self.id, payload)
        if isinstance(data, dict):
            self._update(data)
        return self

    async def rename(self, name: str):
        raise NotSupportedError(
            "チャンネルのリネームは Harmony Bot API にルートがありません "
            "(PATCH /channels/{id} は order と category_id のみ対応)"
        )

    async def _delete(self):
        raise NotSupportedError(
            "チャンネルの削除は Harmony Bot API にルートがありません "
            "(DELETE /channels/{id} は存在しません)"
        )

    @property
    def delete(self):
        return _DeleteAction(self._delete)

    def __repr__(self) -> str:
        return f"<Channel id={self.id} name={self.name!r} type={self.type}>"


class TextChannel(Channel):
    pass


class Thread:
    def __init__(self, state, data: dict, *, channel=None):
        self._state = state
        self.id: str = str(data.get("id"))
        self.channel_id: str | None = data.get("channel_id") or (channel.id if channel else None)
        self.channel = channel
        self.name: str | None = data.get("name")
        self.parent_message_id = data.get("parent_message_id")
        self.archived: bool = bool(data.get("archived", False))
        self.locked: bool = bool(data.get("locked", False))
        self.created_at = data.get("created_at")

    async def send(self, content=None, **kwargs):
        if self.channel is None:
            channel = self._state.get_channel(self.channel_id)
        else:
            channel = self.channel
        return await channel.send(content, thread_id=self.id, **kwargs)

    def __repr__(self) -> str:
        return f"<Thread id={self.id} name={self.name!r}>"


class Server:
    """サーバー (discord.py の Guild に相当)."""

    def __init__(self, state, data: dict):
        self._state = state
        self.id: str = str(data.get("id"))
        self.name: str | None = data.get("name")
        self.icon: str | None = data.get("icon")
        self.owner_id = data.get("owner_id")
        self.description = data.get("description")
        self.member_count = data.get("member_count")

    @classmethod
    def partial(cls, state, server_id):
        return cls(state, {"id": str(server_id)})

    def _update(self, data: dict):
        for key in ("name", "icon", "owner_id", "description", "member_count"):
            if data.get(key) is not None:
                setattr(self, key, data[key])
        return self

    async def fetch(self):
        """GET /servers/{id} で最新情報を取り直す."""
        data = await self._state.http.get_server(self.id)
        return self._update(data)

    async def channels(self):
        """サーバーの全チャンネル。取得結果は Bot のキャッシュにも入る."""
        rows = await self._state.http.list_channels(self.id)
        result = []
        for row in rows or []:
            channel = self._state._cache_channel(row, server=self)
            result.append(channel)
        return result

    async def categories(self):
        rows = await self._state.http.list_categories(self.id)
        return [Category(self._state, row, server=self) for row in (rows or [])]

    async def members(self, *, limit: int = 100, after=None):
        rows = await self._state.http.list_members(self.id, limit=limit, after=after)
        return [Member(self._state, row, server=self) for row in (rows or [])]

    async def roles(self):
        rows = await self._state.http.list_roles(self.id)
        return [Role(self._state, row, server=self) for row in (rows or [])]

    async def create_channel(self, name: str, *, voice: bool = False, category_id=None,
                             description=None, order=None):
        payload: dict = {"name": name}
        if voice:
            payload["type"] = 1  # 作成時の指定は 1=ボイス (応答の type は 2 で返る)
        if category_id is not None:
            payload["category_id"] = str(getattr(category_id, "id", category_id))
        if description is not None:
            payload["description"] = description
        if order is not None:
            payload["order"] = order
        data = await self._state.http.create_channel(self.id, payload)
        return self._state._cache_channel(data, server=self)

    async def create_category(self, name: str, *, order: int = 0):
        data = await self._state.http.create_category(self.id, {"name": name, "order": order})
        return Category(self._state, data, server=self)

    async def create_role(self, name: str, **kwargs):
        payload = {"name": name, **kwargs}
        data = await self._state.http.create_role(self.id, payload)
        return Role(self._state, data, server=self)

    async def rename(self, name: str):
        raise NotSupportedError(
            "サーバーのリネームは Harmony Bot API にルートがありません "
            "(PATCH /servers/{id} は存在しません)"
        )

    def __repr__(self) -> str:
        return f"<Server id={self.id} name={self.name!r}>"


# discord.py 互換の別名
Guild = Server


class Emoji:
    def __init__(self, data: dict):
        self.id = data.get("id")
        self.name = data.get("name")
        self.url = data.get("url")
        self.animated: bool = bool(data.get("animated", False))

    def __str__(self) -> str:
        return self.name or ""

    def __repr__(self) -> str:
        return f"<Emoji name={self.name!r} id={self.id}>"


class ReactionEvent:
    """MESSAGE_REACTION_ADD / REMOVE のイベントオブジェクト."""

    def __init__(self, state, data: dict):
        self._state = state
        self.reaction_id = data.get("reaction_id")
        self.message_id = data.get("message_id")
        self.channel_id = data.get("channel_id")
        self.user_id = data.get("user_id")
        self.bot_id = data.get("bot_id")
        emoji = data.get("emoji") or {}
        self.emoji = Emoji(emoji)
        self.metadata = data.get("metadata") or {}

    @property
    def channel(self):
        return self._state.get_channel(self.channel_id) if self.channel_id else None


class PartialMessage:
    """MESSAGE_DELETE のように ID しか分からないメッセージ."""

    def __init__(self, state, data: dict):
        self._state = state
        self.id = data.get("id")
        self.channel_id = data.get("channel_id")
        self.thread_id = data.get("thread_id")
        self.metadata = data.get("metadata")

    @property
    def channel(self):
        return self._state.get_channel(self.channel_id) if self.channel_id else None


class Interaction:
    """スラッシュコマンドの実行 (INTERACTION_CREATE).

    応答は 5 秒以内に respond() か defer() を呼ぶ必要がある。
    flags=64 (ephemeral) の応答は実行したメンバーにだけ見える。
    """

    def __init__(self, state, data: dict):
        self._state = state
        self.id: str = str(data.get("id"))
        self.type: int = data.get("type", 2)
        self.server_id = data.get("server_id")
        self.channel_id = data.get("channel_id")
        self.thread_id = data.get("thread_id")
        member = data.get("member") or {}
        user_data = data.get("user") or {}
        self.user: User | None = (
            User(state, user_data, nickname=member.get("nickname")) if user_data else None
        )
        self.author = self.user
        self.member = member
        self.resolved: dict = {}
        cmd = data.get("data") or {}
        self.command_id = cmd.get("id")
        self.command_name: str | None = cmd.get("name")
        self.subcommand: str | None = None
        self.options: dict = {}
        self._flatten_options(cmd.get("options") or [], cmd.get("resolved") or {})
        self.created_at = data.get("created_at")
        self.respond_by = data.get("respond_by")
        self.expires_at = data.get("expires_at")
        self._responded = False
        self.raw = data

    def _flatten_options(self, options: list, resolved: dict) -> None:
        self.resolved = resolved or {}
        current = options
        # サブコマンド (type 1) / グループ (type 2) を最大2段まで潜る
        for _ in range(2):
            if len(current) == 1 and current[0].get("type") in (1, 2) \
                    and isinstance(current[0].get("options"), list):
                if current[0]["type"] == 1:
                    self.subcommand = current[0].get("name")
                current = current[0]["options"]
            else:
                break
        for opt in current:
            self.options[opt.get("name")] = opt.get("value")

    @property
    def invoked_with(self) -> str | None:
        return self.command_name

    @property
    def channel(self):
        return self._state.get_channel(self.channel_id) if self.channel_id else None

    @property
    def server(self):
        if self.server_id is None:
            return None
        return self._state._get_server(self.server_id) or self._state.get_server(self.server_id)

    @property
    def guild(self):
        return self.server

    async def respond(self, content=None, *, ephemeral: bool = False, embeds=None):
        """即時に応答する (type 4)。5 秒以内・1回だけ."""
        data_payload: dict = {}
        if content is not None:
            data_payload["content"] = content
        if embeds is not None:
            data_payload["embeds"] = embeds
        if ephemeral:
            data_payload["flags"] = 64
        await self._state.http.interaction_callback(
            self.id, {"type": 4, "data": data_payload}
        )
        self._responded = True

    async def defer(self, *, ephemeral: bool = False):
        """応答を保留する (type 5)。15 分以内に edit_response() する."""
        data_payload: dict = {}
        if ephemeral:
            data_payload["flags"] = 64
        await self._state.http.interaction_callback(
            self.id, {"type": 5, "data": data_payload}
        )
        self._responded = True

    async def edit_response(self, content=None, *, embeds=None):
        payload: dict = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        return await self._state.http.interaction_response(self.id, payload)

    async def followup(self, content=None, *, ephemeral: bool = False, embeds=None):
        payload: dict = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        if ephemeral:
            payload["flags"] = 64
        return await self._state.http.interaction_followup(self.id, payload)

    def __repr__(self) -> str:
        return f"<Interaction id={self.id} command={self.command_name!r} options={self.options!r}>"


class Message:
    """メッセージ。Context はこのオブジェクトとしても扱えるよう設計している."""

    def __init__(self, state, data: dict, *, channel: Channel | None = None):
        self._state = state
        self.id: str = str(data.get("id"))
        self.channel_id: str | None = data.get("channel_id") or (channel.id if channel else None)
        if channel is not None:
            self.channel = channel
        elif self.channel_id is not None:
            self.channel = state.get_channel(self.channel_id)
        else:
            self.channel = None
        self.thread_id = data.get("thread_id")
        author = data.get("author")
        self.author: User | None = User(state, author) if author else None
        self.content: str = data.get("content") or ""
        self.content_raw = data.get("content_raw")
        self.reply_to_id = data.get("reply_to")
        self.created_at = data.get("timestamp")
        self.edited_at = data.get("edited_timestamp")
        self.mentions: list = data.get("mentions") or []
        self.mention_everyone: bool = bool(data.get("mention_everyone", False))
        self.is_system: bool = bool(data.get("is_system", False))
        self.metadata: dict = data.get("metadata") or {}

    # サンプルコード互換の別名
    @property
    def data(self) -> str:
        """メッセージの本文 (content と同じ)."""
        return self.content

    @property
    def user(self) -> User | None:
        """author と同じ."""
        return self.author

    @property
    def server(self):
        if self.channel is not None:
            return self.channel.server
        return None

    @property
    def guild(self):
        return self.server

    async def reply(self, content=None, **kwargs):
        """このメッセージへの返信として送信する."""
        if self.channel is None:
            from .errors import InvalidArgument

            raise InvalidArgument("channel が不明なメッセージには返信できません")
        return await self.channel.send(
            content, reply_to=self.id, thread_id=self.thread_id, **kwargs
        )

    async def send(self, content=None, **kwargs):
        """このメッセージがあるチャンネルへ送信する (返信ではない)."""
        if self.channel is None:
            from .errors import InvalidArgument

            raise InvalidArgument("channel が不明なメッセージのチャンネルには送信できません")
        return await self.channel.send(content, thread_id=self.thread_id, **kwargs)

    async def edit(self, content):
        data = await self._state.http.edit_message(self.id, {"content": content})
        if isinstance(data, dict) and data.get("content") is not None:
            self.content = data["content"]
        else:
            self.content = content if isinstance(content, str) else self.content
        return self

    async def _delete(self):
        await self._state.http.delete_message(self.id)

    @property
    def delete(self):
        """`await msg.delete` でも `await msg.delete()` でも削除できる."""
        return _DeleteAction(self._delete)

    async def add_reaction(self, emoji: str):
        await self._state.http.add_reaction(self.id, emoji)

    async def remove_reaction(self, emoji: str):
        await self._state.http.remove_reaction(self.id, emoji)

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"<Message id={self.id} author={self.author!r} content={self.content!r}>"
