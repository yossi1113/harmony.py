"""実サーバーテスト第2弾: 機能を広く叩く使い捨て Bot (てすたー専用)。

トークンは標準入力の1行目から受け取る。
各テストは結果をチャンネルに投稿し、詳細を標準出力にも記録する。
"""

import sys
import traceback

sys.path.insert(0, str(__file__).rsplit("/examples/", 1)[0])

from harmony import commands  # noqa: E402
from harmony.commands import string_option  # noqa: E402

bot = commands.Bot(command_prefix="!")
STATE = {"server": None}


def log(*args):
    print(*args, flush=True)


async def report(ctx, text):
    log("REPORT:", text)
    await ctx.send(text)


@bot.event
async def on_ready():
    log(f"READY: {bot.name} (id={bot.user.id})")


@bot.event
async def on_message(message):
    author = message.author.name if message.author else None
    log(f"MESSAGE: author={author} channel={message.channel_id} content={message.content!r}")


@bot.event
async def on_command_error(ctx, error):
    original = getattr(error, "original", error)
    log(f"COMMAND_ERROR: {type(error).__name__}: {original!r}")


@bot.event
async def on_reaction_add(event):
    log(f"REACTION_ADD: emoji={event.emoji.name!r} user_id={event.user_id} bot_id={event.bot_id} "
        f"message_id={event.message_id}")
    if event.bot_id and bot.user and event.bot_id == bot.user.id:
        return  # 自分のリアクションは無視
    if event.user_id:
        channel = bot.get_channel(event.channel_id)
        await channel.send(f"リアクションイベント受信: {event.emoji.name}")


@bot.event
async def on_reaction_remove(event):
    log(f"REACTION_REMOVE: emoji={event.emoji.name!r} user_id={event.user_id} "
        f"message_id={event.message_id}")


@bot.event
async def on_message_edit(message):
    log(f"MESSAGE_EDIT: id={message.id} content={message.content!r}")
    if "editme" in (message.content or ""):
        await message.send(f"編集イベント受信: {message.content}")


@bot.event
async def on_message_delete(partial):
    log(f"MESSAGE_DELETE: id={partial.id} channel={partial.channel_id}")
    channel = bot.get_channel(partial.channel_id)
    await channel.send(f"削除イベント受信: {partial.id}")


@bot.command()
async def ping(ctx):
    await ctx.reply("Pong!")


@bot.command()
async def edit_test(ctx):
    msg = await ctx.send("編集テスト: 編集前")
    await msg.edit("編集テスト: 編集後")
    await report(ctx, "edit_test 完了: 自分のメッセージを編集しました")


@bot.command()
async def delete_test(ctx):
    msg = await ctx.send("削除テスト: このメッセージは消えます")
    await msg.delete()
    await report(ctx, "delete_test 完了: 自分のメッセージを削除しました")


@bot.command()
async def delete_cmd_test(ctx):
    try:
        await ctx.message.delete()
        await report(ctx, "delete_cmd_test: コマンドメッセージの削除に成功しました")
    except Exception as exc:  # noqa: BLE001
        await report(ctx, f"delete_cmd_test: コマンドメッセージの削除に失敗 ({type(exc).__name__}: {exc})")


@bot.command()
async def react_test(ctx):
    msg = await ctx.send("リアクションテスト: Bot が 👍 と ❤️ を付けます")
    await msg.add_reaction("👍")
    await msg.add_reaction("❤️")
    await ctx.send("リアクションイベントテスト用: このメッセージに何かリアクションを付けてください")


@bot.command()
async def history_test(ctx):
    msgs = await ctx.channel.history(limit=5)
    summary = " / ".join((m.content or "")[:20] for m in msgs)
    await report(ctx, f"history_test: 直近 {len(msgs)} 件取得: {summary}")


@bot.command()
async def fetch_test(ctx):
    msgs = await ctx.channel.history(limit=2)
    if not msgs:
        await report(ctx, "fetch_test: 履歴が空でした")
        return
    target = msgs[0]
    data = await bot.http.get_message(target.id)
    await report(ctx, f"fetch_test: id={data.get('id')} author={data.get('author')} "
                      f"content={data.get('content')!r}")


@bot.command()
async def typing_test(ctx):
    await bot.http.trigger_typing(ctx.channel.id)
    await report(ctx, "typing_test: typing エンドポイントを叩きました (204想定)")


@bot.command()
async def thread_test(ctx):
    thread = await ctx.channel.create_thread("テストスレッド", message_id=ctx.id)
    await thread.send("スレッド内からこんにちは")
    await report(ctx, f"thread_test: スレッドを作成しました (id={thread.id}, name={thread.name})")


@bot.command()
async def server_info(ctx, server_id=None):
    if not server_id:
        await report(ctx, "使い方: !server_info <サーバーID>")
        return
    server = await bot.fetch_server(server_id)
    STATE["server"] = server
    channels = await server.channels()
    members = await server.members(limit=10)
    roles = await server.roles()
    categories = await server.categories()
    log(f"SERVER_INFO: name={server.name} members={server.member_count} "
        f"channels={[c.name for c in channels]} roles={[r.name for r in roles]} "
        f"categories={[c.name for c in categories]} member_rows={len(members)}")
    await report(ctx, f"server_info: {server.name} / チャンネル {[c.name for c in channels]} / "
                      f"ロール {[r.name for r in roles]} / カテゴリ {[c.name for c in categories]}")


@bot.command()
async def structure_test(ctx):
    server = STATE.get("server")
    if server is None:
        await report(ctx, "structure_test: 先に !server_info <サーバーID> を実行してください")
        return
    results = []
    try:
        channel = await server.create_channel("lib-test-channel")
        results.append(f"チャンネル作成OK ({channel.name})")
    except Exception as exc:  # noqa: BLE001
        results.append(f"チャンネル作成NG ({type(exc).__name__}: {exc})")
    try:
        category = await server.create_category("lib-test-category")
        await category.rename("lib-test-category-renamed")
        results.append(f"カテゴリ作成+リネームOK ({category.name})")
    except Exception as exc:  # noqa: BLE001
        results.append(f"カテゴリ作成/リネームNG ({type(exc).__name__}: {exc})")
    try:
        role = await server.create_role("lib-test-role", color="#00ccff")
        results.append(f"ロール作成OK ({role.name})")
        await bot.http.delete_role(server.id, role.id)
        results.append("ロール削除OK")
    except Exception as exc:  # noqa: BLE001
        results.append(f"ロール作成/削除NG ({type(exc).__name__}: {exc})")
    await report(ctx, "structure_test: " + " / ".join(results))


@bot.slash_command(
    description="挨拶する (スラッシュコマンドのテスト)",
    options=[string_option("who", "相手の名前", required=False)],
)
async def greet(interaction):
    who = interaction.options.get("who") or "みなさん"
    log(f"SLASH greet: who={who!r} user={interaction.user.name if interaction.user else None}")
    await interaction.respond(f"こんにちは、{who}さん！ (スラッシュコマンド経由)")


@bot.slash_command(description="自分にだけ見える応答のテスト")
async def secret(interaction):
    log("SLASH secret")
    await interaction.respond("これはあなただけに見える応答です", ephemeral=True)


if __name__ == "__main__":
    token = sys.stdin.readline().strip()
    if not token:
        print("ERROR: トークンが標準入力から渡されませんでした", flush=True)
        sys.exit(2)
    try:
        bot.run(token)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
