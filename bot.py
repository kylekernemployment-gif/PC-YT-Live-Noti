import discord
import requests
import asyncio
import os
import threading
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler

DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
CHANNEL_ID = int(os.environ['CHANNEL_ID'])
YOUTUBE_API_KEY = os.environ['YOUTUBE_API_KEY']
YOUTUBE_CHANNEL_ID = os.environ['YOUTUBE_CHANNEL_ID']

RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
CHECK_INTERVAL = 300  # 5 minutes

intents = discord.Intents.default()
client = discord.Client(intents=intents)

last_seen_video_id = None
check_live_task = None


def get_latest_video_id():
    try:
        resp = requests.get(RSS_URL, timeout=10)
        root = ET.fromstring(resp.content)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
        }
        entry = root.find('atom:entry', ns)
        if entry is not None:
            video_id = entry.find('yt:videoId', ns)
            if video_id is not None:
                return video_id.text
    except Exception as e:
        print(f"[RSS] Error: {e}", flush=True)
    return None


def is_video_live(video_id):
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,liveStreamingDetails",
                "id": video_id,
                "key": YOUTUBE_API_KEY
            },
            timeout=10
        )
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {})
        live = item.get("liveStreamingDetails", {})

        if snippet.get("liveBroadcastContent") != "live":
            return None
        if not live.get("actualStartTime"):
            return None
        if live.get("actualEndTime"):
            return None

        return {
            "title": snippet.get("title", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}"
        }
    except Exception as e:
        print(f"[API] Error: {e}", flush=True)
    return None


async def check_live():
    global last_seen_video_id
    print("[Bot] check_live loop starting...", flush=True)

    last_seen_video_id = get_latest_video_id()
    print(f"[Bot] Startup latest video ID: {last_seen_video_id}", flush=True)

    while True:
        try:
            channel = client.get_channel(CHANNEL_ID)
            if channel is None:
                print("[Bot] Channel not in cache, retrying in 10s...", flush=True)
                await asyncio.sleep(10)
                continue

            video_id = get_latest_video_id()
            print(f"[Bot] Latest: {video_id} | Last seen: {last_seen_video_id}", flush=True)

            if video_id and video_id != last_seen_video_id:
                info = is_video_live(video_id)
                if info:
                    embed = discord.Embed(
                        title=info["title"],
                        url=info["url"],
                        description="🔴 We're live on YouTube! Come watch!",
                        color=0xFF0000
                    )
                    embed.set_image(url=info["thumbnail"])
                    embed.set_footer(text="Click the title to watch!")
                    await channel.send(content="@everyone", embed=embed)
                    print(f"[Bot] Notification sent for {video_id}!", flush=True)
                else:
                    print(f"[Bot] {video_id} is not live, skipping.", flush=True)
                last_seen_video_id = video_id

        except Exception as e:
            print(f"[Bot] Error in loop: {e}", flush=True)

        await asyncio.sleep(CHECK_INTERVAL)


async def watchdog():
    global check_live_task
    await client.wait_until_ready()
    print("[Watchdog] Started.", flush=True)

    while True:
        if check_live_task is None or check_live_task.done():
            if check_live_task is not None:
                exc = check_live_task.exception() if not check_live_task.cancelled() else None
                print(f"[Watchdog] Task died ({exc}), restarting...", flush=True)
            else:
                print("[Watchdog] Starting check_live task...", flush=True)
            check_live_task = asyncio.create_task(check_live())

        await asyncio.sleep(60)
        print(f"[Watchdog] Alive. Task running: {not check_live_task.done()}", flush=True)


@client.event
async def on_ready():
    print(f"[Bot] Online as {client.user}", flush=True)
    asyncio.create_task(watchdog())


@client.event
async def on_disconnect():
    print("[Bot] Disconnected.", flush=True)


@client.event
async def on_resumed():
    print("[Bot] Reconnected.", flush=True)


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
