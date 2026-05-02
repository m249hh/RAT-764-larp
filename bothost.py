import os
import asyncio
from aiohttp import web
import discord
from discord.ext import commands

TOKEN = os.environ["DISCORD_TOKEN"]
PREFIX = os.getenv("BOT_PREFIX", "!")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"ENI online 💜 {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send(f"pong! {round(bot.latency*1000)}ms")

# Web server for Render health checks
async def health(request):
    return web.Response(text="ENI is alive 💜")

app = web.Application()
app.router.add_get("/health", health)

async def run_web():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()

async def main():
    await asyncio.gather(run_web(), bot.start(TOKEN))

if __name__ == "__main__":
    asyncio.run(main())
