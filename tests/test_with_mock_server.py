"""モックの Harmony サーバー (REST + Gateway) に対してライブラリを E2E テストする。

実行: python tests/test_with_mock_server.py
公式APIのドキュメント (docs/build/*.md) の形に合わせたモックなので、
実サーバーとは通信しない。
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp import web  # noqa: E402

import harmony  # noqa: E402
from harmony import commands  # noqa: E402
from harmony.errors import NotSupportedError  # noqa: E402

BOT_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())
SERVER_ID = str(uuid.uuid4())
CHANNEL_ID = str(uuid.uuid4())
CHANNEL2_ID = str(uuid.uuid4())
HELLO_MSG_ID = str(uuid.uuid4())
SEND_MSG_ID = str(uuid.uuid4())

records = {
    "posts": [],        # (channel_id, body)
    "deletes": [],      # message_id
    "heartbeats": 0,
    "identify_token": None,
    "hello_ctx": None,
    "send_args": [],
    "errors": [],
    "handler_errors": [],
    "ready": False,
    "typo_ran": False,
    "commands_put": None,
    "interaction_callbacks": [],  # (interaction_id, body)
    "greet_seen": None,
    "message_cmd": [],    # (wao, data, prefix) @bot.message() の記録
    "in_cmd": [],         # @bot.message("in") の記録
    "conflict": [],       # command / message のどちらが実行されたか
}
gateway_ws = None


def message_obj(msg_id, channel_id, content, author):
    return {
        "id": msg_id,
        "channel_id": channel_id,
        "thread_id": None,
        "author": author,
        "content": content,
        "content_raw": [{"type": "text", "text": content}],
        "is_system": False,
        "reply_to": None,
        "timestamp": "2026-11-14T00:00:00+00:00",
        "edited_timestamp": "2026-11-14T00:00:00+00:00",
        "mentions": [],
        "mention_everyone": False,
        "metadata": {},
    }


BOT_AUTHOR = {"id": BOT_ID, "username": "test-bot", "display_name": "Test Bot", "bot": True}
ALICE = {
    "id": USER_ID, "username": "alice", "display_name": "Alice",
    "nickname": "Al", "bot": False,
}


async def handle_me(request):
    return web.json_response({
        "id": BOT_ID, "username": "test-bot", "discriminator": "0000",
        "bot": True, "verified": False, "public": True,
    })


async def handle_get_server(request):
    return web.json_response({
        "id": SERVER_ID, "name": "Test Server", "icon": None,
        "owner_id": USER_ID, "description": None, "member_count": 3,
    })


async def handle_list_channels(request):
    return web.json_response([
        {"id": CHANNEL_ID, "type": 0, "guild_id": SERVER_ID, "name": "general",
         "position": 0, "order": 0, "parent_id": None, "category_id": None},
        {"id": CHANNEL2_ID, "type": 0, "guild_id": SERVER_ID, "name": "announce",
         "position": 1, "order": 1, "parent_id": None, "category_id": None},
    ])


async def handle_create_message(request):
    channel_id = request.match_info["channel_id"]
    body = await request.json()
    records["posts"].append((channel_id, body))
    return web.json_response(
        message_obj(str(uuid.uuid4()), channel_id, body.get("content", ""), BOT_AUTHOR),
        status=201,
    )


async def handle_delete_message(request):
    records["deletes"].append(request.match_info["message_id"])
    return web.Response(status=204)


async def handle_replace_commands(request):
    records["commands_put"] = await request.json()
    return web.json_response(records["commands_put"])


async def handle_interaction_callback(request):
    body = await request.json()
    records["interaction_callbacks"].append((request.match_info["interaction_id"], body))
    return web.Response(status=204)


async def handle_gateway(request):
    global gateway_ws
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    gateway_ws = ws
    async for raw in ws:
        payload = raw.json()
        if payload.get("op") == 2:
            records["identify_token"] = payload["d"]["token"]
            await ws.send_json({
                "op": 0, "t": "READY",
                "d": {
                    "bot": {"id": BOT_ID, "username": "test-bot"},
                    "session_id": str(uuid.uuid4()),
                    "heartbeat_interval": 200,
                },
            })
            await asyncio.sleep(0.2)
            await ws.send_json({
                "op": 0, "t": "MESSAGE_CREATE",
                "d": message_obj(HELLO_MSG_ID, CHANNEL_ID, "!hello", ALICE),
            })
        elif payload.get("op") == 1:
            records["heartbeats"] += 1
            await ws.send_json({"op": 11})
    return ws


async def push_message(msg_id, content):
    await gateway_ws.send_json({
        "op": 0, "t": "MESSAGE_CREATE",
        "d": message_obj(msg_id, CHANNEL_ID, content, ALICE),
    })


async def wait_for(cond, timeout=10.0, label=""):
    waited = 0.0
    while waited < timeout:
        if cond():
            return
        await asyncio.sleep(0.05)
        waited += 0.05
    raise AssertionError(f"タイムアウト: {label}")


def build_bot(base_url):
    bot = commands.Bot(command_prefix="!", base_url=base_url, preload_servers=[SERVER_ID])

    @bot.event
    async def on_ready():
        records["ready"] = True

    @bot.event
    async def on_error(event_name, exc, *args):
        records["handler_errors"].append((event_name, repr(exc)))

    @bot.event
    async def on_command_error(ctx, error):
        records["errors"].append(type(error).__name__)

    @bot.command()
    async def hello(ctx):
        records["hello_ctx"] = {
            "nick": ctx.user.nick,
            "name": ctx.user.name,
            "user_id": ctx.user.id,
            "chname": ctx.channel.name,
            "chid": ctx.channel.id,
            "sername": ctx.server.name if ctx.server else None,
            "serid": ctx.server.id if ctx.server else None,
            "data": ctx.data,
            "mesid": ctx.id,
        }
        await ctx.reply(f"{ctx.user.nick}さん！こんにちは！")
        await ctx.send(f"{ctx.user.name}さん！おはよう！")
        await ctx.delete

    @bot.command()
    async def send(ctx, channel_id=None):
        records["send_args"].append(channel_id)
        if channel_id is None:
            await ctx.reply("使い方: !send <チャンネルid>")
            return
        ch = harmony.get_channel(channel_id)
        await ch.send("こんにちは")

    @bot.commant()  # サンプルにあったタイプミスのエイリアスでも登録できること
    async def typo(ctx):
        records["typo_ran"] = True

    @bot.message("is")  # 完全一致: 「てすと」だけで発火する
    async def てすと(ctx):
        records["message_cmd"].append(
            {"mode": "is", "data": ctx.data, "prefix": ctx.prefix})
        await ctx.reply("てすと応答")

    @bot.message("start")  # 先頭一致: 残りが引数になる
    async def すたーと(ctx, wao=None):
        records["message_cmd"].append({"mode": "start", "wao": wao})
        await ctx.reply(f"すたーと応答 wao={wao}")

    @bot.message("end")  # 末尾一致: 引数は渡らない
    async def えんど(ctx):
        records["message_cmd"].append({"mode": "end", "data": ctx.data})
        await ctx.reply("えんど応答")

    @bot.message("in")  # 含まれていたら発火 (非推奨モード)
    async def ほげ(ctx):
        records["in_cmd"].append(ctx.data)
        await ctx.reply("ほげ発火")

    @bot.command()  # 競合テスト用: message 側と同名のコマンド
    async def こんふりくと(ctx, wao=None):
        records["conflict"].append("command")
        await ctx.reply("こんふりくと command")

    @bot.message("start", name="こんふりくと")  # 競合テスト用: command 側と同名
    async def こんふりくと_message(ctx, wao=None):
        records["conflict"].append("message")
        await ctx.reply("こんふりくと message")

    @bot.slash_command(
        description="挨拶する",
        options=[commands.string_option("who", "相手の名前", required=True)],
    )
    async def greet(interaction):
        records["greet_seen"] = dict(interaction.options)
        await interaction.respond(f"こんにちは、{interaction.options['who']}さん！")

    return bot


async def main():
    app = web.Application()
    api = "/bot-gateway/api/v1"
    app.router.add_get(f"{api}/users/@me", handle_me)
    app.router.add_get(f"{api}/servers/{{server_id}}", handle_get_server)
    app.router.add_get(f"{api}/servers/{{server_id}}/channels", handle_list_channels)
    app.router.add_post(f"{api}/channels/{{channel_id}}/messages", handle_create_message)
    app.router.add_delete(f"{api}/messages/{{message_id}}", handle_delete_message)
    app.router.add_put(f"{api}/commands", handle_replace_commands)
    app.router.add_post(f"{api}/interactions/{{interaction_id}}/callback",
                        handle_interaction_callback)
    app.router.add_get("/bot-gateway/gateway", handle_gateway)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1] if runner.addresses else site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    bot = build_bot(base_url)
    task = asyncio.create_task(bot.start("harmony_bot_" + "0" * 64))
    try:
        # --- hello コマンドの一連の流れ ---
        await wait_for(lambda: len(records["posts"]) >= 2 and records["deletes"],
                       label="hello の reply/send/delete")
        assert records["ready"] is True
        assert records["identify_token"].startswith("harmony_bot_")
        ctx = records["hello_ctx"]
        assert ctx["nick"] == "Al", ctx
        assert ctx["name"] == "alice", ctx
        assert ctx["user_id"] == USER_ID, ctx
        assert ctx["chname"] == "general", ctx
        assert ctx["chid"] == CHANNEL_ID, ctx
        assert ctx["sername"] == "Test Server", ctx
        assert ctx["serid"] == SERVER_ID, ctx
        assert ctx["data"] == "!hello", ctx
        assert ctx["mesid"] == HELLO_MSG_ID, ctx
        reply_post, send_post = records["posts"][0], records["posts"][1]
        assert reply_post[0] == CHANNEL_ID
        assert reply_post[1]["content"] == "Alさん！こんにちは！", reply_post
        assert reply_post[1]["reply_to"] == HELLO_MSG_ID, reply_post
        assert send_post[1]["content"] == "aliceさん！おはよう！", send_post
        assert "reply_to" not in send_post[1], send_post
        assert records["deletes"] == [HELLO_MSG_ID], records["deletes"]
        assert bot.name == "test-bot"
        print("PASS: on_ready / !hello (ctx の各属性, reply, send, delete)")

        # --- send コマンド (引数あり/なし, モジュール関数 get_channel) ---
        await push_message(SEND_MSG_ID, f"!send {CHANNEL2_ID}")
        await wait_for(lambda: len(records["posts"]) >= 3, label="!send の転送")
        assert records["posts"][2][0] == CHANNEL2_ID, records["posts"][2]
        assert records["posts"][2][1]["content"] == "こんにちは"
        assert records["send_args"] == [CHANNEL2_ID]

        await push_message(str(uuid.uuid4()), "!send")
        await wait_for(lambda: len(records["posts"]) >= 4, label="!send 引数なし")
        assert records["send_args"] == [CHANNEL2_ID, None]
        assert records["posts"][3][1]["content"] == "使い方: !send <チャンネルid>"
        print("PASS: !send (引数の受け渡し, デフォルト値, get_channel)")

        # --- 未知のコマンド / commant エイリアス ---
        await push_message(str(uuid.uuid4()), "!sonna-command-nai")
        await wait_for(lambda: records["errors"], label="CommandNotFound")
        assert records["errors"] == ["CommandNotFound"], records["errors"]

        await push_message(str(uuid.uuid4()), "!typo")
        await wait_for(lambda: records["typo_ran"], label="commant エイリアス")
        print("PASS: 未知のコマンドは on_command_error へ / @bot.commant() エイリアス")

        # --- @bot.message() (prefix なしコマンド, 照合モード) ---
        posts_before = len(records["posts"])
        # is: 本文全体が完全一致したときだけ発火
        await push_message(str(uuid.uuid4()), "てすと")
        await wait_for(lambda: len(records["message_cmd"]) >= 1, label="てすと is")
        assert records["message_cmd"][0] == {
            "mode": "is", "data": "てすと", "prefix": ""}, records["message_cmd"]
        await push_message(str(uuid.uuid4()), "てすと わお")  # is では発火しない
        await push_message(str(uuid.uuid4()), "てすとです")    # is では発火しない
        await push_message(str(uuid.uuid4()), "!てすと")      # is は完全一致なので発火しない
        await asyncio.sleep(0.3)
        assert len(records["message_cmd"]) == 1, records["message_cmd"]
        # start: 先頭一致で発火し、残りが引数になる
        await push_message(str(uuid.uuid4()), "すたーと わお")
        await wait_for(lambda: len(records["message_cmd"]) >= 2, label="すたーと start")
        assert records["message_cmd"][1] == {
            "mode": "start", "wao": "わお"}, records["message_cmd"]
        await push_message(str(uuid.uuid4()), "すたーとです")  # 頭にあれば発火
        await wait_for(lambda: len(records["message_cmd"]) >= 3,
                       label="すたーとです start")
        assert records["message_cmd"][2]["wao"] == "です", records["message_cmd"]
        # start は prefix が付いていても無視して発火する
        await push_message(str(uuid.uuid4()), "!すたーと わお3")
        await wait_for(lambda: len(records["message_cmd"]) >= 4,
                       label="!すたーと start (prefix 無視)")
        assert records["message_cmd"][3]["wao"] == "わお3", records["message_cmd"]
        # end: 末尾一致で発火する (手前の文は引数にならない)
        await push_message(str(uuid.uuid4()), "わお えんど")
        await wait_for(lambda: len(records["message_cmd"]) >= 5, label="えんど end")
        assert records["message_cmd"][4] == {
            "mode": "end", "data": "わお えんど"}, records["message_cmd"]
        await wait_for(lambda: len(records["posts"]) >= posts_before + 5,
                       label="message コマンドの reply x5")
        print("PASS: @bot.message() (照合モード is/start/end, is は prefix 不可)")

        # --- @bot.message("in") (非推奨モード) ---
        await push_message(str(uuid.uuid4()), "まんなかほげ入り")
        await wait_for(lambda: records["in_cmd"], label="in モード発火")
        assert records["in_cmd"] == ["まんなかほげ入り"], records["in_cmd"]
        print("PASS: @bot.message(\"in\") (含まれていたら発火)")

        # --- 競合したら bot.command を優先 ---
        await push_message(str(uuid.uuid4()), "こんふりくと わお")
        await wait_for(lambda: records["conflict"], label="競合: prefix なしは message")
        assert records["conflict"] == ["message"], records["conflict"]
        await push_message(str(uuid.uuid4()), "!こんふりくと わお")
        await wait_for(lambda: len(records["conflict"]) >= 2,
                       label="競合: prefix ありは command 優先")
        assert records["conflict"] == ["message", "command"], records["conflict"]
        print("PASS: 競合したら bot.command を優先 (bot.message は実行されない)")

        # --- API に無い操作は NotSupportedError ---
        channel = bot.get_channel(CHANNEL_ID)
        for coro_factory, label in [
            (lambda: channel.rename("new-name"), "channel.rename"),
            (lambda: channel.delete(), "channel.delete"),
            (lambda: bot.get_server(SERVER_ID).rename("new"), "server.rename"),
        ]:
            try:
                await coro_factory()
            except NotSupportedError:
                pass
            else:
                raise AssertionError(f"{label} が NotSupportedError を出しませんでした")
        print("PASS: API に無い rename/delete は NotSupportedError")

        # --- スラッシュコマンド (登録 + INTERACTION_CREATE + 応答) ---
        assert records["commands_put"] is not None
        put_names = [c["name"] for c in records["commands_put"]]
        assert put_names == ["greet"], put_names
        assert records["commands_put"][0]["options"][0]["type"] == 3
        interaction_id = str(uuid.uuid4())
        await gateway_ws.send_json({
            "op": 0, "t": "INTERACTION_CREATE",
            "d": {
                "id": interaction_id, "type": 2,
                "server_id": SERVER_ID, "channel_id": CHANNEL_ID, "thread_id": None,
                "user": {"id": USER_ID, "username": "alice", "display_name": "Alice",
                         "bot": False},
                "member": {"nickname": "Al", "roles": [], "permissions": []},
                "data": {"id": str(uuid.uuid4()), "name": "greet", "type": 1,
                         "options": [{"name": "who", "type": 3, "value": "世界"}]},
                "created_at": "2026-11-14T00:00:00Z",
                "respond_by": "2026-11-14T00:00:05Z",
                "expires_at": "2026-11-14T00:15:00Z",
            },
        })
        await wait_for(lambda: records["interaction_callbacks"],
                       label="スラッシュコマンドの応答")
        cb_id, cb_body = records["interaction_callbacks"][0]
        assert cb_id == interaction_id
        assert cb_body["type"] == 4, cb_body
        assert cb_body["data"]["content"] == "こんにちは、世界さん！", cb_body
        assert records["greet_seen"] == {"who": "世界"}
        print("PASS: スラッシュコマンド (PUT /commands 登録, INTERACTION_CREATE, 応答)")

        # --- ハートビートが送られていること ---
        await wait_for(lambda: records["heartbeats"] >= 2, label="heartbeat")
        print("PASS: Gateway ハートビート (op 1)")

        assert not records["handler_errors"], records["handler_errors"]
    finally:
        await bot.close()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        await runner.cleanup()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
