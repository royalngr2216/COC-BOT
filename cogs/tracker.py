"""
cogs/tracker.py — Clan member tracker.
Detects joins, leaves, promotions, and demotions by diffing clan member lists.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from utils.embeds import base_embed, error_embed, GREEN, RED, GOLD, BLUE, ORANGE
from utils.coc_api import CoCAPIError

log = logging.getLogger("tracker")

ROLE_ICONS = {
    "leader": "👑", "coLeader": "🔱",
    "admin": "⭐", "member": "🏅",
}

ROLE_LABELS = {
    "leader": "Leader", "coLeader": "Co-Leader",
    "admin": "Elder", "member": "Member",
}


class TrackerCog(commands.Cog, name="Tracker"):
    def __init__(self, bot):
        self.bot = bot
        self._previous_members: dict = {}  # tag -> member dict
        self.tracker_loop.start()

    def cog_unload(self):
        self.tracker_loop.cancel()

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @tasks.loop(minutes=5)
    async def tracker_loop(self):
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            return

        try:
            await self._check_roster(cfg)
        except Exception as e:
            log.error(f"Tracker error: {e}", exc_info=True)

    @tracker_loop.before_loop
    async def before_tracker(self):
        await self.bot.wait_until_ready()

    async def _check_roster(self, cfg):
        clan_tag = cfg["clan_tag"]
        try:
            members = await self.api.get_clan_members(clan_tag)
        except CoCAPIError:
            return

        current = {m["tag"]: m for m in members}
        previous = self._previous_members

        tracker_channel = None
        if cfg["tracker_channel"]:
            guild = self.bot.get_guild(cfg["guild_id"])
            if guild:
                tracker_channel = guild.get_channel(cfg["tracker_channel"])

        if not previous:
            # First run — just seed the roster
            self._previous_members = current
            return

        events = []

        # Joined
        for tag, member in current.items():
            if tag not in previous:
                events.append(("joined", member, None))
                await self.db.log_member_event(tag, member["name"], "joined")

        # Left
        for tag, member in previous.items():
            if tag not in current:
                events.append(("left", member, None))
                await self.db.log_member_event(tag, member["name"], "left")

        # Promoted / Demoted
        for tag, member in current.items():
            if tag in previous:
                old_role = previous[tag].get("role")
                new_role = member.get("role")
                if old_role != new_role:
                    if _role_rank(new_role) > _role_rank(old_role):
                        events.append(("promoted", member, {"old": old_role, "new": new_role}))
                        await self.db.log_member_event(
                            tag, member["name"], "promoted", old_role, new_role
                        )
                    else:
                        events.append(("demoted", member, {"old": old_role, "new": new_role}))
                        await self.db.log_member_event(
                            tag, member["name"], "demoted", old_role, new_role
                        )

        self._previous_members = current

        if tracker_channel and events:
            for event_type, member, extra in events:
                embed = self._build_event_embed(event_type, member, extra)
                try:
                    await tracker_channel.send(embed=embed)
                    await asyncio.sleep(0.3)
                except discord.HTTPException as e:
                    log.warning(f"Could not post tracker event: {e}")

    def _build_event_embed(self, event_type: str, member: dict, extra: dict) -> discord.Embed:
        name = member["name"]
        tag = member["tag"]
        th = member.get("townHallLevel", "?")
        trophies = member.get("trophies", 0)
        role = member.get("role", "member")
        role_icon = ROLE_ICONS.get(role, "🏅")
        role_label = ROLE_LABELS.get(role, role)

        if event_type == "joined":
            embed = base_embed(
                title=f"📥 Member Joined",
                description=(
                    f"**{name}** `{tag}`\n"
                    f"🏰 TH **{th}** • 🏆 **{trophies:,}** trophies\n"
                    f"{role_icon} **{role_label}**"
                ),
                color=GREEN,
            )
        elif event_type == "left":
            embed = base_embed(
                title=f"📤 Member Left",
                description=(
                    f"**{name}** `{tag}`\n"
                    f"🏰 TH **{th}** • 🏆 **{trophies:,}** trophies\n"
                    f"*Left the clan* 👋"
                ),
                color=RED,
            )
        elif event_type == "promoted":
            old_lbl = ROLE_LABELS.get(extra["old"], extra["old"])
            new_lbl = ROLE_LABELS.get(extra["new"], extra["new"])
            new_icon = ROLE_ICONS.get(extra["new"], "⭐")
            embed = base_embed(
                title=f"⬆️ Member Promoted",
                description=(
                    f"**{name}** `{tag}`\n"
                    f"**{old_lbl}** → {new_icon} **{new_lbl}**"
                ),
                color=GOLD,
            )
        else:  # demoted
            old_lbl = ROLE_LABELS.get(extra["old"], extra["old"])
            new_lbl = ROLE_LABELS.get(extra["new"], extra["new"])
            new_icon = ROLE_ICONS.get(extra["new"], "🏅")
            embed = base_embed(
                title=f"⬇️ Member Demoted",
                description=(
                    f"**{name}** `{tag}`\n"
                    f"**{old_lbl}** → {new_icon} **{new_lbl}**"
                ),
                color=ORANGE,
            )

        embed.set_footer(text="Clan Tracker")
        return embed


def _role_rank(role: str) -> int:
    return {"leader": 4, "coLeader": 3, "admin": 2, "member": 1}.get(role, 0)


async def setup(bot):
    await bot.add_cog(TrackerCog(bot))
