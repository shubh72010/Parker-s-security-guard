import discord
import os
import io
import requests
import imagehash
from PIL import Image
from discord.ext import commands
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
SPAM_IMAGE_FOLDER = 'chex/'
SIMILARITY_THRESHOLD = 10
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# --- PORT HANDLING (FOR RENDER/HOSTING) ---

class HealthCheckHandler(BaseHTTPRequestHandler):
    """A simple handler to respond to health checks on the open port."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        # Overriding to prevent console spam from health check logs
        return

def run_web_server():
    """Starts a server on the port provided by the host (default 8080)."""
    # Render and other hosts provide the 'PORT' environment variable
    port = int(os.environ.get("PORT", 8080))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"--- Web server started on port {port} ---")
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

def get_image_from_url(url):
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except:
        return None

def is_spam(image_obj):
    try:
        target_hash = imagehash.phash(image_obj)
        for spam_hash in known_spam_hashes:
            if (target_hash - spam_hash) <= SIMILARITY_THRESHOLD:
                return True
    except:
        pass
    return False

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    load_spam_hashes()

@client.event
async def on_message(message):
    if message.author == client.user:
        return

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
        if url.split('?')[0].lower().endswith(IMAGE_EXTENSIONS):
            image_urls.append(url)

    for url in image_urls:
        img = get_image_from_url(url)
        if img and is_spam(img):
            try:
                await message.delete()
                print(f"Deleted spam from {message.author}")
                break 
            except:
                print("Failed to delete message (check permissions).")

# --- RUN ---
if __name__ == '__main__':
    # 1. Start the web server in a separate thread so it doesn't block the bot
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # 2. Run the bot
    token = os.getenv('DISCORD_BOT_TOKEN')
    if token:
        client.run(token)
    else:
        print("Error: No DISCORD_BOT_TOKEN found.")

# meow meow 🐈 
