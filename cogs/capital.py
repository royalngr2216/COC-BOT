"""
cogs/capital.py — Clan Capital: raid medals, attacks, who still has attacks remaining.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed, info_embed,
    PURPLE, GOLD, GREEN, RED, ORANGE, BLUE,
    TH_ICONS, progress_bar, mini_bar,
)
from utils.coc_api import CoCAPIError


class CapitalCog(commands.Cog, name="Capital"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="capital", description="Clan Capital raid weekend overview")
    async def capital(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet."))
            return

        try:
            seasons = await self.api.get_capital_raid_seasons(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        items = seasons.get("items", [])
        if not items:
            await interaction.followup.send(
                embed=info_embed("No raid season data found.", title="🏛️ Clan Capital")
            )
            return

        season = items[0]
        state = season.get("state", "ongoing")
        total_attacks = season.get("totalAttacks", 0)
        capital_total_loot = season.get("capitalTotalLoot", 0)
        raids_completed = season.get("raidsCompleted", 0)
        defensive_reward = season.get("defensiveReward", 0)
        offensive_reward = season.get("offensiveReward", 0)

        embed = base_embed(
            title="🏛️ Clan Capital — Raid Weekend",
            color=PURPLE,
        )

        state_labels = {
            "ongoing": "🟢 Raid Weekend Active",
            "ended": "🔴 Raid Weekend Ended",
            "preparation": "🟡 Upcoming",
        }
        embed.description = state_labels.get(state, state)

        embed.add_field(
            name="📊 Season Stats",
            value=(
                f"⚔️ **{total_attacks}** total attacks\n"
                f"🏰 **{raids_completed}** raids completed\n"
                f"💰 **{capital_total_loot:,}** capital gold looted\n"
                f"🎖️ **{offensive_reward:,}** offensive medals\n"
                f"🛡️ **{defensive_reward:,}** defensive medals"
            ),
            inline=False,
        )

        members = season.get("members", [])
        if members:
            view = CapitalView(members, interaction.user.id, embed)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)


class CapitalView(discord.ui.View):
    TABS = [
        discord.SelectOption(label="Overview",      value="overview", emoji="🏛️", default=True),
        discord.SelectOption(label="Top Raiders",   value="top",      emoji="🏆"),
        discord.SelectOption(label="Needs Attacks", value="missing",  emoji="❌"),
        discord.SelectOption(label="Medal Tracker", value="medals",   emoji="🎖️"),
    ]

    def __init__(self, members: list, user_id: int, overview_embed: discord.Embed):
        super().__init__(timeout=120)
        self.members = members
        self.user_id = user_id
        self.overview_embed = overview_embed

    @discord.ui.select(placeholder="🏛️ Select a section…", options=TABS)
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
        return {
            "overview": lambda: self.overview_embed,
            "top":      self._top_raiders,
            "missing":  self._missing_attacks,
            "medals":   self._medals,
        }.get(tab, lambda: self.overview_embed)()

    def _top_raiders(self) -> discord.Embed:
        sorted_members = sorted(
            self.members,
            key=lambda m: m.get("capitalResourcesLooted", 0),
            reverse=True,
        )
        embed = base_embed(title="🏆 Top Raiders", color=GOLD)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, m in enumerate(sorted_members[:15], start=1):
            medal = medals.get(i, f"`#{i}`")
            attacks = m.get("attacks", 0)
            loot = m.get("capitalResourcesLooted", 0)
            lines.append(f"{medal} **{m['name']}** — 💰 **{loot:,}** | ⚔️ **{attacks}** atk")
        embed.description = "\n".join(lines) if lines else "*No data.*"
        return embed

    def _missing_attacks(self) -> discord.Embed:
        embed = base_embed(title="❌ Members with Remaining Attacks", color=RED)
        attack_limit = 6
        missing = [m for m in self.members if m.get("attacks", 0) < attack_limit]
        if not missing:
            embed.description = "✅ **Everyone has used all their attacks!**"
            return embed
        lines = []
        for m in sorted(missing, key=lambda x: x.get("attacks", 0)):
            used = m.get("attacks", 0)
            left = attack_limit - used
            lines.append(f"• **{m['name']}** — `{used}/{attack_limit}` attacks (`{left}` remaining)")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{len(missing)} member(s) still have attacks remaining")
        return embed

    def _medals(self) -> discord.Embed:
        embed = base_embed(title="🎖️ Raid Medal Tracker", color=PURPLE)
        sorted_members = sorted(
            self.members,
            key=lambda m: m.get("capitalResourcesLooted", 0),
            reverse=True,
        )
        lines = []
        for m in sorted_members[:20]:
            attacks = m.get("attacks", 0)
            loot = m.get("capitalResourcesLooted", 0)
            est_medals = loot // 1000
            lines.append(
                f"• **{m['name']}** ⚔️ `{attacks}` atk | 💰 `{loot:,}` | 🎖️ ~`{est_medals}` medals"
            )
        embed.description = "\n".join(lines) if lines else "*No data.*"
        embed.set_footer(text="Medal estimate is approximate")
        return embed


async def setup(bot):
    await bot.add_cog(CapitalCog(bot))
