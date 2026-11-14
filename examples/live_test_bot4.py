"""実サーバーテスト第4弾: @bot.message("in") と command 優先の検証 (てすたー専用)。

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


@bot.command()
async def めも(ctx, text=None):
    log(f"FIRE command: text={text!r}")
    await ctx.reply(f"【command】めも text={text}")


@bot.message("start", name="めも")
async def めも_message(ctx, text=None):
    log(f"FIRE message-start: text={text!r}")
    await ctx.reply(f"【message】めも text={text}")


@bot.message("in")
async def ほげ(ctx):
    log(f"FIRE in: data={ctx.data!r}")
    await ctx.reply("【in】ほげ発火")


if __name__ == "__main__":
    token = sys.stdin.readline().strip()
    if not token:
        print("ERROR: no token", flush=True)
        sys.exit(2)
    bot.run(token)
