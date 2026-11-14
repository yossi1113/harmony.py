"""discord.py の commands 拡張に寄せたプレフィックスコマンド機能.

使い方:
    import harmony
    from harmony import commands

    bot = commands.Bot(command_prefix="!")

    @bot.event
    async def on_ready():
        print(bot.name)

    @bot.command()
    async def hello(ctx):
        await ctx.reply("こんにちは！")

    bot.run("harmony_bot_...")

discord.py との違い (意図的なもの):
- on_message を自前で定義しても、コマンド処理はその後に続けて行われる
  (process_commands を自分で呼ぶ必要はない)。
- 自分自身 (Bot 本人) のメッセージではコマンド処理をしない
  (自分の返信に反応して無限ループになるのを防ぐため。公式クイック
  スタートでも同じガードが推奨されている)。
"""

from __future__ import annotations

import inspect
import logging
import shlex

from .client import Client
from .errors import HarmonyError
from .models import Message

log = logging.getLogger("harmony.commands")


class CommandError(HarmonyError):
    pass


class CommandNotFound(CommandError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"コマンドが見つかりません: {name}")


class MissingRequiredArgument(CommandError):
    def __init__(self, param: str):
        self.param = param
        super().__init__(f"必須の引数がありません: {param}")


class BadArgument(CommandError):
    pass


class CommandInvokeError(CommandError):
    def __init__(self, original: Exception):
        self.original = original
        super().__init__(f"コマンドの実行中に例外が発生しました: {original!r}")


_TRUE_WORDS = {"true", "yes", "on", "1"}
_FALSE_WORDS = {"false", "no", "off", "0"}


def _convert(value: str, annotation, param_name: str):
    if annotation is inspect.Parameter.empty or annotation is str:
        return value
    if annotation is bool:
        lowered = value.lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise BadArgument(f"{param_name}: 真偽値に変換できません: {value!r}")
    if annotation in (int, float):
        try:
            return annotation(value)
        except ValueError:
            raise BadArgument(f"{param_name}: {annotation.__name__} に変換できません: {value!r}") from None
    try:
        return annotation(value)
    except Exception:
        return value


class Command:
    def __init__(self, callback, *, name: str | None = None, aliases=()):
        self.callback = callback
        self.name = name or callback.__name__
        self.aliases = tuple(aliases)
        self.help = inspect.getdoc(callback)
        params = list(inspect.signature(callback).parameters.values())
        if not params:
            raise TypeError("コマンド関数には少なくとも ctx が必要です")
        self.params = params[1:]  # 先頭は ctx

    async def invoke(self, ctx: "Context", args_str: str) -> None:
        args, kwargs = self._parse(args_str)
        try:
            await self.callback(ctx, *args, **kwargs)
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CommandInvokeError(exc) from exc

    def _parse(self, args_str: str):
        try:
            tokens = shlex.split(args_str)
        except ValueError:
            tokens = args_str.split()
        token_iter = iter(tokens)
        positional_values: list[str] = []
        named_values: dict[str, str] = {}
        # key=value 形式は名前付き引数として拾い、それ以外は前から順に割り当てる
        param_names = {p.name for p in self.params}
        for token in tokens:
            if "=" in token:
                key, _, value = token.partition("=")
                if key in param_names:
                    named_values[key] = value
                    continue
            positional_values.append(token)
        del token_iter

        args: list = []
        kwargs: dict = {}
        pos_index = 0
        for param in self.params:
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                rest = positional_values[pos_index:]
                pos_index = len(positional_values)
                args.extend(rest)
                continue
            raw = None
            if param.name in named_values:
                raw = named_values.pop(param.name)
            elif pos_index < len(positional_values):
                raw = positional_values[pos_index]
                pos_index += 1
            if raw is None:
                if param.default is not inspect.Parameter.empty:
                    value = param.default
                else:
                    raise MissingRequiredArgument(param.name)
            else:
                value = _convert(raw, param.annotation, param.name)
            if param.kind is inspect.Parameter.KEYWORD_ONLY:
                kwargs[param.name] = value
            else:
                args.append(value)
        return args, kwargs

    def __repr__(self) -> str:
        return f"<Command name={self.name!r}>"


class Context:
    """コマンド実行時のコンテキスト。メッセージオブジェクトとしても扱える."""

    def __init__(self, bot: "Bot", message: Message, *, prefix: str, command: Command | None,
                 invoked_with: str, args_str: str):
        self.bot = bot
        self.client = bot
        self.message = message
        self.prefix = prefix
        self.command = command
        self.invoked_with = invoked_with
        self.args_str = args_str
        # サンプルコードで使われていた属性
        self.channel = message.channel
        self.author = message.author
        self.user = message.author
        self.data: str = message.content
        self.id: str = message.id

    @property
    def server(self):
        return self.message.server

    @property
    def guild(self):
        return self.message.server

    @property
    def me(self):
        return self.bot.user

    async def send(self, content=None, **kwargs):
        """コマンドが実行されたチャンネルに送信する."""
        return await self.message.send(content, **kwargs)

    async def reply(self, content=None, **kwargs):
        """コマンドのメッセージへ返信する."""
        return await self.message.reply(content, **kwargs)

    @property
    def delete(self):
        """コマンドのメッセージを削除する (`await ctx.delete` / `await ctx.delete()`)."""
        return self.message.delete

    def __repr__(self) -> str:
        return f"<Context command={self.invoked_with!r} message={self.message.id}>"


def _option(type_: int, name: str, description: str, *, required: bool = False, **extra):
    opt = {"type": type_, "name": name, "description": description, "required": required}
    opt.update(extra)
    return opt


def string_option(name: str, description: str, *, required: bool = False, **extra):
    """type 3: 文字列オプション."""
    return _option(3, name, description, required=required, **extra)


def integer_option(name: str, description: str, *, required: bool = False, **extra):
    """type 4: 整数オプション."""
    return _option(4, name, description, required=required, **extra)


def boolean_option(name: str, description: str, *, required: bool = False, **extra):
    """type 5: 真偽値オプション."""
    return _option(5, name, description, required=required, **extra)


def user_option(name: str, description: str, *, required: bool = False, **extra):
    """type 6: ユーザーオプション (値は profile UUID)."""
    return _option(6, name, description, required=required, **extra)


def channel_option(name: str, description: str, *, required: bool = False, **extra):
    """type 7: チャンネルオプション (値は channel UUID)."""
    return _option(7, name, description, required=required, **extra)


def role_option(name: str, description: str, *, required: bool = False, **extra):
    """type 8: ロールオプション (値は role UUID)."""
    return _option(8, name, description, required=required, **extra)


def number_option(name: str, description: str, *, required: bool = False, **extra):
    """type 10: 数値オプション."""
    return _option(10, name, description, required=required, **extra)


class Bot(Client):
    def __init__(self, command_prefix="!", *, case_insensitive: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.command_prefix = command_prefix
        self.case_insensitive = case_insensitive
        self._commands: dict[str, Command] = {}
        self._message_commands: dict[str, Command] = {}
        self._slash_commands: dict[str, tuple] = {}  # name -> (callback, definition)

    # --- コマンド登録 ------------------------------------------------------
    def command(self, *, name: str | None = None, aliases=()):
        def decorator(func):
            cmd = Command(func, name=name, aliases=aliases)
            self.add_command(cmd)
            return cmd

        return decorator

    # サンプルコードにあったタイプミスへの互換エイリアス
    commant = command

    def add_command(self, cmd: Command) -> Command:
        for key in (cmd.name, *cmd.aliases):
            self._commands[self._key(key)] = cmd
        return cmd

    def remove_command(self, name: str) -> Command | None:
        return self._commands.pop(self._key(name), None)

    def get_command(self, name: str) -> Command | None:
        return self._commands.get(self._key(name))

    @property
    def commands(self) -> dict[str, Command]:
        return dict(self._commands)

    # --- メッセージコマンド登録 (prefix なし) --------------------------------
    def message(self, mode: str = "is", *, name: str | None = None, aliases=()):
        """@bot.message(): 本文との照合で発火するコマンドを登録する.

        @bot.command() と違い command_prefix は要らない。照合モードは
        第1引数に文字列で指定する (Python では `is` と裸では書けないため
        クォートして渡す):

        - "is"    : 本文全体が関数名と完全一致したら発火 (デフォルト)
        - "start" : 本文が関数名で始まっていたら発火。残りが引数になる
        - "end"   : 本文が関数名で終わっていたら発火
        - "in"    : 本文に関数名が含まれていたら発火 (非推奨: 会話の
                    途中に単語が出ただけでも反応してしまうため)

        引数が使えるのは "start" のみで、"is" / "end" / "in" では
        引数は渡らない。

        start / end では prefix が付いていても無視して照合するが、
        is は完全一致のため「!てすと」では発火しない。
        @bot.command() のコマンドとして実行されたメッセージでは、
        こちらは実行されない (競合したら bot.command を優先する)。
        ctx はメッセージオブジェクトとして扱える:

            @bot.message("is")
            async def てすと(ctx):
                await ctx.reply("てすと！")

            @bot.message("start")
            async def めも(ctx, text=None):
                ...
        """
        if mode not in ("is", "start", "end", "in"):
            raise ValueError(
                f"message の照合モードは 'is' / 'start' / 'end' / 'in' のいずれかです: {mode!r}")

        def decorator(func):
            cmd = Command(func, name=name, aliases=aliases)
            cmd.trigger_mode = mode
            self.add_message_command(cmd)
            return cmd

        return decorator

    def add_message_command(self, cmd: Command) -> Command:
        for key in (cmd.name, *cmd.aliases):
            self._message_commands[self._key(key)] = cmd
        return cmd

    def remove_message_command(self, name: str) -> Command | None:
        return self._message_commands.pop(self._key(name), None)

    def get_message_command(self, name: str) -> Command | None:
        return self._message_commands.get(self._key(name))

    @property
    def message_commands(self) -> dict[str, Command]:
        return dict(self._message_commands)

    def _key(self, name: str) -> str:
        return name.lower() if self.case_insensitive else name

    # --- コマンド処理 --------------------------------------------------------
    def _resolve_prefix(self, message: Message) -> str | None:
        prefix = self.command_prefix
        if callable(prefix):
            prefix = prefix(self, message)
        if isinstance(prefix, (list, tuple)):
            for candidate in prefix:
                if message.content.startswith(candidate):
                    return candidate
            return None
        if message.content.startswith(prefix):
            return prefix
        return None

    async def _after_message_create(self, message: Message) -> None:
        # bot.command と bot.message が競合したら bot.command を優先する
        invoked = await self.process_commands(message)
        if not invoked:
            await self.process_message_commands(message)

    async def process_message_commands(self, message: Message) -> None:
        """@bot.message() で登録された、prefix なしコマンドの処理."""
        if self.user is not None and message.author is not None \
                and message.author.id == self.user.id:
            return  # 自分のメッセージではコマンドを実行しない
        if not self._message_commands:
            return
        content = (message.content or "").strip()
        if not content:
            return
        candidates = [content]
        prefix = self._resolve_prefix(message)
        if prefix is not None:
            stripped = message.content[len(prefix):].strip()
            if stripped and stripped != content:
                candidates.append(stripped)  # prefix が付いていても無視して照合する
        for key, cmd in self._message_commands.items():
            mode = getattr(cmd, "trigger_mode", "is")
            # is は完全一致なので prefix を外した形とは照合しない
            # (「!てすと」は「てすと」と完全一致ではない)
            targets = [content] if mode == "is" else candidates
            for candidate in targets:
                args_str: str | None = None
                if mode == "is":
                    if candidate == key:
                        args_str = ""
                elif mode == "start":
                    if candidate.startswith(key):
                        args_str = candidate[len(key):].strip()
                elif mode == "end":
                    if candidate.endswith(key):
                        args_str = ""  # end では手前の文は引数にしない
                elif mode == "in":
                    if key in candidate:
                        args_str = ""  # in では引数は渡らない (非推奨モード)
                if args_str is None:
                    continue
                ctx = Context(
                    self, message,
                    prefix="", command=cmd, invoked_with=key, args_str=args_str,
                )
                try:
                    await cmd.invoke(ctx, args_str)
                except CommandError as exc:
                    await self._dispatch_command_error(ctx, exc)
                return

    async def process_commands(self, message: Message) -> bool:
        """プレフィックスコマンドを処理する。実行したら True を返す."""
        if self.user is not None and message.author is not None \
                and message.author.id == self.user.id:
            return False  # 自分のメッセージではコマンドを実行しない
        prefix = self._resolve_prefix(message)
        if prefix is None:
            return False
        rest = message.content[len(prefix):].lstrip()
        if not rest:
            return False
        invoked_with, _, args_str = rest.partition(" ")
        args_str = args_str.strip()
        # コマンド名の直後が改行/タブの場合も拾う
        if not args_str and any(sep in rest for sep in ("\n", "\t")):
            parts = rest.replace("\t", " ").replace("\n", " ").split(None, 1)
            invoked_with = parts[0]
            args_str = parts[1].strip() if len(parts) > 1 else ""

        cmd = self.get_command(invoked_with)
        ctx = Context(
            self, message,
            prefix=prefix, command=cmd, invoked_with=invoked_with, args_str=args_str,
        )
        if cmd is None:
            await self._dispatch_command_error(ctx, CommandNotFound(invoked_with))
            return False
        try:
            await cmd.invoke(ctx, args_str)
        except CommandError as exc:
            await self._dispatch_command_error(ctx, exc)
        return True

    # --- スラッシュコマンド ---------------------------------------------------
    def slash_command(self, *, name: str | None = None, description: str | None = None,
                      options: list | None = None):
        """@bot.slash_command(): スラッシュコマンドを登録する.

        ハンドラは Interaction を受け取る:
            @bot.slash_command(description="挨拶する",
                               options=[string_option("who", "相手", required=True)])
            async def greet(interaction):
                await interaction.respond(f"こんにちは、{interaction.options['who']}さん！")

        登録は Bot 起動時に PUT /commands で一括で行われる。
        """
        def decorator(func):
            cmd_name = name or func.__name__
            desc = description or (inspect.getdoc(func) or cmd_name).splitlines()[0][:100]
            definition: dict = {"name": cmd_name, "description": desc}
            if options:
                definition["options"] = options
            self._slash_commands[cmd_name] = (func, definition)
            return func

        return decorator

    @property
    def slash_commands(self) -> dict:
        return {name: definition for name, (_, definition) in self._slash_commands.items()}

    async def _on_before_gateway(self) -> None:
        if not self._slash_commands:
            return
        definitions = [definition for _, definition in self._slash_commands.values()]
        try:
            await self.http.replace_commands(definitions)
            log.info("スラッシュコマンドを %d 件登録しました", len(definitions))
        except Exception:  # noqa: BLE001 - 登録失敗でも Bot 自体は起動を続ける
            log.exception("スラッシュコマンドの登録に失敗しました")

    async def _after_interaction(self, interaction) -> None:
        entry = self._slash_commands.get(interaction.command_name or "")
        if entry is None:
            return
        callback, _ = entry
        try:
            params = inspect.signature(callback).parameters
            if len(params) <= 1 and not any(
                    p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
                await callback(interaction)
            else:
                kwargs = {k: v for k, v in interaction.options.items() if k in params}
                if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
                    kwargs = dict(interaction.options)
                await callback(interaction, **kwargs)
        except Exception as exc:  # noqa: BLE001
            await self._dispatch_command_error(
                interaction, CommandInvokeError(exc)
            )

    async def _dispatch_command_error(self, ctx: Context, error: CommandError) -> None:
        handlers = self._listeners.get("command_error", ())
        if not handlers:
            log.warning("コマンドエラー (%s): %s", ctx.invoked_with, error)
            return
        for handler in handlers:
            try:
                await handler(ctx, error)
            except Exception:  # noqa: BLE001
                log.exception("on_command_error ハンドラ自体が例外を出しました")
