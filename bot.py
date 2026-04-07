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
RSS_CHECK_INTERVAL = 300  # check RSS every 5 min (free, no quota)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

already_notified_id = None  # track by video ID so restarts don't double-notify
check_live_task = None


def get_latest_video_id():
    """Fetch the most recent video ID from the RSS feed. Free, no API quota."""
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
        print(f"Error fetching RSS: {e}")
    return None


def is_video_live(video_id):
    """
    Check if a specific video is currently live.
    Uses videos.list which costs only 1 API unit (vs 100 for search.list).
    """
    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,liveStreamingDetails",
            "id": video_id,
            "key": YOUTUBE_API_KEY
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {})
        live_details = item.get("liveStreamingDetails", {})

        # Must be a live broadcast that has started but not ended
        if snippet.get("liveBroadcastContent") != "live":
            return None
        if not live_details.get("actualStartTime"):
            return None
        if live_details.get("actualEndTime"):
            return None  # already ended

        title = snippet.get("title", "")
        thumbnail = snippet.get("thumbnails", {}).get("high", {}).get("url", "")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        return {"title": title, "thumbnail": thumbnail, "url": video_url}
    except Exception as e:
        print(f"Error checking video live status: {e}")
    return None


async def check_live():
    global already_notified_id
    print("check_live loop starting...")

    # On startup, record the latest video ID so we don't re-notify for it
    latest = get_latest_video_id()
    if latest:
        live_info = is_video_live(latest)
        if live_info:
            print(f"Already live on startup ({latest}), skipping notification.")
            already_notified_id = latest
        else:
            print(f"Latest video on startup: {latest} (not live)")
            already_notified_id = latest  # don't notify for pre-existing videos either

    while True:
        try:
            channel = client.get_channel(CHANNEL_ID)
            if channel is None:
                print(f"Channel {CHANNEL_ID} not in cache yet, retrying in 10s...")
                await asyncio.sleep(10)
                continue

            video_id = get_latest_video_id()
            print(f"RSS latest video: {video_id} | Last notified: {already_notified_id}")

            if video_id and video_id != already_notified_id:
                # New video appeared — check if it's a live stream (costs 1 API unit)
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
                    already_notified_id = video_id
                    print(f"Notification sent for {video_id}!")
                else:
                    print(f"New video {video_id} is not a live stream, skipping.")
                    already_notified_id = video_id  # still update so we don't recheck it

        except Exception as e:
            print(f"Error in check_live loop: {e}")

        await asyncio.sleep(RSS_CHECK_INTERVAL)


async def watchdog():
    global check_live_task
    await client.wait_until_ready()
    print("Watchdog started.")

    while True:
        if check_live_task is None or check_live_task.done():
            if check_live_task is not None and check_live_task.done():
                exc = check_live_task.exception() if not check_live_task.cancelled() else None
                if exc:
                    print(f"Watchdog: check_live task died with exception: {exc}, restarting...")
                else:
                    print("Watchdog: check_live task ended unexpectedly, restarting...")
            else:
                print("Watchdog: starting check_live loop for the first time...")
            check_live_task = asyncio.create_task(check_live())

        await asyncio.sleep(60)
        print(f"Watchdog: alive | task running: {not check_live_task.done()}")


@client.event
async def on_ready():
    print(f"Bot is online as {client.user}")
    asyncio.create_task(watchdog())


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
