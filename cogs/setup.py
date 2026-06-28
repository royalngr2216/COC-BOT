"""
cogs/setup.py — One-time clan setup and player linking.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    error_embed, success_embed, info_embed, base_embed,
    GOLD, BLUE, GREEN, RED,
)
from utils.coc_api import CoCAPIError


class SetupCog(commands.Cog, name="Setup"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def api(self):
        return self.bot.coc_api

    # ── /setup clan ───────────────────────────────────────────────────────────
    @app_commands.command(name="setup", description="Initial bot setup (Owner only)")
    @app_commands.describe(clan_tag="Your clan's tag (e.g. #ABC123)")
    @app_commands.default_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction, clan_tag: str):
        await interaction.response.defer(ephemeral=True)

        cfg = await self.db.get_config()
        if cfg and cfg["setup_complete"]:
            embed = error_embed(
                "This bot is already set up. Use `/admin` to modify settings.",
                title="⚙️ Already Configured",
            )
            await interaction.followup.send(embed=embed)
            return

        # Validate clan tag
        try:
            clan = await self.api.get_clan(clan_tag)
        except CoCAPIError as e:
            await interaction.followup.send(
                embed=error_embed(f"Could not find clan `{clan_tag}`.\n`{e.message}`")
            )
            return

        await self.db.set_config(
            clan_tag=clan_tag.upper(),
            guild_id=interaction.guild_id,
            setup_complete=1,
        )

        embed = base_embed(
            title="🏰 Clan Linked Successfully!",
            description=(
                f"**{clan['name']}** `{clan_tag.upper()}`\n"
                f"Level **{clan.get('clanLevel')}** • "
                f"**{clan.get('members')}/50** members\n\n"
                "Use `/admin channel` to configure notification channels.\n"
                "Members can now link their accounts with `/link`."
            ),
            color=GOLD,
            thumbnail=clan.get("badgeUrls", {}).get("medium"),
        )
        await interaction.followup.send(embed=embed)

    # ── /link ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="link", description="Link your Discord account to your CoC player tag")
    @app_commands.describe(
        player_tag="Your player tag (e.g. #ABCDEF)",
        api_token="Your in-game API token (Profile → Settings → More Settings → API Token)",
    )
    async def link(
        self,
        interaction: discord.Interaction,
        player_tag: str,
        api_token: str,
    ):
        await interaction.response.defer(ephemeral=True)

        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(
                embed=error_embed("The bot hasn't been set up yet. Ask an admin to run `/setup`.")
            )
            return

        # Verify player exists
        try:
            player = await self.api.get_player(player_tag)
        except CoCAPIError as e:
            await interaction.followup.send(
                embed=error_embed(f"Player `{player_tag}` not found.\n`{e.message}`")
            )
            return

        # Verify player is in the clan
        clan_tag = cfg["clan_tag"]
        player_clan = player.get("clan", {}).get("tag", "").upper()
        if player_clan != clan_tag.upper():
            await interaction.followup.send(
                embed=error_embed(
                    f"You must be a member of **{cfg['clan_tag']}** to link here.\n"
                    f"Your current clan: `{player_clan or 'None'}`"
                )
            )
            return

        # Verify token
        valid = await self.api.verify_player_token(player_tag, api_token)
        if not valid:
            await interaction.followup.send(
                embed=error_embed(
                    "Invalid API token. Please copy it from:\n"
                    "**Profile → Settings ⚙️ → More Settings → API Token**"
                )
            )
            return

        await self.db.link_player(
            interaction.user.id,
            player_tag.upper(),
            player["name"],
        )

        embed = success_embed(
            f"**{player['name']}** `{player_tag.upper()}` linked to your Discord account!\n\n"
            f"🏰 TH **{player.get('townHallLevel')}** • "
            f"🏆 **{player.get('trophies', 0):,}** trophies\n\n"
            "You'll now receive village progress notifications.",
            title="🔗 Account Linked!",
        )
        await interaction.followup.send(embed=embed)

    # ── /unlink ───────────────────────────────────────────────────────────────
    @app_commands.command(name="unlink", description="Unlink your Discord account from CoC")
    async def unlink(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        link = await self.db.get_link_by_discord(interaction.user.id)
        if not link:
            await interaction.followup.send(
                embed=error_embed("You don't have an account linked.")
            )
            return

        await self.db.conn.execute(
            "DELETE FROM player_links WHERE discord_id=?", (interaction.user.id,)
        )
        await self.db.conn.commit()
        await interaction.followup.send(
            embed=success_embed(
                f"Account `{link['player_tag']}` has been unlinked.",
                title="🔓 Account Unlinked",
            )
        )

    # ── /whois ────────────────────────────────────────────────────────────────
    @app_commands.command(name="whois", description="Check which CoC account a Discord user is linked to")
    @app_commands.describe(member="The Discord member to check")
    async def whois(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        link = await self.db.get_link_by_discord(target.id)

        if not link:
            await interaction.followup.send(
                embed=info_embed(
                    f"{target.mention} has not linked a CoC account.",
                    title="🔍 Account Lookup",
                )
            )
            return

        embed = base_embed(
            title="🔍 Account Lookup",
            description=(
                f"**Discord:** {target.mention}\n"
                f"**Player:** {link['player_name']}\n"
                f"**Tag:** `{link['player_tag']}`\n"
                f"**Linked:** <t:{int(discord.utils.utcnow().timestamp())}:R>"
            ),
            color=BLUE,
            thumbnail=target.display_avatar.url,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SetupCog(bot))
