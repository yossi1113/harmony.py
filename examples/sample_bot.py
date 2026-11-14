"""harmony.py のサンプル Bot (実装済み機能の全部入り)。

このファイルに載っているのは、ライブラリに実装されていて実際に使える
機能だけです。Harmony Bot API 本体にルートが存在しない操作
(チャンネルの名前変更・削除、サーバーの名前変更など) は載せていません。

使い方の前提:
- ID は全部 UUID 文字列 (int ではない)
- ctx.channel.name / ctx.server を解決するには preload_servers が要る。
  MESSAGE_CREATE イベントに server_id が含まれないため、Bot が事前に
  fetch_server() で取り込んだサーバーだけ名前解決できる

実行方法:
    export HARMONY_BOT_TOKEN='harmony_bot_...'
    export HARMONY_SERVER_ID='<サーバーID>'   # 任意 (名前解決用)
    python sample_bot.py
"""

import asyncio
import os

import harmony
from harmony import commands
from harmony.commands import string_option

SERVER_ID = os.environ.get("HARMONY_SERVER_ID", "")

bot = commands.Bot(
    command_prefix="!",
    preload_servers=[SERVER_ID] if SERVER_ID else [],
)

# 補足: 元サンプルのタイポだった @bot.commant() も互換のため残してあるが、
# 通常は @bot.command() を使う。


# ============================================================
# イベント
# ============================================================

@bot.event
async def on_ready():
    # bot.name はユーザー名。Bot には API 上ニックネームが無いので
    # bot.nick は通常 None
    print(f"{bot.name}({bot.nick}) has connected to harmony!")


@bot.event
async def on_message(message):
    # 全メッセージ (コマンド以外も) が来る。コマンド処理は Bot が別途行う
    author = message.author.name if message.author else None
    print(f"message: {author}: {message.content!r}")


@bot.event
async def on_message_edit(message):
    print(f"message edited: {message.id}: {message.content!r}")


@bot.event
async def on_message_delete(partial):
    # 削除イベントには ID しか含まれない
    print(f"message deleted: {partial.id} in channel {partial.channel_id}")


@bot.event
async def on_reaction_add(event):
    # event.emoji.name は絵文字名 (カスタム絵文字も名前で来る)
    # 自分 (Bot) が付けたリアクションも届くので、必要なら bot_id で弾く
    if event.bot_id and bot.user and event.bot_id == bot.user.id:
        return
    print(f"reaction add: {event.emoji.name} by {event.user_id} "
          f"on message {event.message_id}")


@bot.event
async def on_reaction_remove(event):
    print(f"reaction remove: {event.emoji.name} by {event.user_id}")


@bot.event
async def on_member_join(member):
    print(f"member join: {member.name}")


@bot.event
async def on_member_remove(member):
    print(f"member remove: {member.name}")


@bot.event
async def on_command_error(ctx, error):
    # コマンドが見つからない / 引数不足 / 型変換失敗 / 実行時例外 で呼ばれる
    # 例外クラスは harmony 直下からも import できる
    # (harmony.CommandNotFound など。基底は harmony.HarmonyError、
    #  REST 系は harmony.HTTPError / Forbidden / NotFound / RateLimited)
    if isinstance(error, commands.CommandNotFound):
        print(f"unknown command: {error}")
    elif isinstance(error, commands.MissingRequiredArgument):
        print(f"missing argument: {error}")
    elif isinstance(error, commands.CommandInvokeError):
        print(f"command raised: {error.original!r}")
    else:
        print(f"command error: {error!r}")


# ============================================================
# プレフィックスコマンド (!ping など)
# ============================================================

@bot.command(aliases=["p"])
async def ping(ctx):
    # aliases を付けると !p でも呼べる
    await ctx.reply("Pong!")


@bot.command()
async def hello(ctx):
    nick = ctx.user.nick      # 実行者のニックネーム (無ければ表示名/ユーザー名)
    name = ctx.user.name      # 実行者のユーザーネーム
    user_id = ctx.user.id     # 実行者のユーザーID (UUID 文字列)
    chname = ctx.channel.name  # チャンネル名 (未取得なら None)
    chid = ctx.channel.id      # チャンネルID
    sername = ctx.server.name if ctx.server else None  # サーバー名
    serid = ctx.server.id if ctx.server else None      # サーバーID
    mesdata = ctx.data  # コマンドメッセージの本文 (ctx.message.content と同じ)
    mesid = ctx.id      # コマンドメッセージのID
    print(f"hello from {name} ({user_id}) in #{chname} ({chid}) "
          f"server={sername} ({serid}) message={mesid}: {mesdata}")
    await ctx.reply(f"{nick}さん！こんにちは！")  # コマンドに返信
    await ctx.send(f"{name}さん！おはよう！")      # 同じチャンネルに送信
    await ctx.delete  # コマンドメッセージを削除 (await ctx.delete() でも同じ)


@bot.command()
async def send(ctx, channel_id=None):
    # !send <チャンネルid> — 引数は文字列。デフォルト値は省略時の代替
    if channel_id is None:
        await ctx.reply("使い方: !send <チャンネルid>")
        return
    ch = bot.get_channel(channel_id)       # ID からチャンネルオブジェクトを取得
    _ = harmony.get_channel(channel_id)    # モジュール関数でも同じことができる
    await ch.send("こんにちは")


@bot.command()
async def add(ctx, a: int, b: int):
    # !add 2 3 — 型注釈を付けると自動で変換される (失敗すると BadArgument)
    await ctx.reply(f"{a} + {b} = {a + b}")


@bot.command()
async def editme(ctx):
    # 自分のメッセージを編集する
    msg = await ctx.send("編集前")
    await msg.edit("編集後")


@bot.command()
async def deleteme(ctx):
    # 自分のメッセージを削除する
    msg = await ctx.send("このメッセージは消えます")
    await msg.delete()


@bot.command()
async def react(ctx):
    # リアクションの追加と取り消し
    msg = await ctx.send("リアクションのテストです")
    await msg.add_reaction("👍")
    await msg.add_reaction("❤️")
    await msg.remove_reaction("❤️")


@bot.command()
async def history(ctx):
    # チャンネルの直近メッセージを取得する
    msgs = await ctx.channel.history(limit=5)
    summary = " / ".join((m.content or "")[:20] for m in msgs)
    await ctx.reply(f"直近 {len(msgs)} 件: {summary}")


@bot.command()
async def thread(ctx):
    # スレッドを作って、その中へ投稿する
    th = await ctx.channel.create_thread("テストスレッド", message_id=ctx.id)
    await th.send("スレッド内からこんにちは")
    await ctx.reply(f"スレッドを作りました: {th.name}")


@bot.command()
async def typing(ctx):
    # 入力中表示のエンドポイント (サーバー側は現状 no-op で、表示はされない)
    await bot.http.trigger_typing(ctx.channel.id)
    await ctx.reply("typing エンドポイントを叩きました")


@bot.command()
async def userinfo(ctx, user_id=None):
    # !userinfo <ユーザーID> — ユーザーを取得する (例外ハンドリングの例)
    if user_id is None:
        await ctx.reply("使い方: !userinfo <ユーザーID>")
        return
    try:
        user = await bot.fetch_user(user_id)
    except harmony.NotFound:
        await ctx.reply("そのユーザーは見つかりませんでした")
        return
    except harmony.Forbidden:
        await ctx.reply("そのユーザーを見る権限がありません")
        return
    await ctx.reply(f"{user.name} (id={user.id}, bot={user.bot})")


@bot.command()
async def serverinfo(ctx, server_id=None):
    # !serverinfo <サーバーID> — サーバーの構造を取得する
    if server_id is None:
        await ctx.reply("使い方: !serverinfo <サーバーID>")
        return
    _ = harmony.get_server(server_id)  # モジュール関数のサーバー取得
    server = await bot.fetch_server(server_id)  # 最新情報を REST で取得
    channels = await server.channels()
    categories = await server.categories()
    roles = await server.roles()
    members = await server.members(limit=10)
    await ctx.reply(
        f"{server.name} (owner={server.owner_id}, member_count={server.member_count})\n"
        f"チャンネル: {[c.name for c in channels]}\n"
        f"カテゴリ: {[c.name for c in categories]}\n"
        f"ロール: {[r.name for r in roles]}\n"
        f"メンバー(先頭{len(members)}件): {[m.name for m in members]}"
    )


@bot.command()
async def build(ctx, server_id=None):
    # !build <サーバーID> — チャンネル/カテゴリ/ロールを作る (管理者向け)
    if server_id is None:
        await ctx.reply("使い方: !build <サーバーID>")
        return
    server = await bot.fetch_server(server_id)
    category = await server.create_category("サンプルカテゴリ")
    await category.rename("サンプルカテゴリ改")  # カテゴリは名前変更できる
    channel = await server.create_channel("サンプルチャンネル")
    await channel.edit(category_id=category.id)  # チャンネルをカテゴリへ移動
    role = await server.create_role("サンプルロール", color="#00ccff")
    # ロールの削除はモデルにメソッドが無いので REST (bot.http) 経由
    await bot.http.delete_role(server.id, role.id)
    await ctx.reply("カテゴリ・チャンネル・ロールを作成しました (ロールは削除済み)")


# ============================================================
# メッセージコマンド (prefix なし)
# @bot.command() として実行されたメッセージでは発火しない
# (競合したら bot.command を優先する)
# ============================================================

@bot.message("is")
async def てすと(ctx):
    # 「てすと」と送られたときに実行される。ctx はメッセージオブジェクト
    # として扱える。"is" は本文全体との完全一致なので、「てすと わお」でも
    # 「!てすと」でも発火しない (完全一致ではないため)
    await ctx.reply("てすと！")


@bot.message("start")
async def めも(ctx, text=None):
    # "start" は本文が関数名で始まっていれば発火し、残りが引数になる
    # 「めも 買い物リスト」→ text="買い物リスト"
    await ctx.reply(f"めもしました: {text}")


@bot.message("end")
async def おやすみ(ctx):
    # "end" は本文が関数名で終わっていれば発火する
    # 「先に寝るね、おやすみ」などで発火 (区切り文字はそのまま残る)
    await ctx.reply("おやすみなさい！")


@bot.message("in")
async def ほげ(ctx):
    # "in" は本文に関数名が含まれていれば発火する (非推奨: 会話の途中で
    # 単語が出ただけでも反応してしまう)。引数は渡らない
    await ctx.reply("ほげ！")


# ============================================================
# スラッシュコマンド (/greet など)
# 起動時に PUT /commands で一括登録される
# ============================================================

@bot.slash_command(
    description="挨拶する",
    options=[string_option("who", "相手の名前", required=False)],
)
async def greet(interaction):
    who = interaction.options.get("who") or "みなさん"
    await interaction.respond(f"こんにちは、{who}さん！")


@bot.slash_command(description="自分にだけ見える応答")
async def secret(interaction):
    # ephemeral=True で実行した本人にだけ見える
    await interaction.respond("これはあなただけに見える応答です", ephemeral=True)


@bot.slash_command(description="時間のかかる処理 (defer の例)")
async def slow(interaction):
    # 5秒以内に defer しておくと、15分まで後から応答を編集できる
    await interaction.defer()
    await asyncio.sleep(2)
    await interaction.edit_response("処理が終わりました")
    await interaction.followup("追加のメッセージも送れます")


if __name__ == "__main__":
    bot.run(os.environ["HARMONY_BOT_TOKEN"])
