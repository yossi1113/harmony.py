"""実サーバーテスト第3弾: @bot.message() の照合モード検証 (てすたー専用)。

トークンは標準入力の1行目から受け取る。
"""

import sys

sys.path.insert(0, str(__file__).rsplit("/examples/", 1)[0])

from harmony import commands  # noqa: E402

bot = commands.Bot(command_prefix="!")


def log(*args):
    print(*args, flush=True)


@bot.event
async def on_ready():
    log(f"READY: {bot.name} (id={bot.user.id})")


@bot.message("is")
async def てすと(ctx):
    log(f"FIRE is: data={ctx.data!r}")
    await ctx.reply("【is】てすと発火")


@bot.message("start")
async def めも(ctx, text=None):
    log(f"FIRE start: text={text!r} data={ctx.data!r}")
    await ctx.reply(f"【start】めも発火 text={text}")


@bot.message("end")
async def おやすみ(ctx):
    log(f"FIRE end: data={ctx.data!r}")
    await ctx.reply("【end】おやすみ発火")


if __name__ == "__main__":
    token = sys.stdin.readline().strip()
    if not token:
        print("ERROR: no token", flush=True)
        sys.exit(2)
    bot.run(token)
