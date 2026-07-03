"""
cogs/cwl.py — Clan War League (CWL): group overview, round-by-round opponent
breakdowns (who we play each round, their TH composition, stars/destruction),
and full group standings — all with premium embeds + a Pillow scoreboard image.
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed, info_embed,
    GOLD, BLUE, GREEN, RED, ORANGE, TEAL, PURPLE,
    TH_ICONS,
)
from utils.coc_api import CoCAPIError
from utils import images as img

log = logging.getLogger("cwl")

STATE_LABELS = {
    "preparation": "🟠 Prep Day",
    "inWar": "🟢 Battle Day",
    "warEnded": "🔴 Ended",
    "notInWar": "⚪ Not Started",
}

CWL_STATE_LABELS = {
    "preparation": "📋 Roster Locked — Waiting for Round 1",
    "war": "⚔️ In Progress",
    "ended": "🏁 Season Ended",
}


def _th_comparison_lines(left: dict, right: dict) -> str:
    all_th = sorted(set(left) | set(right), reverse=True)
    if not all_th:
        return "*No composition data.*"
    lines = []
    for th in all_th[:10]:
        icon = TH_ICONS.get(th, "🏰")
        l, r = left.get(th, 0), right.get(th, 0)
        marker = " ⬅️" if l > r else (" ➡️" if r > l else "")
        lines.append(f"{icon} `TH{th:<2}` — **{l}** vs **{r}**{marker}")
    return "\n".join(lines)


def _result_icon(our_stars, opp_stars, our_dest, opp_dest, state) -> str:
    if state != "warEnded":
        return "⏳"
    if our_stars != opp_stars:
        return "✅" if our_stars > opp_stars else "❌"
    return "✅" if our_dest > opp_dest else ("❌" if our_dest < opp_dest else "🤝")


class RoundSelect(discord.ui.Select):
    def __init__(self, num_rounds: int, current: str):
        options = [discord.SelectOption(label="📊 Group Overview", value="overview", default=(current == "overview"))]
        for i in range(1, num_rounds + 1):
            options.append(discord.SelectOption(label=f"⚔️ Round {i}", value=f"round:{i}", default=(current == f"round:{i}")))
        options.append(discord.SelectOption(label="🏆 Standings", value="standings", default=(current == "standings")))
        super().__init__(placeholder="🗓️ Select CWL section…", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: "CWLView" = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return
        await view.switch(interaction, self.values[0])


class CWLView(discord.ui.View):
    def __init__(self, cog: "CWLCog", group: dict, our_tag: str, user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.group = group
        self.our_tag = our_tag
        self.user_id = user_id
        self.rounds = [r for r in group.get("rounds", []) if any(t != "#0" for t in r.get("warTags", []))]
        self.war_cache: dict = {}  # round_index -> war dict (our matchup for that round)
        self.current = "overview"
        self.add_item(RoundSelect(len(self.rounds), self.current))

    def _refresh_select(self):
        self.clear_items()
        self.add_item(RoundSelect(len(self.rounds), self.current))

    async def switch(self, interaction: discord.Interaction, value: str):
        self.current = value
        self._refresh_select()
        await interaction.response.defer()

        file = None
        if value == "overview":
            embed = self._overview_embed()
        elif value == "standings":
            await interaction.edit_original_response(
                embed=info_embed("Crunching group standings — fetching all round results…", title="🏆 Standings"),
                view=self,
                attachments=[],
            )
            embed, file = await self._standings_embed_and_image()
        elif value.startswith("round:"):
            round_num = int(value.split(":")[1])
            await interaction.edit_original_response(
                embed=info_embed(f"Loading Round {round_num} matchup…", title="⚔️ CWL Round"),
                view=self,
                attachments=[],
            )
            embed, file = await self._round_embed_and_image(round_num)
        else:
            embed = self._overview_embed()

        if file:
            await interaction.edit_original_response(embed=embed, view=self, attachments=[file])
        else:
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])

    # ── Overview ──────────────────────────────────────────────────────────
    def _overview_embed(self) -> discord.Embed:
        g = self.group
        state = g.get("state", "notInWar")
        our_clan = next((c for c in g.get("clans", []) if c.get("tag") == self.our_tag), {})
        num_clans = len(g.get("clans", []))

        embed = base_embed(
            title=f"🏆 Clan War League — {g.get('season', 'Current Season')}",
            description=(
                f"{CWL_STATE_LABELS.get(state, state)}\n"
                f"👥 **{num_clans}** clans in group • **{len(self.rounds)}** rounds generated"
            ),
            color=GOLD,
            thumbnail=our_clan.get("badgeUrls", {}).get("small"),
        )

        clan_lines = []
        for c in g.get("clans", []):
            marker = "👉 " if c.get("tag") == self.our_tag else "• "
            clan_lines.append(f"{marker}**{c.get('name')}** (Lv.{c.get('clanLevel', '?')}) `{c.get('tag')}`")
        if clan_lines:
            embed.add_field(name="🛡️ Clans in Group", value="\n".join(clan_lines[:8]), inline=False)

        our_th = img.th_counts_from_members(our_clan.get("members", []))
        if our_th:
            comp = ", ".join(f"TH{th}×{c}" for th, c in sorted(our_th.items(), reverse=True))
            embed.add_field(name="🏰 Our Roster Composition", value=comp, inline=False)

        embed.set_footer(text="Use the dropdown to view each round's opponent, or the full standings")
        return embed

    # ── Per-round matchup ─────────────────────────────────────────────────
    async def _get_round_war(self, round_num: int):
        if round_num in self.war_cache:
            return self.war_cache[round_num]
        round_obj = self.rounds[round_num - 1]
        war = None
        for tag in round_obj.get("warTags", []):
            if not tag or tag == "#0":
                continue
            try:
                candidate = await self.cog.api.get_cwl_war(tag)
            except CoCAPIError:
                continue
            c_tag = candidate.get("clan", {}).get("tag")
            o_tag = candidate.get("opponent", {}).get("tag")
            if self.our_tag in (c_tag, o_tag):
                if o_tag == self.our_tag:
                    # normalise so `clan` is always us
                    candidate["clan"], candidate["opponent"] = candidate["opponent"], candidate["clan"]
                war = candidate
                break
        self.war_cache[round_num] = war
        return war

    async def _round_embed_and_image(self, round_num: int):
        war = await self._get_round_war(round_num)
        if war is None:
            embed = info_embed(
                "This round hasn't been paired yet, or your clan has a bye this round.",
                title=f"⚔️ CWL Round {round_num}",
            )
            return embed, None

        us = war.get("clan", {})
        them = war.get("opponent", {})
        state = war.get("state", "notInWar")
        team_size = war.get("teamSize", 0)
        our_stars, opp_stars = us.get("stars", 0), them.get("stars", 0)
        our_dest, opp_dest = us.get("destructionPercentage", 0), them.get("destructionPercentage", 0)
        icon = _result_icon(our_stars, opp_stars, our_dest, opp_dest, state)

        left_th = img.th_counts_from_members(us.get("members", []))
        right_th = img.th_counts_from_members(them.get("members", []))

        embed = base_embed(
            title=f"{icon} CWL Round {round_num} — {STATE_LABELS.get(state, state)}",
            description=f"**{us.get('name')}** vs **{them.get('name')}**\n👥 **{team_size}v{team_size}**",
            color={"preparation": ORANGE, "inWar": GREEN, "warEnded": BLUE}.get(state, GOLD),
            thumbnail=us.get("badgeUrls", {}).get("small"),
        )
        embed.add_field(
            name=f"🏠 {us.get('name', 'Us')}",
            value=f"⭐ **{our_stars}** stars\n💥 **{our_dest:.2f}%** destruction\n⚔️ **{us.get('attacks', 0)}/{team_size}** attacks used",
            inline=True,
        )
        embed.add_field(
            name=f"🏴 {them.get('name', 'Them')}",
            value=f"⭐ **{opp_stars}** stars\n💥 **{opp_dest:.2f}%** destruction\n⚔️ **{them.get('attacks', 0)}/{team_size}** attacks used",
            inline=True,
        )
        embed.add_field(name="🏰 Town Hall Composition (Us vs Them)", value=_th_comparison_lines(left_th, right_th), inline=False)

        # Missing attacks (CWL = 1 attack per member)
        if state in ("inWar", "warEnded"):
            missing = [m["name"] for m in us.get("members", []) if not m.get("attacks")]
            if missing and state == "inWar":
                shown = ", ".join(missing[:10])
                more = f" *(+{len(missing) - 10} more)*" if len(missing) > 10 else ""
                embed.add_field(name=f"❌ Still Need to Attack ({len(missing)})", value=shown + more, inline=False)

        embed.set_image(url="attachment://cwl_banner.png")
        embed.set_footer(text=f"Season {self.group.get('season', '')} • Round {round_num}")

        file = None
        try:
            session = await self.cog.api.get_session()
            buf = await img.render_matchup_banner(
                session,
                left_name=us.get("name", "Us"), left_badge_url=us.get("badgeUrls", {}).get("medium"),
                left_stars=our_stars, left_destruction=our_dest, left_attacks_used=us.get("attacks", 0),
                left_th_counts=left_th,
                right_name=them.get("name", "Them"), right_badge_url=them.get("badgeUrls", {}).get("medium"),
                right_stars=opp_stars, right_destruction=opp_dest, right_attacks_used=them.get("attacks", 0),
                right_th_counts=right_th,
                team_size=team_size,
                state_label=STATE_LABELS.get(state, state).split(" ", 1)[-1],
                subtitle=f"CWL Round {round_num} of {len(self.rounds)}",
            )
            file = discord.File(buf, filename="cwl_banner.png")
        except Exception:
            log.exception("Failed to render CWL round banner")
            embed.set_image(url=None)

        return embed, file

    # ── Standings ─────────────────────────────────────────────────────────
    async def _standings_embed_and_image(self):
        stats = {c["tag"]: {
            "tag": c["tag"], "name": c["name"], "badge_url": c.get("badgeUrls", {}).get("medium"),
            "stars": 0, "destruction_total": 0.0, "wins": 0, "losses": 0, "ties": 0, "wars_counted": 0,
        } for c in self.group.get("clans", [])}

        all_tags = []
        for r in self.rounds:
            all_tags.extend([t for t in r.get("warTags", []) if t and t != "#0"])

        sem = asyncio.Semaphore(6)

        async def fetch(tag):
            async with sem:
                try:
                    return await self.cog.api.get_cwl_war(tag)
                except CoCAPIError:
                    return None

        wars = await asyncio.gather(*(fetch(t) for t in all_tags))

        for w in wars:
            if not w:
                continue
            for side, other in ((w.get("clan", {}), w.get("opponent", {})), (w.get("opponent", {}), w.get("clan", {}))):
                tag = side.get("tag")
                if tag not in stats:
                    continue
                stats[tag]["stars"] += side.get("stars", 0)
                stats[tag]["destruction_total"] += side.get("destructionPercentage", 0)
                stats[tag]["wars_counted"] += 1
                if w.get("state") == "warEnded":
                    s, os_ = side.get("stars", 0), other.get("stars", 0)
                    d, od = side.get("destructionPercentage", 0), other.get("destructionPercentage", 0)
                    if s > os_ or (s == os_ and d > od):
                        stats[tag]["wins"] += 1
                    elif s < os_ or (s == os_ and d < od):
                        stats[tag]["losses"] += 1
                    else:
                        stats[tag]["ties"] += 1

        ranked = sorted(
            stats.values(),
            key=lambda s: (s["stars"], s["destruction_total"]),
            reverse=True,
        )
        for r in ranked:
            r["destruction"] = r["destruction_total"] / r["wars_counted"] if r["wars_counted"] else 0.0

        embed = base_embed(
            title=f"🏆 CWL Standings — {self.group.get('season', '')}",
            color=GOLD,
        )
        lines = []
        for i, c in enumerate(ranked, start=1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`{i}.`")
            marker = " 👈" if c["tag"] == self.our_tag else ""
            lines.append(f"{medal} **{c['name']}** — ⭐{c['stars']} · {c['destruction']:.1f}% · {c['wins']}W-{c['losses']}L{marker}")
        embed.description = "\n".join(lines) if lines else "*No war data yet — check back once Round 1 kicks off.*"
        embed.set_image(url="attachment://cwl_standings.png")
        embed.set_footer(text="Rankings based on total stars, then average destruction")

        file = None
        try:
            session = await self.cog.api.get_session()
            buf = await img.render_cwl_standings(session, ranked, self.our_tag, season_label=self.group.get("season", ""))
            file = discord.File(buf, filename="cwl_standings.png")
        except Exception:
            log.exception("Failed to render CWL standings image")
            embed.set_image(url=None)

        return embed, file

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class CWLCog(commands.Cog, name="CWL"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    @app_commands.command(name="cwl", description="View Clan War League — group, rounds, opponents & standings")
    async def cwl(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up yet. Use `/setup`."))
            return

        try:
            group = await self.api.get_cwl_group(cfg["clan_tag"])
        except CoCAPIError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return

        if not group or group.get("state") in (None, "notInWar") or not group.get("clans"):
            await interaction.followup.send(
                embed=info_embed(
                    "Your clan isn't currently signed up for Clan War League.\n"
                    "CWL runs during the first ~9 days of each month — check back then!",
                    title="🏆 Clan War League",
                )
            )
            return

        view = CWLView(self, group, cfg["clan_tag"], interaction.user.id)
        embed = view._overview_embed()
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(CWLCog(bot))
