import discord
import requests
import asyncio
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
YOUTUBE_API_KEY = os.environ['YOUTUBE_API_KEY']
YOUTUBE_CHANNEL_ID = os.environ['YOUTUBE_CHANNEL_ID']

CHECK_INTERVAL = 60

intents = discord.Intents.default()
client = discord.Client(intents=intents)

already_notified = False
loop_started = False

def get_live_info():
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "channelId": YOUTUBE_CHANNEL_ID,
        "type": "video",
        "eventType": "live",
        "key": YOUTUBE_API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        items = data.get("items", [])
        print(f"Live check: {len(items)} stream(s) found")
        if items:
            item = items[0]
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            thumbnail = item["snippet"]["thumbnails"]["high"]["url"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return {"title": title, "thumbnail": thumbnail, "url": video_url}
    except Exception as e:
        print(f"Error checking live status: {e}")
    return None

async def check_live():
    global already_notified
    channel = client.get_channel(CHANNEL_ID)
    print(f"Discord channel found: {channel}")

    startup_check = get_live_info()
    if startup_check:
        print("Was already live on startup, skipping notification.")
        already_notified = True

    while True:
        try:
            info = get_live_info()
            print(f"Is live: {info is not None} | Already notified: {already_notified}")
            if info and not already_notified:
                embed = discord.Embed(
                    title=info["title"],
                    url=info["url"],
                    description="🔴 We're live on YouTube! Come watch!",
                    color=0xFF0000
                )
                embed.set_image(url=info["thumbnail"])
                embed.set_footer(text="Click the title to watch!")
                await channel.send(content="@everyone", embed=embed)
                already_notified = True
            elif not info:
                if already_notified:
                    print("Stream ended, cooling down...")
                    await asyncio.sleep(300)
                already_notified = False
        except Exception as e:
            print(f"Error in check_live loop: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

async def watchdog():
    await client.wait_until_ready()
    global loop_started
    while True:
        if not loop_started:
            print("Watchdog: starting check_live loop...")
            loop_started = True
            client.loop.create_task(check_live())
        await asyncio.sleep(300)
        print("Watchdog: still alive")

@client.event
async def on_ready():
    print(f"Bot is online as {client.user}")
    client.loop.create_task(watchdog())

@client.event
async def on_disconnect():
    print("Bot disconnected, attempting to reconnect...")

@client.event
async def on_resumed():
    print("Bot reconnected successfully!")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running")
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()
client.run(DISCORD_TOKEN, reconnect=True)
