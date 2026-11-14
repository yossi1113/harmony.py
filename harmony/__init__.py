"""harmony.py — Harmony (har.mony.lol) 用の discord.py 風 Bot ライブラリ.

非公式ライブラリ。Harmony 本体の Bot API (Gateway + REST) を使っている。
公式ドキュメント: https://github.com/y4my4my4m/harmony/tree/master/docs/build
"""

from __future__ import annotations

from . import commands  # noqa: F401  (harmony.commands.Bot を使えるように)
from .client import Client, DEFAULT_BASE_URL  # noqa: F401
from .commands import (  # noqa: F401  (例外は harmony 直下からも使えるように)
    BadArgument,
    CommandError,
    CommandInvokeError,
    CommandNotFound,
    MissingRequiredArgument,
)
from .errors import (  # noqa: F401
    Forbidden,
    HarmonyError,
    HTTPError,
    InvalidArgument,
    LoginFailure,
    NotFound,
    NotSupportedError,
    RateLimited,
)
from .models import (  # noqa: F401
    Category,
    Channel,
    ClientUser,
    Emoji,
    Guild,
    Interaction,
    Member,
    Message,
    PartialMessage,
    ReactionEvent,
    Role,
    Server,
    TextChannel,
    Thread,
    User,
)

__version__ = "0.4.0"
__all__ = [
    "Client",
    "commands",
    "Category",
    "Channel",
    "ClientUser",
    "Emoji",
    "Guild",
    "Interaction",
    "Member",
    "Message",
    "PartialMessage",
    "ReactionEvent",
    "Role",
    "Server",
    "TextChannel",
    "Thread",
    "User",
    "HarmonyError",
    "HTTPError",
    "LoginFailure",
    "Forbidden",
    "NotFound",
    "RateLimited",
    "NotSupportedError",
    "InvalidArgument",
    "CommandError",
    "CommandNotFound",
    "MissingRequiredArgument",
    "BadArgument",
    "CommandInvokeError",
    "DEFAULT_BASE_URL",
]

_default_bot: Client | None = None


def _set_default_bot(bot: Client) -> None:
    global _default_bot
    _default_bot = bot


def get_channel(channel_id):
    """直近に作られた Bot の get_channel() を呼ぶ簡易関数.

    サンプルコードの `get_channel(chid)` という書き方のためのもの。
    通常は bot.get_channel(...) を使う方が分かりやすい。
    """
    if _default_bot is None:
        raise RuntimeError("Bot がまだ作られていません。先に commands.Bot(...) を生成してください")
    return _default_bot.get_channel(channel_id)


def get_server(server_id):
    """直近に作られた Bot の get_server() を呼ぶ簡易関数."""
    if _default_bot is None:
        raise RuntimeError("Bot がまだ作られていません。先に commands.Bot(...) を生成してください")
    return _default_bot.get_server(server_id)


# Bot 生成時にデフォルトとして登録する (get_channel / get_server 用)
_orig_client_init = Client.__init__


def _client_init(self, *args, **kwargs):
    _orig_client_init(self, *args, **kwargs)
    _set_default_bot(self)


Client.__init__ = _client_init
