"""
cogs/notifications.py — Personal notification preference management.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import base_embed, error_embed, BLUE


class NotifToggleView(discord.ui.View):
    def __init__(self, link: dict, user_id: int):
        super().__init__(timeout=120)
        self.link = dict(link)
        self.user_id = user_id

    def _status(self, key: str) -> str:
        return "🟢 ON" if self.link.get(key, 1) else "🔴 OFF"

    def _build_embed(self) -> discord.Embed:
        embed = base_embed(
            title="🔔 Notification Settings",
            description="Toggle your personal notification preferences below.",
            color=BLUE,
            timestamp=False,
        )
        embed.add_field(
            name="Current Settings",
            value=(
                f"📬 **DM Notifications** — {self._status('dm_notifs')}\n"
                f"🏰 **Village Updates** — {self._status('village_notifs')}\n"
                f"⚔️ **War Reminders** — {self._status('war_notifs')}\n"
                f"🏆 **Milestone Alerts** — {self._status('milestone_notifs')}"
            ),
            inline=False,
        )
        embed.set_footer(text="Changes save instantly")
        return embed

    @discord.ui.button(label="Toggle DMs", style=discord.ButtonStyle.secondary, emoji="📬", row=0)
    async def toggle_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "dm_notifs")

    @discord.ui.button(label="Toggle Village Updates", style=discord.ButtonStyle.secondary, emoji="🏰", row=0)
    async def toggle_village(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "village_notifs")

    @discord.ui.button(label="Toggle War Reminders", style=discord.ButtonStyle.secondary, emoji="⚔️", row=1)
    async def toggle_war(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "war_notifs")

    @discord.ui.button(label="Toggle Milestones", style=discord.ButtonStyle.secondary, emoji="🏆", row=1)
    async def toggle_milestones(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "milestone_notifs")

    async def _toggle(self, interaction: discord.Interaction, key: str):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your settings.", ephemeral=True)
            return
        self.link[key] = 0 if self.link.get(key, 1) else 1
        await interaction.client.db.update_notif_settings(self.user_id, **{key: self.link[key]})
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


class NotificationsCog(commands.Cog, name="Notifications"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(name="notifications", description="Manage your personal notification preferences")
    async def notifications(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        link = await self.db.get_link_by_discord(interaction.user.id)
        if not link:
            await interaction.followup.send(
                embed=error_embed("You don't have a linked account. Use `/link` first.")
            )
            return
        view = NotifToggleView(link, interaction.user.id)
        await interaction.followup.send(embed=view._build_embed(), view=view)


async def setup(bot):
    await bot.add_cog(NotificationsCog(bot))
