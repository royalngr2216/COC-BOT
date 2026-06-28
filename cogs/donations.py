"""
cogs/donations.py — Donation leaderboard for the clan.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import base_embed, error_embed, GREEN, BLUE, GOLD, TH_ICONS
from utils.coc_api import CoCAPIError
from utils.pagination import PaginatorView

RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


class DonationsCog(commands.Cog, name="Donations"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="donations", description="Clan donation leaderboard")
    async def donations(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up."))
            return

        try:
            members = await self.api.get_clan_members(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        # Sort by donations
        donated_sorted = sorted(members, key=lambda m: m.get("donations", 0), reverse=True)
        received_sorted = sorted(members, key=lambda m: m.get("donationsReceived", 0), reverse=True)

        def build_embed(title: str, sorted_list: list, key: str, color: int, emoji: str) -> discord.Embed:
            embed = base_embed(title=title, color=color)
            lines = []
            for i, m in enumerate(sorted_list[:15], start=1):
                medal = RANK_MEDALS.get(i, f"`#{i}`")
                th = m.get("townHallLevel", 0)
                th_icon = TH_ICONS.get(th, "🏰")
                val = m.get(key, 0)
                lines.append(f"{medal} {th_icon} **{m['name']}** — {emoji} **{val:,}**")
            embed.description = "\n".join(lines) if lines else "*No data.*"
            embed.set_footer(text=f"Season donations • {len(sorted_list)} members")
            return embed

        donated_embed = build_embed(
            "🎁 Donation Leaderboard", donated_sorted, "donations", GREEN, "🎁"
        )
        received_embed = build_embed(
            "📥 Received Leaderboard", received_sorted, "donationsReceived", BLUE, "📥"
        )

        # Ratio leaderboard
        ratio_list = sorted(
            [
                {**m, "_ratio": m.get("donations", 0) / max(m.get("donationsReceived", 1), 1)}
                for m in members
            ],
            key=lambda m: m["_ratio"],
            reverse=True,
        )
        ratio_embed = base_embed(title="📊 Donation Ratio", color=GOLD)
        ratio_lines = []
        for i, m in enumerate(ratio_list[:15], start=1):
            medal = RANK_MEDALS.get(i, f"`#{i}`")
            ratio = m.get("_ratio", 0)
            ratio_lines.append(f"{medal} **{m['name']}** — `{ratio:.2f}x` ratio")
        ratio_embed.description = "\n".join(ratio_lines) if ratio_lines else "*No data.*"

        pages = [donated_embed, received_embed, ratio_embed]
        view = PaginatorView(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view)


async def setup(bot):
    await bot.add_cog(DonationsCog(bot))
