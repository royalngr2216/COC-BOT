"""
cogs/games.py — Clan Games: current points, top contributors, members below target.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed, info_embed,
    GOLD, RED, BLUE, TEAL,
    progress_bar, mini_bar,
)
from utils.coc_api import CoCAPIError

CLAN_GAMES_MAX = 4000


class GamesCog(commands.Cog, name="Games"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="clangames", description="Clan Games progress overview")
    @app_commands.describe(target="Point target per member (default: 4000)")
    async def clangames(self, interaction: discord.Interaction, target: int = 4000):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet."))
            return

        try:
            clan = await self.api.get_clan(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        members = clan.get("memberList", [])
        active = any(m.get("clanGamePoints", 0) > 0 for m in members)

        if not active:
            await interaction.followup.send(
                embed=info_embed(
                    "Clan Games aren't currently active, or no points have been earned yet.",
                    title="🎮 Clan Games",
                )
            )
            return

        target = max(1, min(target, CLAN_GAMES_MAX))
        sorted_members = sorted(members, key=lambda m: m.get("clanGamePoints", 0), reverse=True)
        total_points = sum(m.get("clanGamePoints", 0) for m in members)

        view = ClanGamesView(sorted_members, total_points, target, interaction.user.id)
        embed = view._overview()
        await interaction.followup.send(embed=embed, view=view)


class ClanGamesView(discord.ui.View):
    TABS = [
        discord.SelectOption(label="Overview",        value="overview",    emoji="🎮", default=True),
        discord.SelectOption(label="Top Players",     value="top",         emoji="🏆"),
        discord.SelectOption(label="Below Target",    value="below",       emoji="⚠️"),
        discord.SelectOption(label="Full Leaderboard",value="leaderboard", emoji="📋"),
    ]

    def __init__(self, members, total_points, target, user_id):
        super().__init__(timeout=120)
        self.members = members
        self.total_points = total_points
        self.target = target
        self.user_id = user_id

    @discord.ui.select(placeholder="🎮 Select a section…", options=TABS)
    async def tab_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return
        tab = select.values[0]
        for opt in select.options:
            opt.default = opt.value == tab
        await interaction.response.edit_message(embed=self._build(tab), view=self)

    def _build(self, tab):
        return {"overview": self._overview, "top": self._top,
                "below": self._below, "leaderboard": self._leaderboard}.get(tab, self._overview)()

    def _overview(self):
        target = self.target
        at_target = sum(1 for m in self.members if m.get("clanGamePoints", 0) >= target)
        below = len(self.members) - at_target
        max_possible = len(self.members) * CLAN_GAMES_MAX
        overall_pct = (self.total_points / max_possible * 100) if max_possible > 0 else 0
        embed = base_embed(title="🎮 Clan Games", color=TEAL)
        embed.description = (
            f"**Clan Total** {progress_bar(overall_pct)}\n"
            f"**{self.total_points:,}** / **{max_possible:,}** possible points"
        )
        embed.add_field(
            name="📊 Stats",
            value=(
                f"✅ **{at_target}** at {target:,}+ pts\n"
                f"⚠️ **{below}** below target\n"
                f"📊 **{self.total_points:,}** total"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Target: {target:,} pts per member")
        return embed

    def _top(self):
        embed = base_embed(title="🏆 Top Contributors", color=GOLD)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, m in enumerate(self.members[:15], start=1):
            pts = m.get("clanGamePoints", 0)
            bar = mini_bar(min(100, pts / self.target * 100))
            lines.append(f"{medals.get(i, f'`#{i}`')} **{m['name']}** `{bar}` **{pts:,}**")
        embed.description = "\n".join(lines) or "*No data.*"
        return embed

    def _below(self):
        embed = base_embed(title="⚠️ Below Target", color=RED)
        below = [m for m in self.members if m.get("clanGamePoints", 0) < self.target]
        if not below:
            embed.description = f"✅ **Everyone has reached {self.target:,} points!**"
            return embed
        lines = [
            f"• **{m['name']}** — `{m.get('clanGamePoints',0):,}` pts "
            f"(needs **{self.target - m.get('clanGamePoints',0):,}** more)"
            for m in below
        ]
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{len(below)} below target")
        return embed

    def _leaderboard(self):
        embed = base_embed(title="📋 Full Leaderboard", color=BLUE)
        lines = []
        for i, m in enumerate(self.members, start=1):
            pts = m.get("clanGamePoints", 0)
            icon = "✅" if pts >= self.target else "⏳"
            lines.append(f"`#{i:>2}` {icon} **{m['name']}** — `{pts:,}`")
        embed.description = "\n".join(lines[:25]) or "*No data.*"
        if len(self.members) > 25:
            embed.set_footer(text=f"Top 25 of {len(self.members)}")
        return embed


async def setup(bot):
    await bot.add_cog(GamesCog(bot))
