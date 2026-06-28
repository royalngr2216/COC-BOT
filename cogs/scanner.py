"""
cogs/scanner.py — Background scanner that polls CoC API every N minutes,
detects upgrades by diffing snapshots, and posts to the village updates channel.
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from utils.completion import calculate_completion, diff_snapshots
from utils.embeds import upgrade_embed, milestone_embed, GOLD, GREEN, TEAL
from utils.coc_api import CoCAPIError

log = logging.getLogger("scanner")


class ScannerCog(commands.Cog, name="Scanner"):
    def __init__(self, bot):
        self.bot = bot
        self._scanning = False
        self.scanner_loop.start()

    def cog_unload(self):
        self.scanner_loop.cancel()

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    # ── Main scanner task ─────────────────────────────────────────────────────
    @tasks.loop(minutes=1)
    async def scanner_loop(self):
        """Outer loop: checks interval and delegates to _run_scan."""
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            return

        interval = cfg["scan_interval"] or 30
        # Use a simple in-memory tick counter
        if not hasattr(self, "_tick"):
            self._tick = 0
        self._tick += 1

        if self._tick < interval:
            return
        self._tick = 0

        if self._scanning:
            log.warning("Previous scan still running — skipping")
            return

        self._scanning = True
        try:
            await self._run_scan(cfg)
        except Exception as e:
            log.error(f"Scanner error: {e}", exc_info=True)
        finally:
            self._scanning = False

    @scanner_loop.before_loop
    async def before_scanner(self):
        await self.bot.wait_until_ready()
        self._tick = 0

    # ── Core scan logic ───────────────────────────────────────────────────────
    async def _run_scan(self, cfg):
        clan_tag = cfg["clan_tag"]
        log.info(f"Starting scan for clan {clan_tag}")

        try:
            members = await self.api.get_clan_members(clan_tag)
        except CoCAPIError as e:
            log.error(f"Could not fetch clan members: {e}")
            return

        village_channel = None
        if cfg["village_channel"]:
            guild = self.bot.get_guild(cfg["guild_id"])
            if guild:
                village_channel = guild.get_channel(cfg["village_channel"])

        for member in members:
            await self._scan_player(member["tag"], village_channel, cfg)
            await asyncio.sleep(0.5)  # gentle pacing between API calls

        log.info(f"Scan complete — {len(members)} members checked")

    async def _scan_player(self, player_tag: str, village_channel, cfg):
        try:
            player = await self.api.get_player(player_tag)
        except CoCAPIError as e:
            log.debug(f"Could not fetch player {player_tag}: {e}")
            return

        old_snap = await self.db.get_latest_snapshot(player_tag)
        await self.db.save_snapshot(player_tag, player)

        # First time we see this player — no comparison
        if old_snap is None:
            return

        changes = diff_snapshots(old_snap, player)
        if not changes:
            return

        # Log each upgrade
        for change in changes:
            await self.db.log_upgrade(
                player_tag,
                change["type"],
                change["name"],
                change["old"],
                change["new"],
            )

        # Build and send embed
        th = player.get("townHallLevel", 0)
        embed = upgrade_embed(player["name"], changes, th)

        # Village updates channel
        if village_channel and cfg["village_updates"]:
            try:
                await village_channel.send(embed=embed)
            except discord.HTTPException as e:
                log.warning(f"Could not post upgrade to village channel: {e}")

        # DM the linked player (if they have a link + DMs on)
        link = await self.db.get_link_by_tag(player_tag)
        if link and link["dm_notifs"] and cfg["dm_notifications"]:
            guild = self.bot.get_guild(cfg["guild_id"])
            if guild:
                member = guild.get_member(link["discord_id"])
                if member:
                    try:
                        await member.send(embed=embed)
                    except discord.Forbidden:
                        pass  # DMs closed

        # Milestone notifications (separate if configured)
        await self._check_milestones(player, changes, village_channel, cfg)

        # Update monthly snapshot if needed
        completion = calculate_completion(player)
        await self.db.ensure_monthly_snapshot(
            player_tag, completion["overall"], player
        )

    async def _check_milestones(self, player, changes, channel, cfg):
        if not cfg["milestone_notifs"]:
            return

        th = player.get("townHallLevel", 0)
        for change in changes:
            milestone = None

            if change["type"] == "th":
                milestone = f"upgraded to **Town Hall {change['new']}!** 🎉"

            elif change["type"] == "hero":
                max_levels = {
                    "Barbarian King": 95, "Archer Queen": 95,
                    "Grand Warden": 65, "Royal Champion": 45, "Minion Prince": 15,
                }
                if change["name"] in max_levels and change["new"] >= max_levels[change["name"]]:
                    milestone = f"**maxed {change['name']}!** 🎉"

            elif change["type"] == "pet" and change["old"] == 0:
                milestone = f"**unlocked {change['name']}!** 🐾"

            elif change["type"] in ("troop", "spell") and change["old"] == 0:
                milestone = f"**unlocked {change['name']}!** ⚗️"

            elif change["type"] == "equipment" and change["new"] >= 18:
                milestone = f"**maxed {change['name']} equipment!** 🔩"

            if milestone and channel:
                embed = milestone_embed(player["name"], milestone, th)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    # ── Manual scan trigger ───────────────────────────────────────────────────
    async def trigger_scan(self):
        """Manually trigger a scan (used by admin commands)."""
        cfg = await self.db.get_config()
        if cfg:
            await self._run_scan(cfg)


async def setup(bot):
    await bot.add_cog(ScannerCog(bot))
