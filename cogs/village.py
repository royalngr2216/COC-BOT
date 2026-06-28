"""
cogs/village.py — Village completion and progress commands.
Uses select menus for tabbed navigation between categories.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from utils.embeds import (
    base_embed, error_embed, info_embed, completion_embed,
    progress_bar, mini_bar, TEAL, BLUE, GOLD, GREEN, PURPLE, ORANGE, RED,
    TH_ICONS, LEAGUE_ICONS, HERO_ICONS,
)
from utils.completion import calculate_completion
from utils.coc_api import CoCAPIError
from utils.pagination import send_paginated


# ── Completion tabs select menu ───────────────────────────────────────────────
class CompletionTabsView(discord.ui.View):
    def __init__(self, player: dict, completion: dict, user_id: int):
        super().__init__(timeout=120)
        self.player = player
        self.completion = completion
        self.user_id = user_id

    def _check_author(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.select(
        placeholder="📊 Select a category…",
        options=[
            discord.SelectOption(label="Overview", value="overview", emoji="📊", default=True),
            discord.SelectOption(label="Heroes & Pets", value="heroes", emoji="🦸"),
            discord.SelectOption(label="Equipment", value="equipment", emoji="🔩"),
            discord.SelectOption(label="Laboratory", value="lab", emoji="🔬"),
            discord.SelectOption(label="Defenses", value="defenses", emoji="🏰"),
            discord.SelectOption(label="Buildings", value="buildings", emoji="🏗️"),
            discord.SelectOption(label="Walls", value="walls", emoji="🧱"),
            discord.SelectOption(label="Needed Upgrades", value="remaining", emoji="📋"),
        ],
    )
    async def tab_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self._check_author(interaction):
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return
        tab = select.values[0]
        embed = self._build_tab(tab)
        # Update default
        for opt in select.options:
            opt.default = opt.value == tab
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_tab(self, tab: str) -> discord.Embed:
        p = self.player
        c = self.completion
        name = p.get("name", "Unknown")
        th = p.get("townHallLevel", 0)
        th_icon = TH_ICONS.get(th, "🏰")
        tag = p.get("tag", "")

        if tab == "overview":
            return self._overview()
        elif tab == "heroes":
            return self._heroes_pets()
        elif tab == "equipment":
            return self._equipment()
        elif tab == "lab":
            return self._laboratory()
        elif tab == "defenses":
            return self._defenses()
        elif tab == "buildings":
            return self._buildings()
        elif tab == "walls":
            return self._walls()
        elif tab == "remaining":
            return self._remaining()
        return self._overview()

    def _overview(self) -> discord.Embed:
        p = self.player
        c = self.completion
        th = p.get("townHallLevel", 0)
        th_icon = TH_ICONS.get(th, "🏰")
        name = p.get("name", "Unknown")
        league = p.get("league", {}).get("name", "Unranked")
        l_icon = LEAGUE_ICONS.get(league, "⬜")

        embed = base_embed(
            title=f"{th_icon} Village Completion — {name}",
            color=TEAL,
        )
        embed.description = (
            f"{l_icon} **{league}** • 🏆 **{p.get('trophies', 0):,}** • "
            f"⭐ **{p.get('warStars', 0):,}** war stars\n"
            f"`{p.get('tag', '')}`\n\n"
            f"**Overall** {progress_bar(c.get('overall', 0))}"
        )

        rows = [
            ("🏰", "Defenses",   "defenses"),
            ("🦸", "Heroes",     "heroes"),
            ("🔬", "Laboratory", "laboratory"),
            ("🧱", "Walls",      "walls"),
            ("🐾", "Pets",       "pets"),
            ("🔩", "Equipment",  "equipment"),
            ("🏗️", "Buildings",  "buildings"),
            ("💣", "Traps",      "traps"),
        ]
        lines = []
        for icon, label, key in rows:
            pct = c.get(key, 0)
            bar = mini_bar(pct)
            lines.append(f"{icon} **{label:<12}** `{bar}` **{pct:.1f}%**")
        embed.add_field(name="📊 Category Breakdown", value="\n".join(lines), inline=False)
        embed.set_footer(text="Use the dropdown below to dive into each category")
        return embed

    def _heroes_pets(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        th_icon = TH_ICONS.get(th, "🏰")
        embed = base_embed(
            title=f"{th_icon} Heroes & Pets — {p.get('name')}",
            color=PURPLE,
        )
        hero_lines = []
        for hero in p.get("heroes", []):
            name = hero["name"]
            lv = hero.get("level", 0)
            max_lv = hero.get("maxLevel", lv)
            icon = HERO_ICONS.get(name, "🦸")
            bar = mini_bar(_safe_pct(lv, max_lv))
            hero_lines.append(f"{icon} **{name}** `{lv}/{max_lv}` `{bar}`")
        embed.add_field(
            name="🦸 Heroes",
            value="\n".join(hero_lines) if hero_lines else "*None unlocked*",
            inline=False,
        )

        pet_names = {
            "L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn",
            "Frosty", "Diggy", "Poison Lizard", "Phoenix", "Spirit Fox", "Angry Jelly",
        }
        pet_lines = []
        for troop in p.get("troops", []):
            if troop.get("name") in pet_names:
                name = troop["name"]
                lv = troop.get("level", 0)
                max_lv = troop.get("maxLevel", lv)
                bar = mini_bar(_safe_pct(lv, max_lv))
                pet_lines.append(f"🐾 **{name}** `{lv}/{max_lv}` `{bar}`")
        embed.add_field(
            name="🐾 Pets",
            value="\n".join(pet_lines) if pet_lines else "*None unlocked*",
            inline=False,
        )

        embed.set_footer(text=f"TH{th} • Heroes & Pets")
        return embed

    def _equipment(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        embed = base_embed(
            title=f"🔩 Hero Equipment — {p.get('name')}",
            color=ORANGE,
        )
        equip = p.get("heroEquipment", [])
        if not equip:
            embed.description = "*No equipment found.*"
            return embed

        # Group by hero
        hero_equip: dict = {}
        for e in equip:
            hero_name = e.get("hero", "Other")
            hero_equip.setdefault(hero_name, []).append(e)

        for hero, items in hero_equip.items():
            icon = HERO_ICONS.get(hero, "🦸")
            lines = []
            for item in items:
                name = item["name"]
                lv = item.get("level", 0)
                max_lv = item.get("maxLevel", 18)
                bar = mini_bar(_safe_pct(lv, max_lv))
                lines.append(f"  🔩 **{name}** `{lv}/{max_lv}` `{bar}`")
            embed.add_field(
                name=f"{icon} {hero}",
                value="\n".join(lines),
                inline=False,
            )
        embed.set_footer(text=f"TH{th} • Hero Equipment")
        return embed

    def _laboratory(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        embed = base_embed(
            title=f"🔬 Laboratory — {p.get('name')}",
            color=BLUE,
        )
        home_troops = [t for t in p.get("troops", []) if t.get("village") == "home"]
        spells = p.get("spells", [])
        sieges = [t for t in p.get("troops", []) if t.get("village") == "home" and t.get("isSuperTroop")]

        troop_lines = []
        for t in home_troops[:15]:
            lv = t.get("level", 0)
            max_lv = t.get("maxLevel", lv)
            bar = mini_bar(_safe_pct(lv, max_lv))
            troop_lines.append(f"⚔️ **{t['name']}** `{lv}/{max_lv}` `{bar}`")
        if troop_lines:
            embed.add_field(name="⚔️ Troops", value="\n".join(troop_lines), inline=True)

        spell_lines = []
        for s in spells:
            lv = s.get("level", 0)
            max_lv = s.get("maxLevel", lv)
            bar = mini_bar(_safe_pct(lv, max_lv))
            spell_lines.append(f"🧪 **{s['name']}** `{lv}/{max_lv}` `{bar}`")
        if spell_lines:
            embed.add_field(name="🧪 Spells", value="\n".join(spell_lines), inline=True)

        embed.set_footer(text=f"TH{th} • Laboratory")
        return embed

    def _defenses(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        embed = base_embed(
            title=f"🏰 Defenses — {p.get('name')}",
            color=RED,
        )
        pct = self.completion.get("defenses", 0)
        embed.description = f"**Completion** {progress_bar(pct)}"
        embed.add_field(
            name="📌 Note",
            value="Detailed building-level breakdown requires the full building API endpoint.\nUpgrades are tracked automatically by the scanner.",
            inline=False,
        )
        embed.set_footer(text=f"TH{th} • Defenses")
        return embed

    def _buildings(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        embed = base_embed(
            title=f"🏗️ Buildings — {p.get('name')}",
            color=GREEN,
        )
        pct = self.completion.get("buildings", 0)
        trap_pct = self.completion.get("traps", 0)
        embed.description = (
            f"**Buildings** {progress_bar(pct)}\n"
            f"**Traps** {progress_bar(trap_pct)}"
        )
        embed.set_footer(text=f"TH{th} • Buildings & Traps")
        return embed

    def _walls(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        embed = base_embed(
            title=f"🧱 Walls — {p.get('name')}",
            color=0x8B7355,
        )
        pct = self.completion.get("walls", 0)
        embed.description = f"**Walls** {progress_bar(pct)}"

        # Wall Buster achievement for approximate count
        wall_ach = next(
            (a for a in p.get("achievements", []) if a.get("name") == "Wall Buster"),
            None,
        )
        if wall_ach:
            embed.add_field(
                name="🏆 Wall Buster Achievement",
                value=f"**{wall_ach.get('value', 0):,}** / **{wall_ach.get('target', 0):,}**",
            )
        embed.set_footer(text=f"TH{th} • Walls")
        return embed

    def _remaining(self) -> discord.Embed:
        p = self.player
        th = p.get("townHallLevel", 0)
        remaining = self.completion.get("remaining", [])
        embed = base_embed(
            title=f"📋 Remaining Upgrades — {p.get('name')}",
            color=GOLD,
        )
        if not remaining:
            embed.description = "✅ **Village is complete!** Nothing left to upgrade."
        else:
            lines = [f"• {r}" for r in remaining]
            embed.description = "\n".join(lines)
        embed.set_footer(text=f"TH{th} • {len(remaining)} items remaining")
        return embed


def _safe_pct(current, maximum):
    if not maximum:
        return 100.0
    return min(100.0, (current / maximum) * 100)


# ── Cog ───────────────────────────────────────────────────────────────────────
class VillageCog(commands.Cog, name="Village"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    async def _resolve_player(self, interaction: discord.Interaction, member: discord.Member = None):
        """Resolve a player tag from a Discord member or the command author."""
        target = member or interaction.user
        link = await self.db.get_link_by_discord(target.id)
        if not link:
            return None, target
        return link["player_tag"], target

    # ── /village ──────────────────────────────────────────────────────────────
    @app_commands.command(name="village", description="View village completion breakdown")
    @app_commands.describe(member="View another member's village (optional)")
    async def village(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        tag, target = await self._resolve_player(interaction, member)
        if not tag:
            await interaction.followup.send(
                embed=error_embed(
                    f"{target.mention} hasn't linked a CoC account yet.\nUse `/link` to link."
                )
            )
            return

        try:
            player = await self.api.get_player(tag)
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        completion = calculate_completion(player)
        view = CompletionTabsView(player, completion, interaction.user.id)
        # Build overview tab as initial
        embed = view._overview()
        await interaction.followup.send(embed=embed, view=view)

    # ── /progress ─────────────────────────────────────────────────────────────
    @app_commands.command(name="progress", description="View your monthly and weekly upgrade progress")
    @app_commands.describe(member="View another member's progress (optional)")
    async def progress(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        tag, target = await self._resolve_player(interaction, member)
        if not tag:
            await interaction.followup.send(
                embed=error_embed(f"{target.mention} hasn't linked a CoC account.")
            )
            return

        try:
            player = await self.api.get_player(tag)
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        now = datetime.utcnow()
        month = now.strftime("%Y-%m")
        current_completion = calculate_completion(player)
        monthly = await self.db.get_monthly_snapshot(tag, month)

        embed = base_embed(
            title=f"📈 Progress Report — {player['name']}",
            color=GREEN,
        )
        th = player.get("townHallLevel", 0)
        th_icon = TH_ICONS.get(th, "🏰")
        embed.description = f"{th_icon} **TH{th}** • `{tag}`"

        # Monthly comparison
        if monthly:
            start_pct = monthly["completion_pct"] or 0
            current_pct = current_completion["overall"]
            delta = current_pct - start_pct
            sign = "+" if delta >= 0 else ""
            embed.add_field(
                name=f"📅 Monthly Progress ({month})",
                value=(
                    f"**Start of month:** {start_pct:.1f}%\n"
                    f"**Current:** {current_pct:.1f}%\n"
                    f"**Change:** `{sign}{delta:.1f}%`"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="📅 Monthly Progress",
                value="*Snapshot not yet available for this month.*",
                inline=False,
            )

        # Recent upgrades (last 7 days from log)
        recent = await self.db.get_upgrade_log(tag, limit=15)
        if recent:
            lines = []
            for row in recent[:10]:
                lines.append(
                    f"• **{row['item_name']}** `{row['old_level']} → {row['new_level']}` "
                    f"<t:{_iso_to_ts(row['detected_at'])}:R>"
                )
            embed.add_field(
                name="🔧 Recent Upgrades",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="🔧 Recent Upgrades",
                value="*No upgrades recorded yet.*",
                inline=False,
            )

        embed.set_footer(text="Powered by the automatic scanner")
        await interaction.followup.send(embed=embed)


def _iso_to_ts(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso)
        return int(dt.timestamp())
    except Exception:
        return 0


async def setup(bot):
    await bot.add_cog(VillageCog(bot))
