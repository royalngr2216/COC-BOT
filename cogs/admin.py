"""
cogs/admin.py — Admin settings: channels, scan interval, notification toggles, manual scan.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    base_embed, error_embed, success_embed, info_embed,
    GOLD, BLUE, GREEN, RED, ORANGE,
)


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    admin_group = app_commands.Group(
        name="admin",
        description="Admin-only bot configuration",
        default_permissions=discord.Permissions(administrator=True),
    )

    @admin_group.command(name="status", description="Show current bot configuration")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = await self.db.get_config()
        if not cfg:
            await interaction.followup.send(embed=error_embed("Bot not set up. Run `/setup` first."))
            return

        def ch(cid):
            return f"<#{cid}>" if cid else "❌ Not set"

        embed = base_embed(title="⚙️ Bot Configuration", color=GOLD, timestamp=False)
        embed.add_field(name="🏰 Clan",        value=f"`{cfg['clan_tag'] or 'Not set'}`", inline=True)
        embed.add_field(name="⏱️ Scan",         value=f"**{cfg['scan_interval']} min**",   inline=True)
        embed.add_field(
            name="📢 Channels",
            value=(
                f"🏰 Village: {ch(cfg['village_channel'])}\n"
                f"⚔️ War: {ch(cfg['war_channel'])}\n"
                f"📋 Logs: {ch(cfg['logs_channel'])}\n"
                f"⏰ Reminders: {ch(cfg['reminder_channel'])}\n"
                f"👥 Tracker: {ch(cfg['tracker_channel'])}"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔔 Global Toggles",
            value=(
                f"📬 DMs: {'🟢' if cfg['dm_notifications'] else '🔴'} | "
                f"🏰 Village: {'🟢' if cfg['village_updates'] else '🔴'} | "
                f"⚔️ War: {'🟢' if cfg['war_reminders'] else '🔴'} | "
                f"🏆 Milestones: {'🟢' if cfg['milestone_notifs'] else '🔴'}"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    @admin_group.command(name="channel", description="Set a notification channel")
    @app_commands.describe(channel_type="Which channel to configure", channel="The Discord channel")
    @app_commands.choices(channel_type=[
        app_commands.Choice(name="Village Updates", value="village_channel"),
        app_commands.Choice(name="War Channel",     value="war_channel"),
        app_commands.Choice(name="Logs",            value="logs_channel"),
        app_commands.Choice(name="War Reminders",   value="reminder_channel"),
        app_commands.Choice(name="Member Tracker",  value="tracker_channel"),
    ])
    async def set_channel(self, interaction: discord.Interaction,
                          channel_type: app_commands.Choice[str], channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        await self.db.set_config(**{channel_type.value: channel.id})
        await interaction.followup.send(
            embed=success_embed(f"**{channel_type.name}** set to {channel.mention}", title="✅ Channel Updated")
        )

    @admin_group.command(name="interval", description="Set village scan interval (10–120 minutes)")
    @app_commands.describe(minutes="Scan interval in minutes")
    async def set_interval(self, interaction: discord.Interaction, minutes: int):
        await interaction.response.defer(ephemeral=True)
        if not (10 <= minutes <= 120):
            await interaction.followup.send(embed=error_embed("Interval must be 10–120 minutes."))
            return
        await self.db.set_config(scan_interval=minutes)
        await interaction.followup.send(
            embed=success_embed(f"Scanner runs every **{minutes} minutes**.", title="⏱️ Updated")
        )

    @admin_group.command(name="toggle", description="Enable/disable a global notification type")
    @app_commands.describe(setting="Which setting to toggle")
    @app_commands.choices(setting=[
        app_commands.Choice(name="DM Notifications", value="dm_notifications"),
        app_commands.Choice(name="Village Updates",  value="village_updates"),
        app_commands.Choice(name="War Reminders",    value="war_reminders"),
        app_commands.Choice(name="Milestones",       value="milestone_notifs"),
    ])
    async def toggle(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        cfg = await self.db.get_config()
        if not cfg:
            await interaction.followup.send(embed=error_embed("Bot not set up."))
            return
        new_val = 0 if cfg[setting.value] else 1
        await self.db.set_config(**{setting.value: new_val})
        state = "🟢 **Enabled**" if new_val else "🔴 **Disabled**"
        await interaction.followup.send(
            embed=success_embed(f"**{setting.name}** is now {state}", title="🔔 Updated")
        )

    @admin_group.command(name="scan", description="Manually trigger a village scan now")
    async def scan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = await self.db.get_config()
        if not cfg or not cfg["setup_complete"]:
            await interaction.followup.send(embed=error_embed("Bot not set up."))
            return
        await interaction.followup.send(
            embed=info_embed("Scanner triggered in the background.", title="🔍 Scanning…")
        )
        scanner_cog = self.bot.get_cog("Scanner")
        if scanner_cog:
            asyncio.create_task(scanner_cog.trigger_scan())

    @admin_group.command(name="memberlog", description="View recent member events")
    async def memberlog(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        events = await self.db.get_member_log(limit=20)
        if not events:
            await interaction.followup.send(embed=info_embed("No events yet.", title="📋 Member Log"))
            return
        icons = {"joined": "📥", "left": "📤", "promoted": "⬆️", "demoted": "⬇️"}
        embed = base_embed(title="📋 Member Event Log", color=BLUE)
        lines = [f"{icons.get(e['event_type'],'❓')} **{e['player_name']}** — `{e['event_type']}`" for e in events]
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    @admin_group.command(name="resetclan", description="Reset clan configuration (keeps history)")
    async def resetclan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = ConfirmResetView(interaction.user.id)
        await interaction.followup.send(
            embed=base_embed(
                title="⚠️ Confirm Reset",
                description="This clears the clan tag and requires `/setup` again. History is kept. Continue?",
                color=RED, timestamp=False,
            ),
            view=view,
        )


class ConfirmResetView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=30)
        self.user_id = user_id

    @discord.ui.button(label="Yes, Reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return
        await interaction.client.db.set_config(clan_tag=None, setup_complete=0)
        self.stop()
        await interaction.response.edit_message(
            embed=success_embed("Clan reset. Run `/setup` to reconfigure.", title="♻️ Reset"), view=None
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            embed=info_embed("Reset cancelled.", title="✅ Cancelled"), view=None
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
