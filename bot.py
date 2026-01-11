import discord
import os
import io
import aiohttp 
import imagehash
from PIL import Image
from discord.ext import commands
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import asyncio

# --- CONFIGURATION ---
SPAM_IMAGE_FOLDER = 'chex/'
SIMILARITY_THRESHOLD = 10
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# --- PORT HANDLING (FOR RENDER/HOSTING) ---

class HealthCheckHandler(BaseHTTPRequestHandler):
    """
    Handles health checks. 
    Crucial: Includes do_HEAD to prevent 501 errors from UptimeRobot.
    """
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        # Silence console logs for health checks to keep logs clean
        return

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"--- Web server listening on port {port} ---")
    httpd.serve_forever()

# --- BOT SETUP ---

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

client = discord.Client(intents=intents)
known_spam_hashes = []

def load_spam_hashes():
    if not os.path.exists(SPAM_IMAGE_FOLDER):
        os.makedirs(SPAM_IMAGE_FOLDER)
        return

    print(f"--- Loading spam images from '{SPAM_IMAGE_FOLDER}' ---")
    count = 0
    for filename in os.listdir(SPAM_IMAGE_FOLDER):
        filepath = os.path.join(SPAM_IMAGE_FOLDER, filename)
        try:
            with Image.open(filepath) as img:
                h = imagehash.phash(img)
                known_spam_hashes.append(h)
                count += 1
        except:
            continue
    print(f"--- Load Complete. {count} spam hashes stored. ---")

async def get_image_from_url(url):
    """
    Asynchronously downloads an image. 
    Using aiohttp prevents the bot from 'freezing' while downloading.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.read()
                    return Image.open(io.BytesIO(data))
    except Exception as e:
        # Expected errors: 404s, timeouts, non-image links
        pass
    return None

def is_spam(image_obj):
    try:
        # Convert to RGB to avoid errors with transparent PNGs/GIFs during hashing
        if image_obj.mode != 'RGB':
            image_obj = image_obj.convert('RGB')
            
        target_hash = imagehash.phash(image_obj)
        for spam_hash in known_spam_hashes:
            if (target_hash - spam_hash) <= SIMILARITY_THRESHOLD:
                return True
    except Exception as e:
        print(f"Hashing error: {e}")
    return False

async def scan_message(message):
    """
    Scans a message for spam images. Logic separated so we can 
    call it on both 'on_message' and 'on_message_edit'.
    """
    # 1. Collect URLs
    image_urls = []
    
    if message.attachments:
        for a in message.attachments:
            if a.content_type and a.content_type.startswith('image'):
                image_urls.append(a.url)

    if message.embeds:
        for e in message.embeds:
            if e.image: image_urls.append(e.image.url)
            elif e.thumbnail: image_urls.append(e.thumbnail.url)

    raw_urls = re.findall(r'(https?://\S+)', message.content)
    for url in raw_urls:
        clean_url = url.split('?')[0].lower()
        if clean_url.endswith(IMAGE_EXTENSIONS):
            image_urls.append(url)

    # 2. Check URLs
    if not image_urls:
        return

    message_flagged = False
    for url in image_urls:
        if message_flagged: break

        img = await get_image_from_url(url)
        if img:
            # Hash calculation is CPU bound, running it in executor keeps bot responsive
            is_match = await asyncio.to_thread(is_spam, img)
            if is_match:
                message_flagged = True

    # 3. Delete if flagged
    if message_flagged:
        try:
            await message.delete()
            print(f"ACTION: Deleted spam from {message.author}")
        except discord.NotFound:
            pass # Already deleted
        except discord.Forbidden:
            print(f"ERROR: Cannot delete message in {message.channel.name}")

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    load_spam_hashes()

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    await scan_message(message)

@client.event
async def on_message_edit(before, after):
    """
    Catches images that appear late (like link previews/embeds) 
    that weren't there when the message was first sent.
    """
    if after.author == client.user:
        return
    await scan_message(after)

# --- RUN ---
if __name__ == '__main__':
    # Start web server thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        client.run(token)
    else:
        print("Error: No DISCORD_BOT_TOKEN found.")
        
