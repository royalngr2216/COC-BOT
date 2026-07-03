"""
cogs/war.py — War system: current war, reminders, stats, history.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.embeds import (
    base_embed, error_embed, info_embed, warning_embed,
    ORANGE, RED, GREEN, GOLD, BLUE, PURPLE, TEAL,
    TH_ICONS, progress_bar, mini_bar,
)
from utils.coc_api import CoCAPIError
from utils.pagination import send_paginated
from utils import images as img

log = logging.getLogger("war")


def _parse_war_time(s: str) -> datetime:
    """Parse CoC API date format YYYYMMDDTHHMMSS.000Z"""
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _time_remaining(end_time: str) -> timedelta:
    end = _parse_war_time(end_time)
    now = datetime.now(timezone.utc)
    return max(end - now, timedelta(0))


def _format_td(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, m = divmod(total // 60, 60)
    s = total % 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


class WarTabsView(discord.ui.View):
    TABS = [
        discord.SelectOption(label="Overview",     value="overview",  emoji="🏆", default=True),
        discord.SelectOption(label="Attack Log",   value="attacks",   emoji="⚔️"),
        discord.SelectOption(label="Missing",      value="missing",   emoji="❌"),
        discord.SelectOption(label="Lineup",       value="lineup",    emoji="📋"),
    ]

    def __init__(self, war: dict, user_id: int):
        super().__init__(timeout=120)
        self.war = war
        self.user_id = user_id

    @discord.ui.select(placeholder="⚔️ Select war section…", options=TABS)
    async def tab_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return
        tab = select.values[0]
        for opt in select.options:
            opt.default = opt.value == tab
        embed = self._build(tab)
        await interaction.response.edit_message(embed=embed, view=self)

    def _build(self, tab: str) -> discord.Embed:
        dispatch = {
            "overview": self._overview,
            "attacks":  self._attacks,
            "missing":  self._missing,
            "lineup":   self._lineup,
        }
        return dispatch.get(tab, self._overview)()

    def _us(self):
        return self["clan"] if "clan" in self.war else self.war.get("clan", {})

    def _them(self):
        return self.war.get("opponent", {})

    def _all_our_members(self):
        return self.war.get("clan", {}).get("members", [])

    def _state_label(self):
        state = self.war.get("state", "notInWar")
        return {
            "notInWar": "🟡 Not in War",
            "preparation": "🟠 Prep Day",
            "inWar": "🟢 Battle Day",
            "warEnded": "🔴 War Ended",
        }.get(state, state)

    def _overview(self) -> discord.Embed:
        w = self.war
        us = w.get("clan", {})
        them = w.get("opponent", {})
        state = w.get("state", "notInWar")
        size = w.get("teamSize", 0)

        time_left = ""
        if state == "inWar":
            td = _time_remaining(w.get("endTime", ""))
            time_left = f"\n⏱️ **{_format_td(td)}** remaining"
        elif state == "preparation":
            td = _time_remaining(w.get("startTime", ""))
            time_left = f"\n⏳ Battle day starts in **{_format_td(td)}**"

        embed = base_embed(
            title=f"⚔️ Current War — {self._state_label()}",
            description=(
                f"**{us.get('name')}** vs **{them.get('name')}**\n"
                f"👥 **{size}v{size}** war{time_left}"
            ),
            color=ORANGE,
            thumbnail=us.get("badgeUrls", {}).get("small"),
        )

        our_stars = us.get("stars", 0)
        their_stars = them.get("stars", 0)
        our_dest = us.get("destructionPercentage", 0)
        their_dest = them.get("destructionPercentage", 0)

        embed.add_field(
            name=f"🏠 {us.get('name', 'Us')}",
            value=(
                f"⭐ **{our_stars}** stars\n"
                f"💥 **{our_dest:.2f}%** destruction\n"
                f"⚔️ **{us.get('attacks', 0)}** attacks used"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"🏴 {them.get('name', 'Them')}",
            value=(
                f"⭐ **{their_stars}** stars\n"
                f"💥 **{their_dest:.2f}%** destruction\n"
                f"⚔️ **{them.get('attacks', 0)}** attacks used"
            ),
            inline=True,
        )

        # Status indicator
        if our_stars > their_stars:
            embed.add_field(name="📊 Status", value="🟢 **Winning**", inline=False)
        elif our_stars < their_stars:
            embed.add_field(name="📊 Status", value="🔴 **Losing**", inline=False)
        else:
            embed.add_field(name="📊 Status", value="🟡 **Tied**", inline=False)

        embed.set_footer(text="Use the dropdown below to see attack log & missing attacks")
        embed.set_image(url="attachment://war_banner.png")
        return embed

    def _attacks(self) -> discord.Embed:
        w = self.war
        members = w.get("clan", {}).get("members", [])
        embed = base_embed(title="⚔️ Attack Log", color=ORANGE)
        lines = []
        for m in sorted(members, key=lambda x: x.get("mapPosition", 99)):
            attacks = m.get("attacks", [])
            for atk in attacks:
                stars = "⭐" * atk.get("stars", 0)
                dest = atk.get("destructionPercentage", 0)
                pos = m.get("mapPosition", "?")
                lines.append(
                    f"**#{pos}** {m['name']} → #{atk.get('defenderMapPosition', '?')} "
                    f"{stars or '○○○'} `{dest:.0f}%`"
                )
        embed.description = "\n".join(lines[:25]) if lines else "*No attacks yet.*"
        if len(lines) > 25:
            embed.description += f"\n*...and {len(lines)-25} more*"
        return embed

    def _missing(self) -> discord.Embed:
        w = self.war
        members = w.get("clan", {}).get("members", [])
        state = w.get("state", "")
        max_atk = 2 if state in ("inWar", "warEnded") else 0
        embed = base_embed(title="❌ Missing Attacks", color=RED)
        no_attack = []
        one_left = []
        for m in members:
            used = len(m.get("attacks", []))
            remaining = max_atk - used
            if remaining >= 2:
                no_attack.append(f"• **{m['name']}** (0/{max_atk} attacks)")
            elif remaining == 1:
                one_left.append(f"• **{m['name']}** (1/{max_atk} attacks)")

        if no_attack:
            embed.add_field(
                name=f"🚨 No Attacks ({len(no_attack)})",
                value="\n".join(no_attack[:15]),
                inline=False,
            )
        if one_left:
            embed.add_field(
                name=f"⚠️ One Attack Left ({len(one_left)})",
                value="\n".join(one_left[:15]),
                inline=False,
            )
        if not no_attack and not one_left:
            embed.description = "✅ **Everyone has used all their attacks!**"
        return embed

    def _lineup(self) -> discord.Embed:
        w = self.war
        members = sorted(
            w.get("clan", {}).get("members", []),
            key=lambda x: x.get("mapPosition", 99),
        )
        embed = base_embed(title="📋 War Lineup", color=BLUE)
        lines = []
        for m in members[:25]:
            pos = m.get("mapPosition", "?")
            th = m.get("townhallLevel", 0)
            th_icon = TH_ICONS.get(th, "🏰")
            attacks_used = len(m.get("attacks", []))
            lines.append(f"**#{pos}** {th_icon} **{m['name']}** `{attacks_used}/2 atk`")
        embed.description = "\n".join(lines) if lines else "*No lineup data.*"
        if len(members) > 25:
            embed.description += f"\n*...and {len(members)-25} more*"
        return embed


class WarCog(commands.Cog, name="War"):
    def __init__(self, bot):
        self.bot = bot
        self._reminder_sent: dict = {}  # war_id -> set of milestone strings
        self.war_reminder_loop.start()

    def cog_unload(self):
        self.war_reminder_loop.cancel()

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    # ── /war ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="war", description="View the current clan war status")
    async def war(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet."))
            return

        try:
            war = await self.api.get_current_war(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        if war.get("state") == "notInWar":
            await interaction.followup.send(
                embed=info_embed("The clan is not currently in a war.", title="⚔️ No Active War")
            )
            return

        view = WarTabsView(war, interaction.user.id)
        embed = view._overview()

        us = war.get("clan", {})
        them = war.get("opponent", {})
        state_label = {
            "preparation": "Prep Day", "inWar": "Battle Day", "warEnded": "War Ended",
        }.get(war.get("state"), war.get("state", "War"))
        try:
            session = await self.api.get_session()
            buf = await img.render_matchup_banner(
                session,
                left_name=us.get("name", "Us"),
                left_badge_url=us.get("badgeUrls", {}).get("medium"),
                left_stars=us.get("stars", 0),
                left_destruction=us.get("destructionPercentage", 0),
                left_attacks_used=us.get("attacks", 0),
                left_th_counts=img.th_counts_from_members(us.get("members", [])),
                right_name=them.get("name", "Them"),
                right_badge_url=them.get("badgeUrls", {}).get("medium"),
                right_stars=them.get("stars", 0),
                right_destruction=them.get("destructionPercentage", 0),
                right_attacks_used=them.get("attacks", 0),
                right_th_counts=img.th_counts_from_members(them.get("members", [])),
                team_size=war.get("teamSize", 0),
                state_label=state_label,
                subtitle="Clan War",
            )
            file = discord.File(buf, filename="war_banner.png")
            await interaction.followup.send(embed=embed, view=view, file=file)
        except Exception:
            log.exception("Failed to render war banner image")
            embed.set_image(url=None)
            await interaction.followup.send(embed=embed, view=view)

    # ── /warhistory ───────────────────────────────────────────────────────────
    @app_commands.command(name="warhistory", description="View recent war history")
    async def warhistory(self, interaction: discord.Interaction):
        await interaction.response.defer()
        wars = await self.db.get_war_history(limit=10)
        if not wars:
            await interaction.followup.send(
                embed=info_embed("No war history recorded yet.", title="📜 War History")
            )
            return

        pages = []
        for i, w in enumerate(wars):
            result_icon = {"win": "✅", "lose": "❌", "tie": "🤝"}.get(w["result"], "❓")
            color = {"win": GREEN, "lose": RED, "tie": GOLD}.get(w["result"], BLUE)
            embed = base_embed(
                title=f"{result_icon} War #{i+1} — {w['result'].capitalize() if w['result'] else 'Unknown'}",
                color=color,
            )
            embed.add_field(
                name="📊 Result",
                value=(
                    f"⭐ **{w['our_stars']}** vs **{w['opp_stars']}** stars\n"
                    f"💥 **{w['our_destruction']:.1f}%** vs **{w['opp_destruction']:.1f}%**\n"
                    f"👥 **{w['team_size']}v{w['team_size']}**"
                ),
            )
            if w["start_time"]:
                embed.add_field(name="📅 Date", value=f"`{w['start_time'][:10]}`")
            pages.append(embed)

        await send_paginated(interaction, pages)

    # ── War Reminders ─────────────────────────────────────────────────────────
    @tasks.loop(minutes=5)
    async def war_reminder_loop(self):
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"] or not cfg["war_reminders"]:
            return

        try:
            war = await self.api.get_current_war(cfg["clan_tag"])
        except CoCAPIError:
            return

        if war.get("state") != "inWar":
            return

        end_time = war.get("endTime", "")
        td = _time_remaining(end_time)
        total_minutes = td.total_seconds() / 60

        # Determine which milestone we're at
        milestones = [
            (360, "6h"),
            (120, "2h"),
            (30,  "30m"),
        ]

        war_id = f"{war.get('opponent', {}).get('tag', 'unknown')}_{war.get('preparationStartTime', '')}"
        sent = self._reminder_sent.setdefault(war_id, set())

        for threshold, label in milestones:
            if total_minutes <= threshold and label not in sent:
                sent.add(label)
                await self._send_war_reminder(war, cfg, label)
                break

    @war_reminder_loop.before_loop
    async def before_war_reminder(self):
        await self.bot.wait_until_ready()

    async def _send_war_reminder(self, war: dict, cfg, time_label: str):
        reminder_channel_id = cfg["reminder_channel"] or cfg["war_channel"]
        if not reminder_channel_id:
            return

        guild = self.bot.get_guild(cfg["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(reminder_channel_id)
        if not channel:
            return

        members = war.get("clan", {}).get("members", [])
        state = war.get("state", "inWar")
        max_atk = 2

        # Find players with attacks remaining
        need_attacks = []
        for m in members:
            used = len(m.get("attacks", []))
            remaining = max_atk - used
            if remaining > 0:
                need_attacks.append((m["name"], remaining, m.get("tag", "")))

        embed = base_embed(
            title=f"⏰ War Reminder — {time_label} Left!",
            description=(
                f"**{len(need_attacks)}** player(s) still have attacks remaining!\n"
                f"⏱️ **{time_label}** until war ends."
            ),
            color=RED if time_label == "30m" else ORANGE,
        )

        if need_attacks:
            ping_mentions = []
            lines = []
            for name, remaining, tag in need_attacks:
                link = await self.db.get_link_by_tag(tag)
                mention = f"<@{link['discord_id']}>" if link else f"**{name}**"
                lines.append(f"• {mention} — `{remaining}` attack(s) left")
                if link:
                    ping_mentions.append(mention)

            embed.add_field(
                name=f"⚔️ Needs to Attack ({len(need_attacks)})",
                value="\n".join(lines[:20]),
                inline=False,
            )

            ping_text = " ".join(ping_mentions[:20]) if ping_mentions else ""
            await channel.send(content=ping_text, embed=embed)
        else:
            embed.description = "✅ **All attacks used! Great job everyone!**"
            await channel.send(embed=embed)

    # ── /warstats (player) ────────────────────────────────────────────────────
    @app_commands.command(name="warstats", description="View a player's war statistics")
    @app_commands.describe(member="The member to check (optional)")
    async def warstats(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        link = await self.db.get_link_by_discord(target.id)
        if not link:
            await interaction.followup.send(
                embed=error_embed(f"{target.mention} hasn't linked a CoC account.")
            )
            return

        stats = await self.db.get_player_war_stats(link["player_tag"])
        if not stats:
            await interaction.followup.send(
                embed=info_embed("No war stats recorded yet for this player.", title="⚔️ War Stats")
            )
            return

        total = len(stats)
        total_stars = sum(r["stars_earned"] for r in stats)
        total_dest = sum(r["destruction"] for r in stats)
        total_attacks = sum(r["attacks_used"] for r in stats)
        missed = sum(r["attacks_allowed"] - r["attacks_used"] for r in stats)
        wins = sum(1 for r in stats if r["result"] == "win")

        embed = base_embed(
            title=f"⚔️ War Stats — {target.display_name}",
            color=ORANGE,
            thumbnail=target.display_avatar.url,
        )
        embed.description = f"`{link['player_tag']}`"
        embed.add_field(
            name="📊 Stats",
            value=(
                f"⚔️ **{total}** wars\n"
                f"⭐ **{total_stars}** stars\n"
                f"💥 **{total_dest/total_attacks:.1f}%** avg destruction\n"
                f"⭐ **{total_stars/total_attacks:.2f}** stars/attack\n"
                f"🏆 **{wins}** wars won\n"
                f"❌ **{missed}** missed attacks"
            ),
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(WarCog(bot))
