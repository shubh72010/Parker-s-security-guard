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

# --- PORT HANDLING ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.read()
                    return Image.open(io.BytesIO(data))
    except:
        pass
    return None

def is_spam(image_obj):
    try:
        if image_obj.mode != 'RGB':
            image_obj = image_obj.convert('RGB')
        target_hash = imagehash.phash(image_obj)
        for spam_hash in known_spam_hashes:
            if (target_hash - spam_hash) <= SIMILARITY_THRESHOLD:
                return True
    except Exception as e:
        print(f"Hashing error: {e}")
    return False

def extract_urls_from_object(message_obj):
    """
    Helper function to extract image URLs from any message-like object.
    Works for: Message, MessageSnapshot, and Referenced Message.
    """
    urls = []
    
    # 1. Attachments
    if hasattr(message_obj, 'attachments') and message_obj.attachments:
        for a in message_obj.attachments:
            if a.content_type and a.content_type.startswith('image'):
                urls.append(a.url)

    # 2. Embeds
    if hasattr(message_obj, 'embeds') and message_obj.embeds:
        for e in message_obj.embeds:
            if e.image: urls.append(e.image.url)
            elif e.thumbnail: urls.append(e.thumbnail.url)

    # 3. Content Links (Regex)
    # Note: message_obj.content might be empty or None in some snapshots
    content = getattr(message_obj, 'content', '')
    if content:
        raw_urls = re.findall(r'(https?://\S+)', content)
        for url in raw_urls:
            clean_url = url.split('?')[0].lower()
            if clean_url.endswith(IMAGE_EXTENSIONS):
                urls.append(url)
                
    return urls

async def scan_message(message):
    image_urls = []

    # A. Check CURRENT message
    image_urls.extend(extract_urls_from_object(message))

    # B. Check SNAPSHOTS (The new "Forward" feature)
    # Snapshots are included in the message payload, so they are fast.
    if hasattr(message, 'snapshots') and message.snapshots:
        for snapshot in message.snapshots:
            image_urls.extend(extract_urls_from_object(snapshot))

    # C. Check REFERENCE (Replies / Old Forwards)
    # We must resolve and fetch the original message object.
    if message.reference and message.reference.message_id:
        try:
            # Try to get from cache first (Instant)
            ref_msg = message.reference.cached_message
            
            if not ref_msg:
                # If not in cache, fetch from API (Slower, but necessary)
                # We need the channel object to fetch the message
                ref_channel = client.get_channel(message.reference.channel_id)
                if ref_channel:
                    ref_msg = await ref_channel.fetch_message(message.reference.message_id)

            if ref_msg:
                image_urls.extend(extract_urls_from_object(ref_msg))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # If original message was deleted or we can't see it, ignore.
            pass

    # --- PROCESSING ---
    if not image_urls:
        return

    # Use a set to avoid checking the same URL twice (e.g. link + embed)
    unique_urls = set(image_urls)
    message_flagged = False

    for url in unique_urls:
        if message_flagged: break
        
        img = await get_image_from_url(url)
        if img:
            is_match = await asyncio.to_thread(is_spam, img)
            if is_match:
                message_flagged = True

    if message_flagged:
        try:
            await message.delete()
            print(f"ACTION: Deleted spam (Forward/Reply included) from {message.author}")
        except:
            print(f"ERROR: Cannot delete message in {message.channel}")

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
    if after.author == client.user:
        return
    await scan_message(after)

# --- RUN ---
if __name__ == '__main__':
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        client.run(token)
    else:
        print("Error: No DISCORD_BOT_TOKEN found.")
        
