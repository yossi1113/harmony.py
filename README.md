# harmony.py

Harmony (har.mony.lol) 用の、discord.py 風に書ける非公式 Bot ライブラリ (Python)。
ちなみにmeta社のmuseってAIに書かせました、ここから下はmuseが書いた部分です、現代恐ろしい！

Harmony 本体の Bot API は、ドキュメントが `docs/bot-api.md` から
`docs/build/` 配下に分かれている。実装はそのページ群と
`bot-gateway` のソースコードを突き合わせて作ってある。

## インストール

```bash
pip install aiohttp websockets   # 依存はこの2つ (REST=aiohttp, Gateway=websockets)
# このフォルダで使う場合 (pyproject.toml あり):
pip install -e .
```

## 最小の Bot

```python
import os
import harmony
from harmony import commands

bot = commands.Bot(command_prefix="!")

@bot.event
async def on_ready():
    print(f"{bot.name} has connected to harmony!")

@bot.command()
async def hello(ctx):
    await ctx.reply(f"{ctx.user.nick}さん！こんにちは！")

bot.run(os.environ["HARMONY_BOT_TOKEN"])
```

動くサンプル一式は `examples/sample_bot.py`。
アップロードされたサンプルコードを直したもので、元の書き方からの
変更点と理由もコメントで書いてある。

prefix なしで、本文との照合で反応させることもできる:

```python
@bot.message("is")
async def てすと(ctx):
    await ctx.reply("てすと！")
```

「てすと」と送るだけで発火する。照合モードは第1引数で選ぶ: `"is"` は
本文全体との完全一致 (「!てすと」では発火しない)、`"start"` は本文が
関数名で始まっていたら (残りが引数になる)、`"end"` は本文が関数名で
終わっていたら、`"in"` は本文に関数名が含まれていたら (非推奨)。
start / end では prefix が付いていても無視して照合する。
引数が使えるのは `"start"` のみ。`@bot.command()` として実行された
メッセージでは発火しない (競合したら bot.command を優先)。

## テスト

モックサーバー相手の E2E テスト (実サーバーには繋がない):

```bash
python tests/test_with_mock_server.py
```

READY → `!hello` (reply/send/delete) → `!send <id>` → 未知のコマンド →
ハートビートまでを通しで確認する。

## 実サーバーで動かす手順

1. Harmony の **ユーザー設定 → My bots → New bot** で Bot を作る
2. 表示されるトークン (`harmony_bot_` + 16進数64文字) を控える
   (一度しか表示されない)
3. Bot のページの **Add to server** で、入れたいサーバーに追加する
4. `HARMONY_BOT_TOKEN` にトークンを入れて Bot を起動する
5. チャンネルで `!hello` と打つ

デフォルトの接続先は `https://har.mony.lol`。
セルフホストのインスタンスには `commands.Bot(..., base_url="https://...")`
か環境変数 `HARMONY_URL` で切り替えられる。

## サンプルコードから直した点・API の制約でできなかった点

調べた結果、元のサンプルの想定と実際の API が違うところがいくつかある。

| サンプルの想定 | 実際の API |
|---|---|
| ID は int | ID はすべて UUID 文字列 |
| `ch.rename(...)` チャンネルの名前変更 | ルート無し。`PATCH /channels/{id}` は並び順とカテゴリのみ |
| `ch.delete` チャンネルの削除 | ルート無し (`DELETE /channels/{id}` は存在しない) |
| `ser.rename(...)` サーバーの名前変更 | ルート無し (`PATCH /servers/{id}` は存在しない) |
| `bot.nick` Bot のニックネーム | Bot にニックネームは無い (常に None) |
| `ctx.server` が常にある | `MESSAGE_CREATE` に server_id が含まれない |

rename/delete のメソッド自体は用意してあるが、呼ぶと
`harmony.NotSupportedError` になる (嘘の成功を返さないため)。

`ctx.server` / `ctx.channel.name` については、`MESSAGE_CREATE` イベントに
サーバー情報が入っていないのが原因。回避策として、Bot 生成時に
`preload_servers=["<サーバーID>"]` を渡すか、起動後に
`await bot.fetch_server("<サーバーID>")` を呼ぶと、サーバーの
チャンネル一覧を取り込んで解決できるようにしてある。
それ以外で単体のチャンネル情報を取るルート (`GET /channels/{id}`) は
存在しないので、キャッシュに無いチャンネルの name は None になる。

## 実装済みの範囲 (v0.4.0)

- Gateway: Identify / READY / ハートビート / 自動再接続 (指数バックオフ、
  トークン拒否時は再接続しない)。イベントは
  `on_ready`, `on_message`, `on_message_edit`, `on_message_delete`,
  `on_reaction_add`, `on_reaction_remove`, `on_member_join`,
  `on_member_remove`, `on_interaction`
- コマンド: プレフィックス、エイリアス、引数の型変換 (注釈ベース)、
  デフォルト値、`key=value` 形式、`on_command_error`。
  `@bot.commant()` のタイプミス互換エイリアスも残してある
- メッセージコマンド: `@bot.message("is" | "start" | "end" | "in")` で、
  prefix なしに本文と関数名の照合 (完全一致 / 先頭一致 / 末尾一致 /
  含む) で発火するコマンドも書ける。start / end は prefix が付いていても
  無視して照合し、is は完全一致のため prefix 付きでは発火しない。
  "in" は会話の途中の単語にも反応するので非推奨。
  `@bot.command()` と競合したら bot.command を優先する
- 例外: 基底の `harmony.HarmonyError` のもとに、REST 系
  (`HTTPError` / `Forbidden` / `NotFound` / `RateLimited` /
  `LoginFailure` / `NotSupportedError` / `InvalidArgument`) と
  コマンド系 (`CommandError` / `CommandNotFound` /
  `MissingRequiredArgument` / `BadArgument` / `CommandInvokeError`) が
  あり、すべて `harmony` 直下から import できる
- スラッシュコマンド: `@bot.slash_command()` で定義すると起動時に
  `PUT /commands` で登録される。ハンドラは Interaction を受け取り、
  `interaction.respond(...)` / `defer()` / `edit_response()` /
  `followup()`、ephemeral (自分だけに見える) 応答も使える。
  オプション定義用に `string_option` などのヘルパーがある
- REST: メッセージ送信/取得/編集/削除、リアクション、スレッド作成、
  サーバー/メンバー/チャンネル/カテゴリ/ロール取得と作成、
  カテゴリのリネーム、ロールの削除、チャンネルの並び替え、
  招待プレビュー、ユーザー取得
- `ctx.delete` / `msg.delete` / `ch.delete` は `await obj.delete` でも
  `await obj.delete()` でも動く


