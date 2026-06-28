"""
Clash of Clans Discord Bot — Main Entry Point
Premium private bot for a single clan.

Render Web Service compatibility:
  Render's free tier requires an HTTP server to pass health checks.
  We spin up a tiny aiohttp server on PORT (default 10000) alongside
  the Discord bot so Render marks the service as healthy.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.db import Database
from utils.coc_api import CoCAPI

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bot")

# ── HTTP health-check server (keeps Render Web Service alive) ─────────────────
_start_time = datetime.now(timezone.utc)

async def handle_health(request: web.Request) -> web.Response:
    uptime = (datetime.now(timezone.utc) - _start_time).seconds
    bot: CoCBot = request.app["bot"]
    status = "online" if bot.is_ready() else "starting"
    return web.json_response({
        "status": status,
        "bot": str(bot.user) if bot.user else None,
        "uptime_seconds": uptime,
    })

async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="🏰 CoC Bot is running!", content_type="text/plain")

async def start_web_server(bot: "CoCBot"):
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/",       handle_root)
    app.router.add_get("/health", handle_health)

    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health-check server listening on port {port}")


# ── Bot Setup ─────────────────────────────────────────────────────────────────
class CoCBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        self.db: Database = None
        self.coc_api: CoCAPI = None

    async def setup_hook(self):
        # Init database
        self.db = Database()
        await self.db.init()

        # Init CoC API wrapper
        self.coc_api = CoCAPI(
            api_key=os.getenv("COC_API_KEY"),
            db=self.db,
        )

        # Load all cogs
        cogs = [
            "cogs.setup",
            "cogs.profile",
            "cogs.village",
            "cogs.war",
            "cogs.clan",
            "cogs.donations",
            "cogs.capital",
            "cogs.games",
            "cogs.leaderboard",
            "cogs.notifications",
            "cogs.admin",
            "cogs.scanner",
            "cogs.tracker",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                log.error(f"Failed to load cog {cog}: {e}", exc_info=True)

        # Sync slash commands
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Synced slash commands to guild {guild_id}")
        else:
            await self.tree.sync()
            log.info("Synced slash commands globally")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="the Clash of Clans village 🏰",
            )
        )

    async def on_command_error(self, ctx, error):
        log.error(f"Command error: {error}", exc_info=True)


async def main():
    bot = CoCBot()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.critical("DISCORD_TOKEN not set in environment.")
        sys.exit(1)

    async with bot:
        await start_web_server(bot)   # ← was missing; Render needs this HTTP server
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
