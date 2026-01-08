# TUTORIAL

---

How the bot Was Set Up

1. Create the GitHub Repository

Create a new GitHub repository containing only the essentials:

Repository structure

• bot.py → main Discord bot file

• requirements.txt → Python dependencies


---

2. Register the Bot on Discord

1. Go to https://discord.dev


2. Create a new application


3. Open Bot → create a bot


4. Copy the Bot Token

5. Enable only the required intents


---

3. Deploy on Render (Free Tier)

1. Go to https://render.com


2. Create a New Web Service


3. Connect the GitHub repository


4. Configure:

Runtime: Python3

Build command:
pip install -r requirements.txt

Start command:
python bot.py



5. Add an Environment Variable:

Key: DISCORD_BOT_TOKEN

Value: (the bot token)

Deploy the service.

Render will build the environment using requirements.txt and start the bot.


---

4. Invite the Bot to the Server

1. In Discord Developer Portal


2. Select:

Scope: bot



3. Select only required permissions (typically:

Read Messages

Manage Messages)

4. Invite the bot to the server

---

5. Prevent Render Free Tier Sleep

Render’s free tier sleeps after inactivity.

To keep the bot online:

1. Go to https://uptimerobot.com


2. Create a new monitor:

Type: HTTP(s)

URL: your Render service URL



3. Set interval to 5 minutes



This keeps the service alive without paid hosting.


---
