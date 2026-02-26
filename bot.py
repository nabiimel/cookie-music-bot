import asyncio
import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("musicbot")


@dataclass
class Track:
    title: str
    stream_url: str
    webpage_url: str
    requested_by: str


class GuildMusicState:
    def __init__(self) -> None:
        self.queue: Deque[Track] = deque()
        self.current: Optional[Track] = None
        self.lock = asyncio.Lock()


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot, ytdl_opts: dict) -> None:
        self.bot = bot
        self.ytdl = YoutubeDL(ytdl_opts)
        self.guild_states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = GuildMusicState()
        return self.guild_states[guild_id]

    async def ensure_voice(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return None

        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("Join a voice channel first.")
            return None

        voice_client = ctx.guild.voice_client
        if voice_client is None:
            voice_client = await ctx.author.voice.channel.connect()
        elif voice_client.channel != ctx.author.voice.channel:
            await voice_client.move_to(ctx.author.voice.channel)

        return voice_client

    async def extract_track(self, query: str, requested_by: str) -> Optional[Track]:
        loop = asyncio.get_running_loop()

        def _extract() -> dict:
            return self.ytdl.extract_info(query, download=False)

        try:
            info = await loop.run_in_executor(None, _extract)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to extract track: %s", exc)
            return None

        if "entries" in info:
            entries = [entry for entry in info["entries"] if entry]
            if not entries:
                return None
            info = entries[0]

        url = info.get("url")
        title = info.get("title") or "Unknown title"
        webpage_url = info.get("webpage_url") or query

        if not url:
            return None

        return Track(title=title, stream_url=url, webpage_url=webpage_url, requested_by=requested_by)

    async def play_next(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            return

        state = self.get_state(ctx.guild.id)
        voice_client = ctx.guild.voice_client
        if voice_client is None:
            return

        async with state.lock:
            if not state.queue:
                state.current = None
                await ctx.send("Queue is empty.")
                return

            track = state.queue.popleft()
            state.current = track

        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn",
        }

        source = discord.FFmpegPCMAudio(track.stream_url, **ffmpeg_options)

        def _after_play(error: Optional[Exception]) -> None:
            if error:
                logger.error("Playback error: %s", error)
            fut = asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to play next track: %s", exc)

        voice_client.play(source, after=_after_play)
        await ctx.send(f"Now playing: **{track.title}** (requested by {track.requested_by})")

    @commands.command(name="join")
    async def join(self, ctx: commands.Context) -> None:
        voice_client = await self.ensure_voice(ctx)
        if voice_client:
            await ctx.send(f"Connected to **{voice_client.channel.name}**.")

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        voice_client = await self.ensure_voice(ctx)
        if voice_client is None or ctx.guild is None:
            return

        track = await self.extract_track(query, str(ctx.author))
        if track is None:
            await ctx.send("Could not load track. Try a different URL/search query.")
            return

        state = self.get_state(ctx.guild.id)
        async with state.lock:
            state.queue.append(track)
            should_start = not voice_client.is_playing() and state.current is None

        await ctx.send(f"Queued: **{track.title}**")

        if should_start:
            await self.play_next(ctx)

    @commands.command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.guild.voice_client is None:
            await ctx.send("Not connected to voice.")
            return

        voice_client = ctx.guild.voice_client
        if not voice_client.is_playing():
            await ctx.send("Nothing is playing.")
            return

        voice_client.stop()
        await ctx.send("Skipped current track.")

    @commands.command(name="queue")
    async def queue(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        state = self.get_state(ctx.guild.id)
        if state.current is None and not state.queue:
            await ctx.send("Queue is empty.")
            return

        lines = []
        if state.current:
            lines.append(f"**Now:** {state.current.title}")
        for idx, track in enumerate(state.queue, start=1):
            lines.append(f"{idx}. {track.title} (by {track.requested_by})")

        await ctx.send("\n".join(lines))

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        if ctx.guild is None or ctx.guild.voice_client is None:
            await ctx.send("Not connected to voice.")
            return

        state = self.get_state(ctx.guild.id)
        async with state.lock:
            state.queue.clear()
            state.current = None

        voice_client = ctx.guild.voice_client
        if voice_client.is_playing():
            voice_client.stop()
        await voice_client.disconnect(force=True)
        await ctx.send("Stopped playback and disconnected.")


class MusicBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        command_prefix = os.getenv("COMMAND_PREFIX", "!")
        super().__init__(command_prefix=command_prefix, intents=intents)

    async def setup_hook(self) -> None:
        ytdl_opts = {
            "format": os.getenv("YTDL_FORMAT", "bestaudio/best"),
            "noplaylist": True,
            "nocheckcertificate": os.getenv("YTDL_NOCHECK_CERTIFICATE", "true").lower() == "true",
            "default_search": "ytsearch",
            "quiet": True,
            "source_address": "0.0.0.0",
        }
        await self.add_cog(MusicCog(self, ytdl_opts))


def build_bot() -> commands.Bot:
    bot = MusicBot()

    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")

    return bot


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set. Fill it in your .env file.")

    bot = build_bot()
    bot.run(token)


if __name__ == "__main__":
    main()
