"""
utils/images.py — Pillow-powered graphics engine.

Renders premium PNG banners for war / CWL matchups and CWL standings tables,
so commands can attach a real "scoreboard" image next to the embed instead
of relying on text alone.

Design language: dark navy card background, gold/orange CoC-flavoured
accents, circular clan badges, diverging TH-composition bar chart.

All network calls (badge fetches) are best-effort — if a badge can't be
downloaded (no internet, bad URL, timeout) we fall back to a generated
initial-letter avatar so rendering never fails.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Dict, List, Optional

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

log = logging.getLogger("images")

# ── Fonts ─────────────────────────────────────────────────────────────────────
_FONT_DIR = "assets/fonts"
_FONT_CACHE: Dict[str, ImageFont.FreeTypeFont] = {}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """weight: 'bold' | 'medium' | 'regular'"""
    key = f"{weight}:{size}"
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    filenames = {
        "bold": "Poppins-Bold.ttf",
        "medium": "Poppins-Medium.ttf",
        "regular": "Poppins-Regular.ttf",
    }
    path = f"{_FONT_DIR}/{filenames.get(weight, 'Poppins-Regular.ttf')}"
    try:
        font = ImageFont.truetype(path, size)
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# ── Palette ───────────────────────────────────────────────────────────────────
BG_TOP = (17, 20, 39)
BG_BOTTOM = (10, 12, 24)
PANEL = (26, 30, 54)
PANEL_LIGHT = (34, 39, 68)
GOLD = (245, 166, 35)
ORANGE = (230, 126, 34)
BLUE = (91, 141, 239)
GREEN = (67, 181, 129)
RED = (240, 71, 71)
WHITE = (245, 246, 250)
GREY = (150, 155, 175)
FAINT = (60, 65, 95)

TH_EMOJI_FALLBACK = "TH"


# ── Low-level drawing helpers ────────────────────────────────────────────────

def _vertical_gradient(w: int, h: int, top, bottom) -> Image.Image:
    base = Image.new("RGB", (w, h), top)
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        grad.putpixel((0, y), (r, g, b))
    grad = grad.resize((w, h))
    return grad


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _text_center(draw, cx, y, text, font, fill, anchor="mm"):
    draw.text((cx, y), text, font=font, fill=fill, anchor=anchor)


def _fit_text(draw, text, font_weight, max_size, min_size, max_width) -> ImageFont.FreeTypeFont:
    size = max_size
    while size > min_size:
        f = _font(font_weight, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return _font(font_weight, min_size)


def _circle_crop(im: Image.Image, diameter: int) -> Image.Image:
    im = ImageOps.fit(im.convert("RGBA"), (diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def _initial_avatar(name: str, diameter: int, color) -> Image.Image:
    im = Image.new("RGBA", (diameter, diameter), color + (255,))
    d = ImageDraw.Draw(im)
    letter = (name or "?").strip()[0].upper() if name else "?"
    font = _font("bold", int(diameter * 0.5))
    d.text((diameter / 2, diameter / 2 + diameter * 0.03), letter, font=font, fill=WHITE, anchor="mm")
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter, diameter), fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


async def _fetch_badge(session: Optional[aiohttp.ClientSession], url: Optional[str], diameter: int, fallback_name: str, fallback_color) -> Image.Image:
    if session and url:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    im = Image.open(io.BytesIO(data))
                    return _circle_crop(im, diameter)
        except Exception as e:
            log.debug(f"Badge fetch failed for {url}: {e}")
    return _initial_avatar(fallback_name, diameter, fallback_color)


def _ring(im: Image.Image, diameter: int, color, width: int = 5) -> Image.Image:
    canvas = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    canvas.paste(im, (0, 0), im)
    d = ImageDraw.Draw(canvas)
    d.ellipse((width // 2, width // 2, diameter - width // 2, diameter - width // 2), outline=color + (255,), width=width)
    return canvas


def _pill(draw, box, fill, text, font, text_color=WHITE, pad=0):
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill)
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    draw.text((cx, cy), text, font=font, fill=text_color, anchor="mm")


def _th_counts(members: List[dict]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for m in members or []:
        th = m.get("townHallLevel", 0)
        counts[th] = counts.get(th, 0) + 1
    return counts


def th_counts_from_members(members: List[dict]) -> Dict[int, int]:
    """Public helper: build a {th_level: count} dict from a war 'members' list."""
    return _th_counts(members)


# ── Main: matchup banner (used by /war and /cwl round view) ─────────────────

async def render_matchup_banner(
    session: Optional[aiohttp.ClientSession],
    *,
    left_name: str,
    left_badge_url: Optional[str],
    left_stars: float,
    left_destruction: float,
    left_attacks_used: int,
    left_th_counts: Dict[int, int],
    right_name: str,
    right_badge_url: Optional[str],
    right_stars: float,
    right_destruction: float,
    right_attacks_used: int,
    right_th_counts: Dict[int, int],
    team_size: int,
    state_label: str,
    subtitle: str = "",
    accent=ORANGE,
) -> io.BytesIO:
    W, H = 1200, 640
    img = _vertical_gradient(W, H, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Subtle accent glow bar at the very top
    draw.rectangle((0, 0, W, 6), fill=accent)

    # ── Header pill: state + subtitle ───────────────────────────────────────
    header_font = _font("bold", 26)
    header_text = state_label.upper()
    text_w = draw.textlength(header_text, font=header_font)
    pill_w = text_w + 64
    _pill(draw, (W / 2 - pill_w / 2, 26, W / 2 + pill_w / 2, 72), accent, header_text, header_font)

    if subtitle:
        sub_font = _font("medium", 20)
        draw.text((W / 2, 96), subtitle, font=sub_font, fill=GREY, anchor="mm")

    # ── Badges + names ────────────────────────────────────────────────────
    badge_d = 148
    badge_y = 140
    left_cx = 260
    right_cx = W - 260

    left_badge, right_badge = await asyncio.gather(
        _fetch_badge(session, left_badge_url, badge_d, left_name, (52, 62, 110)),
        _fetch_badge(session, right_badge_url, badge_d, right_name, (52, 62, 110)),
    )
    left_badge = _ring(left_badge, badge_d, GOLD, 5)
    right_badge = _ring(right_badge, badge_d, BLUE, 5)
    img.paste(left_badge, (int(left_cx - badge_d / 2), badge_y), left_badge)
    img.paste(right_badge, (int(right_cx - badge_d / 2), badge_y), right_badge)

    name_y = badge_y + badge_d + 34
    name_font_l = _fit_text(draw, left_name, "bold", 34, 18, 340)
    name_font_r = _fit_text(draw, right_name, "bold", 34, 18, 340)
    draw.text((left_cx, name_y), left_name, font=name_font_l, fill=WHITE, anchor="mm")
    draw.text((right_cx, name_y), right_name, font=name_font_r, fill=WHITE, anchor="mm")

    # ── VS divider + team size ───────────────────────────────────────────
    vs_font = _font("bold", 46)
    draw.text((W / 2, badge_y + badge_d / 2), "VS", font=vs_font, fill=accent, anchor="mm")
    size_font = _font("medium", 18)
    draw.text((W / 2, badge_y + badge_d / 2 + 44), f"{team_size}v{team_size}", font=size_font, fill=GREY, anchor="mm")

    # ── Stat rows: stars / destruction / attacks ─────────────────────────
    stat_y = name_y + 46
    label_font = _font("medium", 17)
    value_font = _font("bold", 30)

    def stat_block(cx, stars, dest, used):
        draw.text((cx, stat_y), f"⭐ {stars:g}", font=value_font, fill=GOLD, anchor="mm")
        draw.text((cx, stat_y + 38), f"{dest:.1f}% destruction", font=label_font, fill=GREY, anchor="mm")
        draw.text((cx, stat_y + 64), f"{used}/{team_size * 2} attacks used", font=label_font, fill=GREY, anchor="mm")

    stat_block(left_cx, left_stars, left_destruction, left_attacks_used)
    stat_block(right_cx, right_stars, right_destruction, right_attacks_used)

    # Leading indicator
    if left_stars != right_stars:
        leader_cx = left_cx if left_stars > right_stars else right_cx
        arrow_y = stat_y - 42
        draw.text((leader_cx, arrow_y), "▲ LEADING", font=_font("bold", 16), fill=GREEN, anchor="mm")

    # ── TH composition diverging bar chart ────────────────────────────────
    chart_top = stat_y + 100
    chart_bottom = H - 34
    draw.line((60, chart_top - 20, W - 60, chart_top - 20), fill=FAINT, width=1)
    draw.text((W / 2, chart_top - 2), "TOWN HALL COMPOSITION", font=_font("medium", 15), fill=GREY, anchor="mm")

    all_ths = sorted(set(left_th_counts) | set(right_th_counts), reverse=True)
    all_ths = all_ths[:8] if all_ths else []
    if all_ths:
        row_h = min(34, (chart_bottom - chart_top - 10) // max(len(all_ths), 1))
        row_h = max(row_h, 20)
        max_count = max(
            [left_th_counts.get(th, 0) for th in all_ths] + [right_th_counts.get(th, 0) for th in all_ths] + [1]
        )
        max_bar_w = 380
        cx = W / 2
        y = chart_top + 14
        th_font = _font("bold", 16)
        count_font = _font("medium", 15)
        for th in all_ths:
            lc = left_th_counts.get(th, 0)
            rc = right_th_counts.get(th, 0)
            lw = int((lc / max_count) * max_bar_w)
            rw = int((rc / max_count) * max_bar_w)
            bar_h = row_h - 8
            # left bar grows leftward from center
            if lw > 0:
                draw.rounded_rectangle((cx - 46 - lw, y, cx - 46, y + bar_h), radius=bar_h / 2, fill=GOLD)
                draw.text((cx - 46 - lw - 10, y + bar_h / 2), str(lc), font=count_font, fill=WHITE, anchor="rm")
            # right bar grows rightward
            if rw > 0:
                draw.rounded_rectangle((cx + 46, y, cx + 46 + rw, y + bar_h), radius=bar_h / 2, fill=BLUE)
                draw.text((cx + 46 + rw + 10, y + bar_h / 2), str(rc), font=count_font, fill=WHITE, anchor="lm")
            # TH label pill in the middle
            draw.text((cx, y + bar_h / 2), f"TH{th}", font=th_font, fill=WHITE, anchor="mm")
            y += row_h
    else:
        draw.text((W / 2, (chart_top + chart_bottom) / 2), "No composition data available", font=_font("regular", 18), fill=GREY, anchor="mm")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── CWL standings table ──────────────────────────────────────────────────────

async def render_cwl_standings(
    session: Optional[aiohttp.ClientSession],
    clans: List[dict],
    our_tag: str,
    season_label: str = "",
) -> io.BytesIO:
    """
    clans: list of dicts sorted by rank already, each with:
        tag, name, badge_url, stars, destruction, wins, losses
    """
    row_h = 74
    header_h = 120
    footer_pad = 24
    W = 1100
    H = header_h + row_h * len(clans) + footer_pad

    img = _vertical_gradient(W, H, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 6), fill=GOLD)

    draw.text((40, 34), "🏆 Clan War League — Group Standings", font=_font("bold", 30), fill=WHITE, anchor="lm")
    if season_label:
        draw.text((40, 70), season_label, font=_font("medium", 18), fill=GREY, anchor="lm")

    # Column headers
    col_rank_x = 60
    col_badge_x = 110
    col_name_x = 190
    col_stars_x = 740
    col_dest_x = 870
    col_record_x = 1010

    hy = header_h - 22
    hfont = _font("medium", 15)
    draw.text((col_rank_x, hy), "#", font=hfont, fill=GREY, anchor="lm")
    draw.text((col_name_x, hy), "CLAN", font=hfont, fill=GREY, anchor="lm")
    draw.text((col_stars_x, hy), "STARS", font=hfont, fill=GREY, anchor="lm")
    draw.text((col_dest_x, hy), "DEST%", font=hfont, fill=GREY, anchor="lm")
    draw.text((col_record_x, hy), "W-L", font=hfont, fill=GREY, anchor="lm")

    badge_d = 48
    y = header_h
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, c in enumerate(clans, start=1):
        is_us = c.get("tag") == our_tag
        row_box = (20, y + 4, W - 20, y + row_h - 4)
        if is_us:
            draw.rounded_rectangle(row_box, radius=14, fill=(52, 42, 20))
            draw.rounded_rectangle(row_box, radius=14, outline=GOLD, width=2)
        elif i % 2 == 0:
            draw.rounded_rectangle(row_box, radius=14, fill=PANEL)

        rank_label = medals.get(i, str(i))
        draw.text((col_rank_x, y + row_h / 2), rank_label, font=_font("bold", 20), fill=GOLD if i <= 3 else WHITE, anchor="lm")

        badge = await _fetch_badge(session, c.get("badge_url"), badge_d, c.get("name", "?"), (52, 62, 110))
        img.paste(badge, (col_badge_x, int(y + row_h / 2 - badge_d / 2)), badge)

        name_font = _fit_text(draw, c.get("name", "Unknown"), "medium" if not is_us else "bold", 22, 14, 500)
        draw.text((col_name_x, y + row_h / 2), c.get("name", "Unknown"), font=name_font, fill=WHITE if not is_us else GOLD, anchor="lm")

        draw.text((col_stars_x, y + row_h / 2), f"⭐ {c.get('stars', 0)}", font=_font("bold", 19), fill=WHITE, anchor="lm")
        draw.text((col_dest_x, y + row_h / 2), f"{c.get('destruction', 0):.1f}%", font=_font("medium", 18), fill=GREY, anchor="lm")
        draw.text((col_record_x, y + row_h / 2), f"{c.get('wins', 0)}-{c.get('losses', 0)}", font=_font("medium", 18), fill=GREEN, anchor="lm")

        y += row_h

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
