# follian scam scan engine v6.2
import discord
import os
import io
import aiohttp 
import imagehash
from PIL import Image, ImageOps, ImageSequence
from discord.ext import commands
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import asyncio

# --- CONFIGURATION ---
SPAM_IMAGE_FOLDER = 'chex/'
THRESHOLD = 10 
MATCH_VOTES_REQUIRED = 2 
GRID_MATCH_MIN = 4      
GIF_FRAME_LIMIT = 8    # Increased for better coverage of longer GIFs
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# --- WEB SERVER (HEALTH CHECKS) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Active: Hardcore Mode")
    def log_message(self, format, *args): return

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('', port), HealthCheckHandler).serve_forever()

# --- THE MODERATION ENGINE ---
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
client = commands.Bot(command_prefix="!", intents=intents)

spam_database = []

def get_grid_hashes(img):
    hashes = []
    img = img.convert('RGB')
    w, h = img.size
    gw, gh = w // 3, h // 3
    for i in range(3):
        for j in range(3):
            box = (j * gw, i * gh, (j + 1) * gw, (i + 1) * gh)
            hashes.append(imagehash.phash(img.crop(box)))
    return hashes

def load_spam_hashes():
    global spam_database
    new_db = []
    if not os.path.exists(SPAM_IMAGE_FOLDER): os.makedirs(SPAM_IMAGE_FOLDER)
    for filename in os.listdir(SPAM_IMAGE_FOLDER):
        try:
            with Image.open(os.path.join(SPAM_IMAGE_FOLDER, filename)) as img:
                img = img.convert('RGB')
                new_db.append({
                    'name': filename,
                    'phash': imagehash.phash(img),
                    'dhash': imagehash.dhash(img),
                    'ahash': imagehash.average_hash(img),
                    'grid': get_grid_hashes(img)
                })
        except: continue
    spam_database = new_db
    print(f"--- Loaded {len(spam_database)} signatures ---")

def check_similarity(target_img):
    frames = []
    if getattr(target_img, "is_animated", False):
        total = getattr(target_img, "n_frames", 1)
        indices = [int(i * (total - 1) / (GIF_FRAME_LIMIT - 1)) for i in range(GIF_FRAME_LIMIT)] if total > 1 else [0]
        for i in set(indices):
            target_img.seek(i)
            frames.append(target_img.convert('RGB'))
    else:
        frames.append(target_img.convert('RGB'))

    for frame in frames:
        # Check original and 3 rotations
        for angle in [0, 90, 180, 270]:
            variant = frame.rotate(angle, expand=True) if angle != 0 else frame
            t_ph = imagehash.phash(variant)
            t_dh = imagehash.dhash(variant)
            t_ah = imagehash.average_hash(variant)
            t_grid = get_grid_hashes(variant)

            for spam in spam_database:
                # 1. Triple-Voter Logic
                votes = sum([
                    (t_ph - spam['phash']) <= THRESHOLD,
                    (t_dh - spam['dhash']) <= THRESHOLD,
                    (t_ah - spam['ahash']) <= THRESHOLD
                ])
                if votes >= MATCH_VOTES_REQUIRED:
                    return f"Voter Match ({votes}/3) at {angle}°"

                # 2. Grid/Crop Logic
                grid_matches = sum(1 for i in range(9) if (t_grid[i] - spam['grid'][i]) <= THRESHOLD)
                if grid_matches >= GRID_MATCH_MIN:
                    return f"Grid Match ({grid_matches}/9) at {angle}°"
    return None

def extract_urls(msg):
    urls = [a.url for a in msg.attachments if a.content_type and 'image' in a.content_type]
    for e in msg.embeds:
        if e.image: urls.append(e.image.url)
        elif e.thumbnail: urls.append(e.thumbnail.url)
    links = re.findall(r'(https?://\S+)', msg.content or "")
    urls.extend([l for l in links if l.split('?')[0].lower().endswith(IMAGE_EXTENSIONS)])
    return list(set(urls))

async def scan(message):
    urls = extract_urls(message)
    
    # Handle snapshots (Forwards)
    if hasattr(message, 'snapshots'):
        for s in message.snapshots: urls.extend(extract_urls(s))
    
    # Handle references (Replies)
    if message.reference and message.reference.message_id:
        try:
            ref = message.reference.cached_message or await message.channel.fetch_message(message.reference.message_id)
            urls.extend(extract_urls(ref))
        except: pass

    for url in set(urls):
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    img = Image.open(io.BytesIO(await resp.read()))
                    reason = await asyncio.to_thread(check_similarity, img)
                    if reason:
                        try:
                            await message.delete()
                            print(f"[KILL] User: {message.author} | Logic: {reason} | File: {url.split('/')[-1]}")
                            return
                        except: pass

@client.event
async def on_ready():
    load_spam_hashes()
    print(f"BOT READY: Listening on {len(client.guilds)} servers.")

@client.event
async def on_message(m):
    if m.author == client.user: return
    await client.process_commands(m)
    await scan(m)

@client.event
async def on_message_edit(b, a):
    if a.author != client.user: await scan(a)

@client.command()
@commands.has_permissions(administrator=True)
async def reload(ctx):
    load_spam_hashes()
    await ctx.send(f"✅ DB Hot-Reloaded: {len(spam_database)} signatures.")

if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    client.run(os.getenv('DISCORD_BOT_TOKEN'))
            
