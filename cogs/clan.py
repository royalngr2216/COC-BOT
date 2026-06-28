"""
cogs/clan.py — Clan dashboard overview command.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed, info_embed,
    GOLD, BLUE, GREEN, TEAL, PURPLE, ORANGE,
    LEAGUE_ICONS, progress_bar,
)
from utils.coc_api import CoCAPIError


class ClanTabsView(discord.ui.View):
    TABS = [
        discord.SelectOption(label="Overview",   value="overview",  emoji="🏰", default=True),
        discord.SelectOption(label="Members",    value="members",   emoji="👥"),
        discord.SelectOption(label="War League", value="warleague", emoji="🏆"),
        discord.SelectOption(label="Capital",    value="capital",   emoji="🏛️"),
    ]

    def __init__(self, clan: dict, user_id: int):
        super().__init__(timeout=120)
        self.clan = clan
        self.user_id = user_id

    @discord.ui.select(placeholder="🏰 Select a section…", options=TABS)
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
            "members": self._members,
            "warleague": self._warleague,
            "capital": self._capital,
        }
        return dispatch.get(tab, self._overview)()

    def _overview(self) -> discord.Embed:
        c = self.clan
        badge = c.get("badgeUrls", {}).get("medium")
        war_league = c.get("warLeague", {}).get("name", "Unknown")
        l_icon = LEAGUE_ICONS.get(war_league, "🏆")
        capital_league = c.get("clanCapitalPoints", 0)

        embed = base_embed(
            title=f"🏰 Clan Dashboard — {c['name']}",
            description=f"`{c.get('tag')}` • {c.get('description', '')[:100]}",
            color=GOLD,
            thumbnail=badge,
        )
        embed.add_field(
            name="📊 Clan Info",
            value=(
                f"🏆 **Level {c.get('clanLevel', '?')}**\n"
                f"👥 **{c.get('members', 0)}/50** members\n"
                f"🌍 **{c.get('location', {}).get('name', 'Unknown')}**\n"
                f"🔒 **{c.get('type', 'invite_only').replace('_', ' ').title()}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚔️ War Stats",
            value=(
                f"🏆 **{c.get('warWins', 0):,}** wars won\n"
                f"❌ **{c.get('warLosses', 0):,}** lost\n"
                f"🤝 **{c.get('warTies', 0):,}** ties\n"
                f"🔥 **{c.get('warWinStreak', 0)}** win streak\n"
                f"{l_icon} **{war_league}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🎁 Donations",
            value=(
                f"📤 **{c.get('clanPoints', 0):,}** total clan points\n"
                f"🏛️ **{capital_league:,}** capital points"
            ),
            inline=False,
        )
        embed.set_footer(text="Use the dropdown to explore more")
        return embed

    def _members(self) -> discord.Embed:
        c = self.clan
        members = c.get("memberList", [])
        embed = base_embed(
            title=f"👥 Members — {c['name']}",
            description=f"**{len(members)}/50** members",
            color=BLUE,
            thumbnail=c.get("badgeUrls", {}).get("small"),
        )
        role_icons = {"leader": "👑", "coLeader": "🔱", "admin": "⭐", "member": "🏅"}
        from utils.embeds import TH_ICONS

        # Sort by TH desc
        members_sorted = sorted(members, key=lambda m: m.get("townHallLevel", 0), reverse=True)
        lines = []
        for m in members_sorted[:20]:
            th = m.get("townHallLevel", 0)
            th_icon = TH_ICONS.get(th, "🏰")
            role_icon = role_icons.get(m.get("role", "member"), "🏅")
            lines.append(
                f"{role_icon} {th_icon} **{m['name']}** — "
                f"🏆 {m.get('trophies', 0):,}"
            )
        embed.add_field(name="👥 Member List", value="\n".join(lines) or "*Empty*", inline=False)
        if len(members) > 20:
            embed.set_footer(text=f"Showing top 20 of {len(members)} members")
        return embed

    def _warleague(self) -> discord.Embed:
        c = self.clan
        war_league = c.get("warLeague", {}).get("name", "Unknown")
        l_icon = LEAGUE_ICONS.get(war_league, "🏆")
        embed = base_embed(
            title=f"🏆 War League — {c['name']}",
            description=f"{l_icon} **{war_league}**",
            color=ORANGE,
        )
        embed.add_field(
            name="📊 Record",
            value=(
                f"✅ **{c.get('warWins', 0):,}** wins\n"
                f"❌ **{c.get('warLosses', 0):,}** losses\n"
                f"🤝 **{c.get('warTies', 0):,}** ties\n"
                f"🔥 **{c.get('warWinStreak', 0)}** current streak"
            ),
        )
        return embed

    def _capital(self) -> discord.Embed:
        c = self.clan
        embed = base_embed(
            title=f"🏛️ Clan Capital — {c['name']}",
            color=PURPLE,
        )
        capital = c.get("clanCapital", {})
        capital_hall = capital.get("capitalHallLevel", 0)
        districts = capital.get("districts", [])

        embed.add_field(
            name="🏛️ Capital Hall",
            value=f"**Level {capital_hall}**",
            inline=True,
        )
        embed.add_field(
            name="💰 Capital Points",
            value=f"**{c.get('clanCapitalPoints', 0):,}**",
            inline=True,
        )
        if districts:
            dist_lines = [
                f"🏘️ **{d.get('name', 'District')}** Lv. **{d.get('districtHallLevel', 0)}**"
                for d in districts
            ]
            embed.add_field(name="🏘️ Districts", value="\n".join(dist_lines), inline=False)
        return embed


class ClanCog(commands.Cog, name="Clan"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="clan", description="View clan dashboard")
    async def clan(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet. Use `/setup`."))
            return

        try:
            clan = await self.api.get_clan(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        view = ClanTabsView(clan, interaction.user.id)
        embed = view._overview()
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(ClanCog(bot))
