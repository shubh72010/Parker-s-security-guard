# scam image scan engine v7
import discord
import os
import io
import aiohttp 
import imagehash
import base64
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
GIF_FRAME_LIMIT = 8    
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# --- GITHUB CONFIGURATION ---
# Ensure these are set in your environment variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") 
GITHUB_REPO = os.getenv("GITHUB_REPO")   # Format: "Username/RepoName"
GITHUB_BRANCH = "main"                   # or "master"

# --- WEB SERVER (HEALTH CHECKS) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self): 
        self.send_response(200)
        self.end_headers()
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active: Hardcore Pro Mode - GitHub Sync Enabled")
    def log_message(self, format, *args): 
        return

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('', port), HealthCheckHandler)
    server.serve_forever()

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

def generate_entry(img, filename):
    """Generates a full hash entry for an image."""
    img = img.convert('RGB')
    return {
        'name': filename,
        'phash': imagehash.phash(img),
        'dhash': imagehash.dhash(img),
        'ahash': imagehash.average_hash(img),
        'grid': get_grid_hashes(img)
    }

def load_spam_hashes():
    global spam_database
    new_db = []
    if not os.path.exists(SPAM_IMAGE_FOLDER): 
        os.makedirs(SPAM_IMAGE_FOLDER)
    for filename in os.listdir(SPAM_IMAGE_FOLDER):
        try:
            with Image.open(os.path.join(SPAM_IMAGE_FOLDER, filename)) as img:
                new_db.append(generate_entry(img, filename))
        except: 
            continue
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
                votes = sum([
                    (t_ph - spam['phash']) <= THRESHOLD,
                    (t_dh - spam['dhash']) <= THRESHOLD,
                    (t_ah - spam['ahash']) <= THRESHOLD
                ])
                if votes >= MATCH_VOTES_REQUIRED: 
                    return f"Voter Match ({votes}/3) @ {angle}°"

                grid_matches = sum(1 for i in range(9) if (t_grid[i] - spam['grid'][i]) <= THRESHOLD)
                if grid_matches >= GRID_MATCH_MIN: 
                    return f"Grid Match ({grid_matches}/9) @ {angle}°"
    return None

async def upload_to_github(filename, file_bytes):
    """Uploads file bytes directly to the GitHub repository."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("❌ Error: GITHUB_TOKEN or GITHUB_REPO not set in environment.")
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SPAM_IMAGE_FOLDER}{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    content_b64 = base64.b64encode(file_bytes).decode('utf-8')
    data = {
        "message": f"Auto-upload scam signature: {filename}",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=data) as resp:
            if resp.status in [200, 201]:
                return True
            else:
                error_log = await resp.text()
                print(f"❌ GitHub API Error: {resp.status} - {error_log}")
                return False

# --- COMMANDS ---

@client.command(name="DBUpdate")
@commands.has_permissions(administrator=True)
async def db_update(ctx):
    if not ctx.message.attachments: 
        return await ctx.send("❌ No attachments found.")

    added, dups, fails = 0, 0, 0
    status = await ctx.send("⏳ Processing & Syncing with GitHub...")

    for attachment in ctx.message.attachments:
        if not attachment.filename.lower().endswith(IMAGE_EXTENSIONS):
            fails += 1
            continue
        try:
            img_bytes = await attachment.read()
            img = Image.open(io.BytesIO(img_bytes)).convert('RGB')

            # Duplicate Check
            is_dup = await asyncio.to_thread(check_similarity, img)
            if is_dup:
                dups += 1
                continue

            # Naming
            fname = f"{attachment.id}_{attachment.filename}"
            
            # Push to GitHub
            success = await upload_to_github(fname, img_bytes)
            
            if success:
                # Save locally for immediate cache
                local_path = os.path.join(SPAM_IMAGE_FOLDER, fname)
                with open(local_path, "wb") as f:
                    f.write(img_bytes)
                
                # Update memory
                spam_database.append(generate_entry(img, fname))
                added += 1
            else:
                fails += 1
        except Exception as e:
            print(f"Process Error: {e}")
            fails += 1

    await status.edit(content=f"**GitHub Sync Results**\n✅ Uploaded: {added}\n⚠️ Duplicates: {dups}\n❌ Failed: {fails}")

# --- MESSAGE SCANNING ---

async def scan(message):
    urls = [a.url for a in message.attachments if a.content_type and 'image' in a.content_type]
    for e in message.embeds:
        if e.image: urls.append(e.image.url)
        elif e.thumbnail: urls.append(e.thumbnail.url)
    
    links = re.findall(r'(https?://\S+)', message.content or "")
    urls.extend([l for l in links if l.split('?')[0].lower().endswith(IMAGE_EXTENSIONS)])

    if message.reference and message.reference.message_id:
        try:
            ref = message.reference.cached_message or await message.channel.fetch_message(message.reference.message_id)
            urls.extend([a.url for a in ref.attachments])
        except: pass

    for url in set(urls):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        img_data = await resp.read()
                        img = Image.open(io.BytesIO(img_data))
                        reason = await asyncio.to_thread(check_similarity, img)
                        if reason:
                            await message.delete()
                            print(f"[KILL] {message.author} | {reason}")
                            return
            except: 
                continue

@client.event
async def on_ready():
    load_spam_hashes()
    print(f"BOT ONLINE: {client.user}")

@client.event
async def on_message(m):
    if m.author == client.user: 
        return
    await client.process_commands(m)
    await scan(m)

if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    client.run(os.getenv('DISCORD_BOT_TOKEN'))
    
