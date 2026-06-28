"""
utils/pagination.py — Reusable paginator for Discord embeds using buttons.
"""

import discord
from typing import List


class PaginatorView(discord.ui.View):
    """
    A simple paginator that shows one embed per page with Prev/Next buttons.
    Auto-disables when the interaction times out.
    """

    def __init__(self, pages: List[discord.Embed], user_id: int, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.user_id = user_id
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1
        # Update page counter label
        self.page_label.label = f"{self.current + 1} / {len(self.pages)}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the command author can navigate pages.", ephemeral=True
            )
            return
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the command author can navigate pages.", ephemeral=True
            )
            return
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def send_paginated(
    interaction: discord.Interaction,
    pages: List[discord.Embed],
    ephemeral: bool = False,
):
    """Send a paginated embed response."""
    if not pages:
        await interaction.followup.send("No data to display.", ephemeral=True)
        return
    if len(pages) == 1:
        await interaction.followup.send(embed=pages[0], ephemeral=ephemeral)
        return
    view = PaginatorView(pages, interaction.user.id)
    await interaction.followup.send(embed=pages[0], view=view, ephemeral=ephemeral)
