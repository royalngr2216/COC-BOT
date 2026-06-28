"""
cogs/profile.py — Member profile command with tabbed embed navigation.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed,
    BLUE, GOLD, PURPLE, GREEN, TEAL, ORANGE,
    TH_ICONS, LEAGUE_ICONS, HERO_ICONS, ROLE_ICONS,
    progress_bar, mini_bar,
)
from utils.completion import calculate_completion
from utils.coc_api import CoCAPIError


def _safe_pct(current, maximum):
    if not maximum:
        return 100.0
    return min(100.0, (current / maximum) * 100)


class ProfileTabsView(discord.ui.View):
    TABS = [
        discord.SelectOption(label="Overview",     value="overview",   emoji="👤", default=True),
        discord.SelectOption(label="Heroes",       value="heroes",     emoji="🦸"),
        discord.SelectOption(label="War Stats",    value="war",        emoji="⚔️"),
        discord.SelectOption(label="Donations",    value="donations",  emoji="🎁"),
        discord.SelectOption(label="Achievements", value="achieve",    emoji="🏆"),
    ]

    def __init__(self, player: dict, discord_member: discord.Member,
                 completion: dict, war_stats: list, user_id: int):
        super().__init__(timeout=120)
        self.player = player
        self.discord_member = discord_member
        self.completion = completion
        self.war_stats = war_stats
        self.user_id = user_id

    @discord.ui.select(placeholder="👤 Select a section…", options=TABS)
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
            "overview":  self._overview,
            "heroes":    self._heroes,
            "war":       self._war,
            "donations": self._donations,
            "achieve":   self._achievements,
        }
        return dispatch.get(tab, self._overview)()

    def _header_info(self) -> str:
        p = self.player
        th = p.get("townHallLevel", 0)
        th_icon = TH_ICONS.get(th, "🏰")
        league = p.get("league", {}).get("name", "Unranked")
        l_icon = LEAGUE_ICONS.get(league, "⬜")
        role = p.get("role", "member")
        r_icon = ROLE_ICONS.get(role, "🏅")
        role_labels = {"leader": "Leader", "coLeader": "Co-Leader", "admin": "Elder", "member": "Member"}
        role_label = role_labels.get(role, role)
        return (
            f"{th_icon} **TH{th}** • {l_icon} **{league}**\n"
            f"🏆 **{p.get('trophies', 0):,}** • {r_icon} **{role_label}**\n"
            f"`{p.get('tag', '')}`"
        )

    def _overview(self) -> discord.Embed:
        p = self.player
        dm = self.discord_member
        c = self.completion
        embed = base_embed(
            title=f"👤 {p.get('name')} — Profile",
            color=BLUE,
            thumbnail=dm.display_avatar.url if dm else None,
        )
        embed.description = self._header_info()

        embed.add_field(
            name="📊 Village Completion",
            value=f"**Overall** {progress_bar(c.get('overall', 0))}",
            inline=False,
        )
        embed.add_field(
            name="🏅 Stats",
            value=(
                f"⭐ **{p.get('warStars', 0):,}** war stars\n"
                f"🎁 **{p.get('donations', 0):,}** donated\n"
                f"📥 **{p.get('donationsReceived', 0):,}** received\n"
                f"🏆 **{p.get('bestTrophies', 0):,}** best trophies"
            ),
            inline=True,
        )
        bh = p.get("builderHallLevel", 0)
        embed.add_field(
            name="🔨 Builder Base",
            value=(
                f"🏚️ **BH{bh}**\n"
                f"🏆 **{p.get('builderBaseTrophies', 0):,}** trophies\n"
                f"⭐ **{p.get('bestBuilderBaseTrophies', 0):,}** best"
            ),
            inline=True,
        )
        embed.set_footer(text="Use the dropdown below to see more sections")
        return embed

    def _heroes(self) -> discord.Embed:
        p = self.player
        dm = self.discord_member
        embed = base_embed(
            title=f"🦸 Heroes & Pets — {p.get('name')}",
            color=PURPLE,
            thumbnail=dm.display_avatar.url if dm else None,
        )

        hero_lines = []
        for hero in p.get("heroes", []):
            name = hero["name"]
            lv = hero.get("level", 0)
            max_lv = hero.get("maxLevel", lv or 1)
            icon = HERO_ICONS.get(name, "🦸")
            pct = _safe_pct(lv, max_lv)
            bar = mini_bar(pct)
            hero_lines.append(f"{icon} **{name}** `{lv}/{max_lv}` `{bar}` {pct:.0f}%")
        embed.add_field(
            name="🦸 Heroes",
            value="\n".join(hero_lines) if hero_lines else "*None*",
            inline=False,
        )

        pet_names = {
            "L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn",
            "Frosty", "Diggy", "Poison Lizard", "Phoenix", "Spirit Fox", "Angry Jelly",
        }
        pet_lines = []
        for t in p.get("troops", []):
            if t.get("name") in pet_names:
                lv = t.get("level", 0)
                max_lv = t.get("maxLevel", lv or 1)
                pct = _safe_pct(lv, max_lv)
                bar = mini_bar(pct)
                pet_lines.append(f"🐾 **{t['name']}** `{lv}/{max_lv}` `{bar}`")
        embed.add_field(
            name="🐾 Pets",
            value="\n".join(pet_lines) if pet_lines else "*None unlocked*",
            inline=False,
        )

        equip_lines = []
        for e in p.get("heroEquipment", [])[:10]:
            lv = e.get("level", 0)
            max_lv = e.get("maxLevel", 18)
            bar = mini_bar(_safe_pct(lv, max_lv))
            equip_lines.append(f"🔩 **{e['name']}** `{lv}/{max_lv}` `{bar}`")
        if equip_lines:
            embed.add_field(name="🔩 Equipment (top 10)", value="\n".join(equip_lines), inline=False)

        return embed

    def _war(self) -> discord.Embed:
        p = self.player
        dm = self.discord_member
        embed = base_embed(
            title=f"⚔️ War Stats — {p.get('name')}",
            color=ORANGE,
            thumbnail=dm.display_avatar.url if dm else None,
        )

        total_wars = len(self.war_stats)
        total_attacks = sum(r["attacks_used"] for r in self.war_stats)
        total_stars = sum(r["stars_earned"] for r in self.war_stats)
        total_destruction = sum(r["destruction"] for r in self.war_stats)
        missed = sum(
            r["attacks_allowed"] - r["attacks_used"]
            for r in self.war_stats
        )
        wins = sum(1 for r in self.war_stats if r["result"] == "win")

        avg_stars = total_stars / total_attacks if total_attacks > 0 else 0
        avg_dest = total_destruction / total_attacks if total_attacks > 0 else 0

        embed.add_field(
            name="📊 Career Stats",
            value=(
                f"⚔️ **{total_wars}** wars participated\n"
                f"⭐ **{total_stars}** total stars\n"
                f"💥 **{avg_dest:.1f}%** avg destruction\n"
                f"⭐ **{avg_stars:.2f}** avg stars/attack\n"
                f"🏆 **{wins}** wars won\n"
                f"❌ **{missed}** missed attacks"
            ),
            inline=True,
        )
        embed.add_field(
            name="🏅 War Stars",
            value=f"⭐ **{p.get('warStars', 0):,}** lifetime war stars",
            inline=True,
        )

        if self.war_stats:
            recent = self.war_stats[:5]
            lines = []
            for r in recent:
                result_icon = {"win": "✅", "lose": "❌", "tie": "🤝"}.get(r["result"], "❓")
                lines.append(
                    f"{result_icon} `{r['stars_earned']}⭐` `{r['destruction']:.0f}%` "
                    f"({r['attacks_used']}/{r['attacks_allowed']} atk)"
                )
            embed.add_field(
                name="📋 Recent Wars",
                value="\n".join(lines),
                inline=False,
            )
        return embed

    def _donations(self) -> discord.Embed:
        p = self.player
        dm = self.discord_member
        embed = base_embed(
            title=f"🎁 Donations — {p.get('name')}",
            color=GREEN,
            thumbnail=dm.display_avatar.url if dm else None,
        )
        donated = p.get("donations", 0)
        received = p.get("donationsReceived", 0)
        ratio = donated / received if received > 0 else float("inf")

        embed.add_field(
            name="📤 Season Stats",
            value=(
                f"🎁 **{donated:,}** donated\n"
                f"📥 **{received:,}** received\n"
                f"📊 **{ratio:.2f}x** ratio"
            ),
            inline=False,
        )
        # Donation achievement
        don_ach = next(
            (a for a in p.get("achievements", []) if a.get("name") == "Friend in Need"),
            None,
        )
        if don_ach:
            embed.add_field(
                name="🏆 All-Time Donations",
                value=f"**{don_ach.get('value', 0):,}** troops donated",
                inline=False,
            )
        return embed

    def _achievements(self) -> discord.Embed:
        p = self.player
        embed = base_embed(
            title=f"🏆 Achievements — {p.get('name')}",
            color=GOLD,
        )
        # Show top completed achievements
        completed = [
            a for a in p.get("achievements", [])
            if a.get("stars", 0) >= 3
        ][:12]
        lines = [f"⭐ **{a['name']}**" for a in completed]
        if lines:
            embed.add_field(
                name=f"✅ Completed ({len(completed)})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.description = "*No completed achievements found.*"
        return embed


class ProfileCog(commands.Cog, name="Profile"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="profile", description="View a member's profile card")
    @app_commands.describe(member="The Discord member to view (optional, defaults to you)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        link = await self.db.get_link_by_discord(target.id)
        if not link:
            await interaction.followup.send(
                embed=error_embed(
                    f"{target.mention} hasn't linked a CoC account.\nUse `/link` to link."
                )
            )
            return

        try:
            player = await self.api.get_player(link["player_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        completion = calculate_completion(player)
        war_stats = await self.db.get_player_war_stats(link["player_tag"])

        view = ProfileTabsView(player, target, completion, war_stats, interaction.user.id)
        embed = view._overview()
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(ProfileCog(bot))
