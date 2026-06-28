"""
utils/completion.py — Village completion calculator.

Parses a CoC player JSON payload and computes per-category and overall
completion percentages, plus a "remaining upgrades" list.

NOTE: Exact max levels are approximated for TH16. The CoC API does not
expose max levels directly; we maintain a best-effort lookup table.
"""

from typing import Dict, List, Tuple


# ── Max level tables (TH16) ───────────────────────────────────────────────────
# These are used for completeness calculations.
# Structures not listed default to their current in-game max at TH16.

HERO_MAX = {
    "Barbarian King":  95,
    "Archer Queen":    95,
    "Grand Warden":    65,
    "Royal Champion":  45,
    "Minion Prince":   15,
}

PET_MAX = {
    "L.A.S.S.I": 20, "Electro Owl": 20, "Mighty Yak": 20,
    "Unicorn": 20, "Frosty": 20, "Diggy": 20, "Poison Lizard": 20,
    "Phoenix": 20, "Spirit Fox": 20, "Angry Jelly": 20,
}

# Building max levels at TH16 (key = name, value = max level)
BUILDING_MAX = {
    # Defenses
    "Cannon": 21, "Archer Tower": 21, "Mortar": 14, "Air Defense": 12,
    "Wizard Tower": 16, "Air Sweeper": 7, "Hidden Tesla": 14,
    "X-Bow": 11, "Inferno Tower": 11, "Eagle Artillery": 6,
    "Scattershot": 6, "Builder's Hut": 5, "Giga Tesla": 5,
    "Giga Inferno": 5, "Bomb Tower": 12, "Giant Cannon": 5,
    "Multi-Mortar": 5, "Ricochet Cannon": 5,
    # Army
    "Army Camp": 12, "Barracks": 16, "Dark Barracks": 10,
    "Laboratory": 14, "Spell Factory": 7, "Dark Spell Factory": 6,
    "Siege Workshop": 6, "Pet House": 5,
    # Resources
    "Town Hall": 16, "Clan Castle": 11, "Gold Mine": 15, "Elixir Collector": 15,
    "Dark Elixir Drill": 10, "Gold Storage": 16, "Elixir Storage": 16,
    "Dark Elixir Storage": 10,
    # Walls
    "Wall": 18,
    # Traps
    "Bomb": 9, "Giant Bomb": 5, "Spring Trap": 6, "Air Bomb": 9,
    "Seeking Air Mine": 3, "Skeleton Trap": 6, "Tornado Trap": 4,
}

TROOP_MAX = {
    # Home village troops
    "Barbarian": 12, "Archer": 12, "Giant": 11, "Goblin": 9,
    "Wall Breaker": 12, "Balloon": 11, "Wizard": 10, "Healer": 8,
    "Dragon": 10, "P.E.K.K.A": 10, "Baby Dragon": 10, "Miner": 9,
    "Electro Dragon": 7, "Yeti": 6, "Dragon Rider": 5, "Electro Titan": 5,
    "Root Rider": 5, "Thrower": 5,
    # Dark troops
    "Minion": 12, "Hog Rider": 14, "Valkyrie": 10, "Golem": 11,
    "Witch": 7, "Lava Hound": 7, "Bowler": 7, "Ice Golem": 7,
    "Headhunter": 6, "Apprentice Warden": 5, "Druid": 5,
}

SPELL_MAX = {
    "Lightning Spell": 11, "Healing Spell": 10, "Rage Spell": 7,
    "Freeze Spell": 8, "Earthquake Spell": 5, "Haste Spell": 5,
    "Clone Spell": 7, "Bat Spell": 6, "Invisibility Spell": 5,
    "Recall Spell": 5, "Revive Spell": 5,
    # Dark spells
    "Poison Spell": 9, "Earthquake Spell": 5, "Haste Spell": 5,
    "Skeleton Spell": 7,
}

SIEGE_MAX = {
    "Wall Wrecker": 4, "Battle Blimp": 4, "Stone Slammer": 4,
    "Siege Barracks": 4, "Log Launcher": 4, "Flame Flinger": 4,
    "Battle Drill": 4,
}

EQUIPMENT_MAX = {
    # Level varies; common max is 18 for epic, 15 for common
    # We'll use actual max from API if available; fallback to 18
}


def _safe_pct(current: float, maximum: float) -> float:
    if maximum <= 0:
        return 100.0
    return min(100.0, (current / maximum) * 100)


def calculate_completion(player: dict) -> dict:
    """
    Given a raw CoC player dict, return a completion breakdown dict:
    {
        "overall": float,
        "defenses": float,
        "heroes": float,
        "laboratory": float,
        "walls": float,
        "pets": float,
        "equipment": float,
        "buildings": float,
        "traps": float,
        "remaining": [str, ...]
    }
    """
    results: Dict[str, float] = {}
    remaining: List[str] = []

    # ── Heroes ────────────────────────────────────────────────────────────────
    hero_score = 0.0
    hero_max_score = 0.0
    for hero in player.get("heroes", []):
        name = hero.get("name", "")
        level = hero.get("level", 0)
        max_lv = HERO_MAX.get(name)
        if max_lv is None:
            max_lv = hero.get("maxLevel", level or 1)
        hero_score += level
        hero_max_score += max_lv
        if level < max_lv:
            remaining.append(f"{name} +{max_lv - level}")
    results["heroes"] = _safe_pct(hero_score, hero_max_score) if hero_max_score > 0 else 100.0

    # ── Pets ──────────────────────────────────────────────────────────────────
    pet_score = 0.0
    pet_max_score = len(PET_MAX) * 20
    for troop in player.get("troops", []):
        if troop.get("village") == "home" and troop.get("name") in PET_MAX:
            name = troop["name"]
            level = troop.get("level", 0)
            max_lv = PET_MAX[name]
            pet_score += level
            if level < max_lv:
                remaining.append(f"{name} +{max_lv - level}")
    results["pets"] = _safe_pct(pet_score, pet_max_score)

    # ── Equipment ─────────────────────────────────────────────────────────────
    eq_score = 0.0
    eq_max_score = 0.0
    for equip in player.get("heroEquipment", []):
        name = equip.get("name", "")
        level = equip.get("level", 0)
        max_lv = equip.get("maxLevel", 18)
        eq_score += level
        eq_max_score += max_lv
        if level < max_lv:
            remaining.append(f"{name} (equip) +{max_lv - level}")
    results["equipment"] = _safe_pct(eq_score, eq_max_score) if eq_max_score > 0 else 100.0

    # ── Laboratory (troops + spells + sieges) ─────────────────────────────────
    lab_score = 0.0
    lab_max_score = 0.0
    home_troops = [t for t in player.get("troops", []) if t.get("village") == "home"]
    all_lab = home_troops + player.get("spells", [])
    for item in all_lab:
        name = item.get("name", "")
        level = item.get("level", 0)
        max_lv = item.get("maxLevel", level or 1)
        lab_score += level
        lab_max_score += max_lv
    results["laboratory"] = _safe_pct(lab_score, lab_max_score) if lab_max_score > 0 else 100.0

    # ── Walls ─────────────────────────────────────────────────────────────────
    # CoC API doesn't give wall counts directly; we infer from achievement
    wall_ach = next(
        (a for a in player.get("achievements", []) if a.get("name") == "Wall Buster"),
        None,
    )
    walls_total = _infer_wall_count(player.get("townHallLevel", 0))
    walls_upgraded = 0
    if wall_ach:
        walls_upgraded = min(wall_ach.get("value", 0), walls_total)
    results["walls"] = _safe_pct(walls_upgraded, walls_total)
    if walls_total > walls_upgraded:
        remaining.append(f"{walls_total - walls_upgraded} Walls")

    # ── Buildings ─────────────────────────────────────────────────────────────
    # From player achievements and building stats
    # We approximate from the buildings achievement
    b_score = 0.0
    b_max = 0.0
    for bld in player.get("achievements", []):
        if bld.get("name") in ("Unbreakable", "Bigger & Better"):
            b_score += bld.get("value", 0)
            b_max += bld.get("target", bld.get("value", 1))
    results["buildings"] = _safe_pct(b_score, b_max) if b_max > 0 else 75.0

    # ── Defenses (subset of buildings) — use Unbreakable achievement ──────────
    def_ach = next(
        (a for a in player.get("achievements", []) if a.get("name") == "Unbreakable"),
        None,
    )
    if def_ach:
        results["defenses"] = _safe_pct(def_ach.get("value", 0), def_ach.get("target", 1))
    else:
        results["defenses"] = results["buildings"]

    # ── Traps ─────────────────────────────────────────────────────────────────
    # Approx from achievements
    trap_ach = next(
        (a for a in player.get("achievements", []) if a.get("name") == "Shattered and Scattered"),
        None,
    )
    if trap_ach:
        results["traps"] = _safe_pct(trap_ach.get("value", 0), trap_ach.get("target", 1))
    else:
        results["traps"] = 70.0  # fallback

    # ── Overall ───────────────────────────────────────────────────────────────
    weights = {
        "heroes": 0.15, "pets": 0.08, "equipment": 0.10,
        "laboratory": 0.20, "walls": 0.15, "defenses": 0.15,
        "buildings": 0.12, "traps": 0.05,
    }
    overall = sum(results.get(k, 0) * w for k, w in weights.items())
    results["overall"] = round(overall, 1)
    results["remaining"] = remaining[:20]  # cap for embed

    return results


def _infer_wall_count(th: int) -> int:
    """Approximate total wall pieces at a given TH level."""
    wall_counts = {
        1: 25, 2: 25, 3: 50, 4: 75, 5: 100, 6: 125,
        7: 175, 8: 225, 9: 250, 10: 275, 11: 300,
        12: 325, 13: 350, 14: 375, 15: 400, 16: 425,
    }
    return wall_counts.get(th, 300)


# ── Snapshot diffing ──────────────────────────────────────────────────────────

def diff_snapshots(old: dict, new: dict) -> List[dict]:
    """
    Compare two player snapshots and return a list of upgrade dicts:
    [{"type": str, "name": str, "old": int, "new": int}, ...]
    """
    changes = []

    # Town Hall
    old_th = old.get("townHallLevel", 0)
    new_th = new.get("townHallLevel", 0)
    if new_th > old_th:
        changes.append({"type": "th", "name": "Town Hall", "old": old_th, "new": new_th})

    # Heroes
    old_heroes = {h["name"]: h.get("level", 0) for h in old.get("heroes", [])}
    for hero in new.get("heroes", []):
        name = hero["name"]
        old_lv = old_heroes.get(name, 0)
        new_lv = hero.get("level", 0)
        if new_lv > old_lv:
            changes.append({"type": "hero", "name": name, "old": old_lv, "new": new_lv})

    # Hero Equipment
    old_equip = {e["name"]: e.get("level", 0) for e in old.get("heroEquipment", [])}
    for equip in new.get("heroEquipment", []):
        name = equip["name"]
        old_lv = old_equip.get(name, 0)
        new_lv = equip.get("level", 0)
        if new_lv > old_lv:
            changes.append({"type": "equipment", "name": name, "old": old_lv, "new": new_lv})

    # Troops (home village only)
    old_troops = {
        t["name"]: t.get("level", 0)
        for t in old.get("troops", [])
        if t.get("village") == "home"
    }
    for troop in new.get("troops", []):
        if troop.get("village") != "home":
            continue
        if troop["name"] in PET_MAX:
            utype = "pet"
        else:
            utype = "troop"
        name = troop["name"]
        old_lv = old_troops.get(name, 0)
        new_lv = troop.get("level", 0)
        if new_lv > old_lv:
            changes.append({"type": utype, "name": name, "old": old_lv, "new": new_lv})

    # Spells
    old_spells = {s["name"]: s.get("level", 0) for s in old.get("spells", [])}
    for spell in new.get("spells", []):
        name = spell["name"]
        old_lv = old_spells.get(name, 0)
        new_lv = spell.get("level", 0)
        if new_lv > old_lv:
            changes.append({"type": "spell", "name": name, "old": old_lv, "new": new_lv})

    # Walls (via achievement)
    old_walls = _wall_level_from_achievements(old)
    new_walls = _wall_level_from_achievements(new)
    wall_diff = new_walls - old_walls
    if wall_diff > 0:
        changes.append({"type": "wall", "name": "Wall", "old": old_walls, "new": new_walls})

    return changes


def _wall_level_from_achievements(player: dict) -> int:
    for a in player.get("achievements", []):
        if a.get("name") == "Wall Buster":
            return a.get("value", 0)
    return 0
