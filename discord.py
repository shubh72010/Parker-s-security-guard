import discord
import os
import io
import requests
import imagehash
from PIL import Image
from discord.ext import commands
import re

# --- CONFIGURATION ---

# The directory containing known spam images.
SPAM_IMAGE_FOLDER = 'chex/'

# The threshold for Hamming distance. 
# Lower number = stricter match (0 is exact duplicate).
# Higher number = looser match (allows for slight edits, compression artifacts).
# 10 is generally a good balance for pHash.
SIMILARITY_THRESHOLD = 10

# Supported image extensions to look for in raw links.
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')

# --- BOT SETUP ---

# We need the 'message_content' intent to read message text (for links)
# and 'guilds'/'messages' to manage message deletion.
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

# Initialize the Client
client = discord.Client(intents=intents)

# In-memory storage for the hashes of known spam images
known_spam_hashes = []

def load_spam_hashes():
    """
    Loads images from the SPAM_IMAGE_FOLDER, computes their pHash,
    and stores them in the global known_spam_hashes list.
    """
    if not os.path.exists(SPAM_IMAGE_FOLDER):
        print(f"Warning: Folder '{SPAM_IMAGE_FOLDER}' not found. Creating it...")
        os.makedirs(SPAM_IMAGE_FOLDER)
        return

    print(f"--- Loading spam images from '{SPAM_IMAGE_FOLDER}' ---")
    
    count = 0
    for filename in os.listdir(SPAM_IMAGE_FOLDER):
        filepath = os.path.join(SPAM_IMAGE_FOLDER, filename)
        
        # specific check to try and open valid image files only
        try:
            with Image.open(filepath) as img:
                # Compute average hash (aHash) or perceptual hash (pHash). 
                # pHash is generally more robust against minor modifications.
                h = imagehash.phash(img)
                known_spam_hashes.append(h)
                count += 1
                print(f"Loaded: {filename} | Hash: {h}")
        except Exception as e:
            # Skip non-image files or errors
            continue
            
    print(f"--- Load Complete. {count} spam hashes stored in memory. ---")

def get_image_from_url(url):
    """
    Downloads an image from a URL and returns a PIL Image object.
    Returns None if download fails or content is not an image.
    """
    try:
        # Timeout is important to prevent hanging on bad links
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        # Convert bytes to a PIL Image
        image_bytes = io.BytesIO(response.content)
        return Image.open(image_bytes)
    except Exception as e:
        print(f"Failed to process URL {url}: {e}")
        return None

def is_spam(image_obj):
    """
    Computes the hash of the given PIL Image object and compares it
    against all stored known spam hashes.
    
    Returns: True if a match is found within the threshold, else False.
    """
    try:
        target_hash = imagehash.phash(image_obj)
        
        for spam_hash in known_spam_hashes:
            # ImageHash objects support subtraction to calculate Hamming distance
            distance = target_hash - spam_hash
            
            if distance <= SIMILARITY_THRESHOLD:
                print(f"Match Found! Distance: {distance} (Threshold: {SIMILARITY_THRESHOLD})")
                return True
    except Exception as e:
        print(f"Error during hashing/comparison: {e}")
        
    return False

@client.event
async def on_ready():
    """
    Triggered when the bot successfully connects to Discord.
    """
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    load_spam_hashes()
    print("Bot is ready and listening for images.")

@client.event
async def on_message(message):
    """
    Triggered on every message sent in servers visible to the bot.
    """
    # Don't let the bot check its own messages
    if message.author == client.user:
        return

    # 1. Collect all potential image URLs from the message
    image_urls = []

    # A. Check Attachments (Direct file uploads)
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image'):
                image_urls.append(attachment.url)

    # B. Check Embeds (e.g., Image links that Discord has already processed)
    # Note: Sometimes embeds appear slightly after the message is sent. 
    # For a robust production bot, one might also listen to 'on_message_edit'.
    if message.embeds:
        for embed in message.embeds:
            if embed.image:
                image_urls.append(embed.image.url)
            if embed.thumbnail:
                image_urls.append(embed.thumbnail.url)

    # C. Check Raw Links in Content (That Discord auto-embeds)
    # We use regex to find http/https links ending in image extensions
    # This covers cases where the Embed object hasn't been created yet.
    urls_in_content = re.findall(r'(https?://\S+)', message.content)
    for url in urls_in_content:
        # Clean query parameters for extension checking
        clean_url = url.split('?')[0].lower()
        if clean_url.endswith(IMAGE_EXTENSIONS):
            image_urls.append(url)

    # If no images found, we are done
    if not image_urls:
        return

    # 2. Process collected URLs
    message_flagged = False
    
    for url in image_urls:
        if message_flagged: 
            break # Optimization: If one image in the message is spam, delete the whole message.

        downloaded_img = get_image_from_url(url)
        
        if downloaded_img:
            if is_spam(downloaded_img):
                message_flagged = True

    # 3. Take Action
    if message_flagged:
        try:
            await message.delete()
            print(f"ACTION: Deleted message from {message.author} in #{message.channel}. Reason: Image Spam detected.")
        except discord.Forbidden:
            print(f"ERROR: Missing permissions to delete message in #{message.channel}.")
        except discord.NotFound:
            print("ERROR: Message was already deleted.")

# --- RUN ---
if __name__ == '__main__':
    # Retrieve token from environment variable for security
    token = os.getenv('DISCORD_BOT_TOKEN')
    
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable is not set.")
    else:
        client.run(token)
      
