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

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def get_latest_video_id():
    try:
        resp = requests.get(RSS_URL, headers=HEADERS, timeout=10)
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


def get_video_status(video_id):
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
            return {"status": "none"}
        item = items[0]
        snippet = item.get("snippet", {})
        live = item.get("liveStreamingDetails", {})
        broadcast = snippet.get("liveBroadcastContent", "none")

        if broadcast == "live" and live.get("actualStartTime") and not live.get("actualEndTime"):
            return {
                "status": "live",
                "title": snippet.get("title", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}"
            }
        elif broadcast == "upcoming":
            return {"status": "upcoming"}
        else:
            return {"status": "none"}
    except Exception as e:
        print(f"[API] Error: {e}", flush=True)
    return None


async def send_notification(channel, result, video_id):
    """Attempt to send the notification, retrying up to 5 times on rate limit."""
    embed = discord.Embed(
        title=result["title"],
        url=result["url"],
        description="🔴 We're live on YouTube! Come watch!",
        color=0xFF0000
    )
    embed.set_image(url=result["thumbnail"])
    embed.set_footer(text="Click the title to watch!")

    for attempt in range(5):
        try:
            await channel.send(content="@everyone", embed=embed)
            print(f"[Bot] Notification sent for {video_id}!", flush=True)
            return True
        except discord.HTTPException as e:
            wait = 30 * (attempt + 1)
            print(f"[Bot] Send failed (attempt {attempt + 1}/5): {e.status} — retrying in {wait}s...", flush=True)
            await asyncio.sleep(wait)
        except Exception as e:
            wait = 30 * (attempt + 1)
            print(f"[Bot] Send error (attempt {attempt + 1}/5): {e} — retrying in {wait}s...", flush=True)
            await asyncio.sleep(wait)

    print(f"[Bot] All send attempts failed for {video_id}.", flush=True)
    return False


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

            if video_id is None:
                print("[Bot] RSS failed, retrying in 30s...", flush=True)
                await asyncio.sleep(30)
                video_id = get_latest_video_id()

            print(f"[Bot] Latest: {video_id} | Last seen: {last_seen_video_id}", flush=True)

            if video_id and video_id != last_seen_video_id:
                result = get_video_status(video_id)
                print(f"[Bot] Video {video_id} status: {result}", flush=True)

                if result is None:
                    print("[Bot] API error, will retry next cycle.", flush=True)
                elif result["status"] == "live":
                    sent = await send_notification(channel, result, video_id)
                    if sent:
                        last_seen_video_id = video_id
                elif result["status"] == "upcoming":
                    print(f"[Bot] {video_id} is upcoming, will keep checking.", flush=True)
                else:
                    print(f"[Bot] {video_id} is a regular video, skipping.", flush=True)
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
