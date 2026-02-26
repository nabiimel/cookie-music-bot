# Discord Music Bot Backend (Python)

A simple backend Discord music bot built with `discord.py` voice support + `yt-dlp` streaming.

## Features

- Join voice channels
- Queue music by URL or search terms
- Playback queue and auto-play next track
- Skip current track
- Show queue
- Stop playback and disconnect

## Requirements

- Python 3.10+
- `ffmpeg` installed and available on your PATH

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy env template:
   ```bash
   cp .env.example .env
   ```
4. Edit `.env` and set your bot token:
   ```env
   DISCORD_TOKEN=
   COMMAND_PREFIX=!
   ```

> The token is intentionally blank by default as requested.

## Run

```bash
python bot.py
```

## Commands

- `!join` — join your current voice channel
- `!play <url or search query>` — queue and play audio
- `!queue` — show now playing + queued tracks
- `!skip` — skip current track
- `!stop` — clear queue and disconnect

## Discord Developer Portal Checklist

- Create an application + bot user
- Enable **MESSAGE CONTENT INTENT** for the bot
- Invite bot with `bot` scope and voice permissions
