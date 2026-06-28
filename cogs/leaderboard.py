"""
cogs/leaderboard.py — Clan completion leaderboard and monthly progress rankings.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from utils.embeds import (
    base_embed, error_embed, info_embed,
    GOLD, BLUE, GREEN, TEAL, ORANGE,
    TH_ICONS, progress_bar, mini_bar,
)
from utils.completion import calculate_completion
from utils.coc_api import CoCAPIError
from utils.pagination import send_paginated


RANK_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


class LeaderboardCog(commands.Cog, name="Leaderboard"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    # ── /leaderboard ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="leaderboard",
        description="Clan village completion leaderboard"
    )
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet."))
            return

        try:
            members = await self.api.get_clan_members(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        await interaction.followup.send(
            embed=base_embed(
                title="⏳ Building Leaderboard…",
                description="Fetching village data for all members — this may take a moment.",
                color=BLUE,
                timestamp=False,
            )
        )

        results = []
        for member in members:
            try:
                player = await self.api.get_player(member["tag"])
                completion = calculate_completion(player)
                results.append({
                    "name": player.get("name", member["name"]),
                    "tag": member["tag"],
                    "th": player.get("townHallLevel", 0),
                    "overall": completion.get("overall", 0),
                    "heroes": completion.get("heroes", 0),
                    "walls": completion.get("walls", 0),
                    "lab": completion.get("laboratory", 0),
                })
                await asyncio.sleep(0.3)
            except CoCAPIError:
                continue

        results.sort(key=lambda x: x["overall"], reverse=True)

        # Build pages (10 per page)
        pages = []
        chunk_size = 10
        for page_i in range(0, len(results), chunk_size):
            chunk = results[page_i: page_i + chunk_size]
            embed = base_embed(
                title="🏆 Village Completion Leaderboard",
                color=GOLD,
            )
            lines = []
            for i, r in enumerate(chunk, start=page_i + 1):
                medal = RANK_MEDALS.get(i, f"`#{i}`")
                th_icon = TH_ICONS.get(r["th"], "🏰")
                bar = mini_bar(r["overall"])
                lines.append(
                    f"{medal} {th_icon} **{r['name']}** "
                    f"`{bar}` **{r['overall']:.1f}%**"
                )
            embed.description = "\n".join(lines)
            embed.set_footer(
                text=f"Page {page_i // chunk_size + 1} of {((len(results) - 1) // chunk_size) + 1} "
                     f"• {len(results)} members"
            )
            pages.append(embed)

        await interaction.edit_original_response(embed=pages[0])
        if len(pages) > 1:
            from utils.pagination import PaginatorView
            view = PaginatorView(pages, interaction.user.id)
            await interaction.edit_original_response(embed=pages[0], view=view)

    # ── /monthlyranks ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="monthlyranks",
        description="Monthly progress ranking — who improved the most this month"
    )
    async def monthlyranks(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet."))
            return

        month = datetime.utcnow().strftime("%Y-%m")
        try:
            members = await self.api.get_clan_members(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        results = []
        for member in members:
            tag = member["tag"]
            monthly = await self.db.get_monthly_snapshot(tag, month)
            try:
                player = await self.api.get_player(tag)
                current = calculate_completion(player)
                current_pct = current.get("overall", 0)
                start_pct = monthly["completion_pct"] if monthly else current_pct
                results.append({
                    "name": player.get("name", member["name"]),
                    "tag": tag,
                    "th": player.get("townHallLevel", 0),
                    "start": start_pct,
                    "current": current_pct,
                    "delta": current_pct - start_pct,
                })
                await asyncio.sleep(0.3)
            except CoCAPIError:
                continue

        results.sort(key=lambda x: x["delta"], reverse=True)

        embed = base_embed(
            title=f"📅 Monthly Progress — {month}",
            description="Ranked by completion % gained this month",
            color=TEAL,
        )

        lines = []
        for i, r in enumerate(results[:15], start=1):
            medal = RANK_MEDALS.get(i, f"`#{i}`")
            th_icon = TH_ICONS.get(r["th"], "🏰")
            sign = "+" if r["delta"] >= 0 else ""
            lines.append(
                f"{medal} {th_icon} **{r['name']}** "
                f"`{r['start']:.1f}% → {r['current']:.1f}%` "
                f"(`{sign}{r['delta']:.1f}%`)"
            )
        embed.description = "\n".join(lines) if lines else "*No data yet.*"
        embed.set_footer(text=f"Based on {month} snapshot data")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
