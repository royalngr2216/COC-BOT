"""
utils/embeds.py — Premium embed factory for consistent, beautiful Discord embeds.

Color palette:
  GOLD    #F5A623  — achievements, milestones, gold tier
  BLUE    #5B8DEF  — info, clan, general
  GREEN   #43B581  — success, upgrades, progress
  RED     #F04747  — warnings, missed attacks, left clan
  PURPLE  #9B59B6  — heroes, equipment, premium
  ORANGE  #E67E22  — war, attack, urgent
  TEAL    #1ABC9C  — village progress, completion
  DARK    #2F3136  — neutral / dark backgrounds
"""

import discord

# ── Palette ───────────────────────────────────────────────────────────────────
GOLD   = 0xF5A623
BLUE   = 0x5B8DEF
GREEN  = 0x43B581
RED    = 0xF04747
PURPLE = 0x9B59B6
ORANGE = 0xE67E22
TEAL   = 0x1ABC9C
DARK   = 0x2F3136
WHITE  = 0xFFFFFF

# ── Town Hall icons ───────────────────────────────────────────────────────────
TH_ICONS = {
    1: "🏠", 2: "🏚️", 3: "🏡", 4: "🏘️", 5: "🏗️",
    6: "🏛️", 7: "🏯", 8: "🏰", 9: "⚔️", 10: "🌟",
    11: "💥", 12: "🔥", 13: "🌩️", 14: "💎", 15: "🌠",
    16: "👑",
}

LEAGUE_ICONS = {
    "Bronze League I": "🥉",   "Bronze League II": "🥉",   "Bronze League III": "🥉",
    "Silver League I": "🥈",   "Silver League II": "🥈",   "Silver League III": "🥈",
    "Gold League I": "🥇",     "Gold League II": "🥇",     "Gold League III": "🥇",
    "Crystal League I": "💎",  "Crystal League II": "💎",  "Crystal League III": "💎",
    "Master League I": "🏆",   "Master League II": "🏆",   "Master League III": "🏆",
    "Champion League I": "🌟", "Champion League II": "🌟", "Champion League III": "🌟",
    "Titan League I": "⚡",    "Titan League II": "⚡",    "Titan League III": "⚡",
    "Legend League": "👑",     "Unranked": "⬜",
}

ROLE_ICONS = {
    "leader": "👑",
    "coLeader": "🔱",
    "admin": "⭐",
    "member": "🏅",
}

HERO_ICONS = {
    "Barbarian King": "⚔️",
    "Archer Queen": "🏹",
    "Grand Warden": "📖",
    "Royal Champion": "🛡️",
    "Minion Prince": "😈",
}

# ── Progress bar ──────────────────────────────────────────────────────────────
def progress_bar(pct: float, length: int = 12) -> str:
    """Return a Discord-friendly progress bar string."""
    filled = round(pct / 100 * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"`{bar}` **{pct:.1f}%**"


def mini_bar(pct: float, length: int = 8) -> str:
    filled = round(pct / 100 * length)
    empty = length - filled
    return "█" * filled + "░" * empty


# ── Base embed factory ────────────────────────────────────────────────────────
def base_embed(
    title: str = None,
    description: str = None,
    color: int = BLUE,
    thumbnail: str = None,
    footer: str = None,
    timestamp: bool = True,
) -> discord.Embed:
    from datetime import datetime, timezone
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )
    if timestamp:
        embed.timestamp = datetime.now(timezone.utc)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if footer:
        embed.set_footer(text=footer)
    return embed


# ── Error / success embeds ────────────────────────────────────────────────────
def error_embed(message: str, title: str = "❌ Error") -> discord.Embed:
    return base_embed(title=title, description=message, color=RED, timestamp=False)


def success_embed(message: str, title: str = "✅ Success") -> discord.Embed:
    return base_embed(title=title, description=message, color=GREEN, timestamp=False)


def info_embed(message: str, title: str = "ℹ️ Info") -> discord.Embed:
    return base_embed(title=title, description=message, color=BLUE, timestamp=False)


def warning_embed(message: str, title: str = "⚠️ Warning") -> discord.Embed:
    return base_embed(title=title, description=message, color=ORANGE, timestamp=False)


# ── Upgrade notification embed ────────────────────────────────────────────────
def upgrade_embed(player_name: str, upgrades: list, th_level: int = 0) -> discord.Embed:
    """
    upgrades: list of dicts with keys: type, name, old, new
    """
    th_icon = TH_ICONS.get(th_level, "🏰")
    color = _upgrade_color(upgrades)

    lines = []
    for u in upgrades:
        icon = _upgrade_icon(u["type"], u["name"])
        lines.append(f"{icon} **{u['name']}** `{u['old']}` → `{u['new']}`")

    # Wall summary
    wall_count = sum(1 for u in upgrades if u["type"] == "wall")
    if wall_count > 0:
        lines = [l for l in lines if "wall" not in l.lower()]
        lines.append(f"🧱 **{wall_count} Wall{'s' if wall_count > 1 else ''} upgraded**")

    embed = base_embed(
        title=f"{th_icon} Village Progress — {player_name}",
        description="\n".join(lines),
        color=color,
    )

    # Milestone badge
    milestones = _detect_milestones(upgrades)
    if milestones:
        embed.add_field(
            name="🏆 Milestones Reached",
            value="\n".join(milestones),
            inline=False,
        )

    embed.set_footer(text="Detected just now • Automatic Scanner")
    return embed


def _upgrade_color(upgrades: list) -> int:
    types = {u["type"] for u in upgrades}
    if "hero" in types:
        return PURPLE
    if "th" in types:
        return GOLD
    if "pet" in types:
        return TEAL
    if "equipment" in types:
        return ORANGE
    if "troop" in types or "spell" in types:
        return BLUE
    return GREEN


def _upgrade_icon(utype: str, name: str = "") -> str:
    icons = {
        "building": "🏗️",
        "defense": "🏰",
        "hero": HERO_ICONS.get(name, "🦸"),
        "troop": "⚔️",
        "spell": "🧪",
        "siege": "🐏",
        "pet": "🐾",
        "equipment": "🔩",
        "wall": "🧱",
        "th": "🏛️",
        "lab": "🔬",
        "trap": "💣",
    }
    return icons.get(utype, "🔧")


def _detect_milestones(upgrades: list) -> list:
    milestones = []
    for u in upgrades:
        # Hero maxed (level varies by TH, show when reaching known max levels)
        if u["type"] == "hero":
            max_levels = {
                "Barbarian King": 95, "Archer Queen": 95,
                "Grand Warden": 65, "Royal Champion": 45, "Minion Prince": 15,
            }
            if u["name"] in max_levels and u["new"] >= max_levels[u["name"]]:
                icon = HERO_ICONS.get(u["name"], "🦸")
                milestones.append(f"{icon} **{u['name']} MAXED!** 🎉")

        # TH upgrade
        if u["type"] == "th":
            milestones.append(f"🏛️ **Town Hall {u['new']} unlocked!** 🎉")

        # Pet unlocked (level 1)
        if u["type"] == "pet" and u["old"] == 0:
            milestones.append(f"🐾 **{u['name']} unlocked!** 🎉")

        # Troop unlocked
        if u["type"] in ("troop", "spell") and u["old"] == 0:
            milestones.append(f"⚗️ **{u['name']} unlocked!** 🎉")

        # Equipment maxed
        if u["type"] == "equipment" and u["new"] >= 18:
            milestones.append(f"🔩 **{u['name']} equipment maxed!** 🎉")

    # Wall milestones
    # (handled externally based on total count)
    return milestones


# ── Milestone-only embed ──────────────────────────────────────────────────────
def milestone_embed(player_name: str, milestone: str, th_level: int = 0) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Milestone Achieved!",
        description=f"**{player_name}** {milestone}",
        color=GOLD,
    )
    embed.set_footer(text="Automatic Scanner")
    return embed


# ── Village completion embed ──────────────────────────────────────────────────
def completion_embed(player_data: dict, completion: dict) -> discord.Embed:
    th = player_data.get("townHallLevel", 0)
    th_icon = TH_ICONS.get(th, "🏰")
    name = player_data.get("name", "Unknown")
    league = player_data.get("league", {}).get("name", "Unranked")
    l_icon = LEAGUE_ICONS.get(league, "⬜")

    embed = base_embed(
        title=f"{th_icon} Village Completion — {name}",
        color=TEAL,
    )

    overall = completion.get("overall", 0)
    embed.description = f"{l_icon} **{league}**\n\n**Overall** {progress_bar(overall)}"

    categories = [
        ("🏰", "Defenses",   "defenses"),
        ("🦸", "Heroes",     "heroes"),
        ("🔬", "Laboratory", "laboratory"),
        ("🧱", "Walls",      "walls"),
        ("🐾", "Pets",       "pets"),
        ("🔩", "Equipment",  "equipment"),
        ("🏗️", "Buildings",  "buildings"),
        ("💣", "Traps",      "traps"),
    ]

    rows = []
    for icon, label, key in categories:
        pct = completion.get(key, 0)
        bar = mini_bar(pct)
        rows.append(f"{icon} **{label:<12}** `{bar}` {pct:.1f}%")

    embed.add_field(name="📊 Breakdown", value="\n".join(rows), inline=False)

    # Remaining
    remaining = completion.get("remaining", [])
    if remaining:
        rem_lines = [f"• {r}" for r in remaining[:8]]
        if len(remaining) > 8:
            rem_lines.append(f"*...and {len(remaining)-8} more*")
        embed.add_field(
            name="📋 Still Needed",
            value="\n".join(rem_lines),
            inline=False,
        )

    embed.set_footer(text=f"TH{th} • Snapshot updated just now")
    return embed
