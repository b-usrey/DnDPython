"""
utils/character_builder.py

Interactive CLI wizard for building a custom character and saving it as a
runnable scenario JSON.

Usage (via main.py):
    python main.py build

Flow:
  1. Character name
  2. Class + level
  3. Subclass (if applicable)
  4. Ability scores (standard array, point buy, or manual)
  5. Feature choices (fighting style, invocations, etc.)
  6. Equipment (weapon + armor, filtered by class proficiency)
  7. Optional feats
  8. Monster opponents
  9. Write to scenarios/<name>.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


# ---------------------------------------------------------------------------
# ANSI helpers (works on Windows 10+ via ENABLE_VIRTUAL_TERMINAL_PROCESSING)
# ---------------------------------------------------------------------------

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def gold(t):   return _c(t, "33")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")
def green(t):  return _c(t, "32")
def red(t):    return _c(t, "31")
def cyan(t):   return _c(t, "36")


def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user for free-text input."""
    suffix = f" [{default}]" if default else ""
    val = input(f"  {gold('>')} {prompt}{suffix}: ").strip()
    return val if val else default


def _choose(prompt: str, options: list[str], default_idx: int = 0) -> str:
    """Show a numbered menu, return the chosen string."""
    print(f"\n  {bold(prompt)}")
    for i, opt in enumerate(options):
        marker = green("*") if i == default_idx else " "
        print(f"    {marker} {cyan(str(i+1))}. {opt}")
    while True:
        raw = input(f"  {gold('>')} Choice [1-{len(options)}] "
                    f"(default {default_idx+1}): ").strip()
        if not raw:
            return options[default_idx]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print(f"  {red('!')} Enter a number between 1 and {len(options)}.")


def _choose_many(prompt: str, options: list[str], n: int) -> list[str]:
    """Let the user pick exactly n items from options."""
    print(f"\n  {bold(prompt)}")
    for i, opt in enumerate(options):
        print(f"    {cyan(str(i+1))}. {opt}")
    chosen = []
    while len(chosen) < n:
        remaining = n - len(chosen)
        raw = input(f"  {gold('>')} Pick {remaining} more "
                    f"(number, or done to skip): ").strip()
        if raw.lower() in ("done", "skip", "") and not chosen:
            return []
        if raw.lower() in ("done", "skip"):
            break
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                item = options[idx]
                if item not in chosen:
                    chosen.append(item)
                    print(f"    {green('+')} {item}")
                else:
                    print(f"  {red('!')} Already chosen.")
            else:
                print(f"  {red('!')} Out of range.")
        except ValueError:
            print(f"  {red('!')} Enter a number.")
    return chosen


def _ask_int(prompt: str, lo: int, hi: int, default: int) -> int:
    while True:
        raw = input(f"  {gold('>')} {prompt} [{lo}-{hi}] (default {default}): ").strip()
        if not raw:
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
        except ValueError:
            pass
        print(f"  {red('!')} Enter a whole number between {lo} and {hi}.")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_classes() -> dict[str, dict]:
    classes = {}
    classes_dir = DATA / "classes"
    for path in sorted(classes_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        classes[data["class_name"]] = data
    return classes


def _load_items() -> dict[str, dict]:
    with open(DATA / "items.json") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if k != "comment"}


def _load_monsters() -> dict[str, dict]:
    sys.path.insert(0, str(ROOT))
    from data.monsters.monsters import MONSTER_REGISTRY
    return MONSTER_REGISTRY


# ---------------------------------------------------------------------------
# Proficiency filter helpers
# ---------------------------------------------------------------------------

_SIMPLE_WEAPONS = {
    "Dagger", "Dagger+1", "Handaxe", "Javelin", "Light Crossbow",
    "Mace", "Quarterstaff", "Shortbow", "Spear",
}
_MARTIAL_WEAPONS = {
    "Longsword", "Longsword+1", "Longsword+2",
    "Shortsword", "Shortsword+1",
    "Rapier", "Rapier+1", "Rapier+2",
    "Greatsword", "Greatsword+1", "Greatsword+2",
    "Greataxe", "Greataxe+1", "Greataxe+2",
    "Battleaxe", "Warhammer", "Warhammer+1",
    "Maul", "Flail", "Morningstar",
    "Longbow", "Longbow+1", "Longbow+2",
    "Hand Crossbow",
}
_LIGHT_ARMOR  = {"Leather Armor", "Studded Leather", "Studded Leather+1", "Studded Leather+2"}
_MEDIUM_ARMOR = {"Scale Mail", "Breastplate", "Breastplate+1", "Half Plate", "Half Plate+1"}
_HEAVY_ARMOR  = {"Chain Mail", "Chain Mail+1", "Plate", "Plate+1"}
_SHIELDS      = {"Shield", "Shield+1"}
_TRINKETS     = {
    "Bracers Of Archery", "Ring of Protection", "Cloak of Protection",
}


def _weapons_for(armor_profs: list[str], weapon_profs: list[str]) -> list[str]:
    allowed: set[str] = set()
    if "simple" in weapon_profs:
        allowed |= _SIMPLE_WEAPONS
    if "martial" in weapon_profs:
        allowed |= _MARTIAL_WEAPONS
    return sorted(allowed)


def _armor_for(armor_profs: list[str]) -> list[str]:
    allowed: set[str] = set()
    if "light" in armor_profs or "all" in armor_profs:
        allowed |= _LIGHT_ARMOR
    if "medium" in armor_profs or "all" in armor_profs:
        allowed |= _MEDIUM_ARMOR
    if "heavy" in armor_profs or "all" in armor_profs:
        allowed |= _HEAVY_ARMOR
    if "shields" in armor_profs or "all" in armor_profs:
        allowed |= _SHIELDS
    return sorted(allowed)


# ---------------------------------------------------------------------------
# Standard array and point buy
# ---------------------------------------------------------------------------

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
STAT_NAMES     = ["Str", "Dex", "Con", "Int", "Wis", "Cha"]

def _assign_standard_array() -> dict[str, int]:
    print(f"\n  {bold('Standard array:')} {STANDARD_ARRAY}")
    print("  Assign each value to an ability score.\n")
    remaining = list(STANDARD_ARRAY)
    scores: dict[str, int] = {}
    for stat in STAT_NAMES:
        print(f"  Remaining values: {sorted(remaining, reverse=True)}")
        chosen = _choose(f"Assign to {bold(stat)}", [str(v) for v in sorted(remaining, reverse=True)])
        val = int(chosen)
        scores[stat] = val
        remaining.remove(val)
    return scores


def _manual_stats() -> dict[str, int]:
    print(f"\n  {bold('Enter each ability score (1-20):')}")
    scores = {}
    for stat in STAT_NAMES:
        scores[stat] = _ask_int(stat, 1, 20, 10)
    return scores


def _point_buy() -> dict[str, int]:
    print(f"\n  {bold('Point Buy')} — 27 points to spend. Each score starts at 8.")
    print("  Cost: 9=1pt, 10=2pt, 11=3pt, 12=4pt, 13=5pt, 14=7pt, 15=9pt\n")
    COST = {8:0, 9:1, 10:2, 11:3, 12:4, 13:5, 14:7, 15:9}
    scores = {s: 8 for s in STAT_NAMES}
    budget = 27

    for stat in STAT_NAMES:
        while True:
            current_cost = COST.get(scores[stat], 0)
            print(f"  Budget remaining: {budget + current_cost} pts  |  {stat} = {scores[stat]}")
            raw = _ask(f"Set {bold(stat)} (8-15)", str(scores[stat]))
            try:
                val = int(raw)
                if val < 8 or val > 15:
                    print(f"  {red('!')} Range is 8-15 for point buy.")
                    continue
                cost = COST[val]
                spent_so_far = sum(COST.get(v, 0) for k, v in scores.items() if k != stat)
                if spent_so_far + cost > 27:
                    print(f"  {red('!')} Not enough points (cost={cost}, remaining={27 - spent_so_far}).")
                    continue
                scores[stat] = val
                budget = 27 - sum(COST.get(v, 0) for v in scores.values())
                break
            except (ValueError, KeyError):
                print(f"  {red('!')} Invalid value.")
    return scores


# ---------------------------------------------------------------------------
# Choice resolution
# ---------------------------------------------------------------------------

def _get_choices_for_class(class_data: dict, level: int, subclass: str | None) -> list[list]:
    """Walk levels 1..level and collect all 'options' choices needed."""
    choices_needed: list[tuple[str, int, str, list[str]]] = []

    for lvl in range(1, level + 1):
        for feat in class_data["features_by_level"].get(str(lvl), []):
            if "options" in feat:
                choices_needed.append(
                    (class_data["class_name"], lvl, feat["name"], feat["options"])
                )

    if subclass:
        sub_key = subclass.replace(" ", "").lower()
        sub_data = class_data.get("subclasses", {}).get(sub_key) or \
                   class_data.get("subclasses", {}).get(subclass.lower())
        if sub_data:
            for lvl in range(1, level + 1):
                for feat in sub_data.get("features_by_level", {}).get(str(lvl), []):
                    if "options" in feat:
                        choices_needed.append(
                            (subclass, lvl, feat["name"], feat["options"])
                        )

    return choices_needed


# ---------------------------------------------------------------------------
# Subclass unlock level
# ---------------------------------------------------------------------------

def _subclass_unlock_level(class_data: dict) -> int:
    """Return the lowest level at which 'Primal Path' / 'Roguish Archetype' etc. appear."""
    for lvl_str, feats in class_data["features_by_level"].items():
        for feat in feats:
            if "options" in feat and any(
                kw in feat["name"].lower()
                for kw in ("path", "archetype", "oath", "patron", "college", "circle", "tradition")
            ):
                return int(lvl_str)
    # Fallback — check subclasses section
    if class_data.get("subclasses"):
        sub_levels = [
            int(lvl)
            for sub in class_data["subclasses"].values()
            for lvl in sub.get("features_by_level", {}).keys()
        ]
        return min(sub_levels) if sub_levels else 3
    return 3


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_builder() -> None:
    # Enable ANSI on Windows
    if sys.platform == "win32":
        os.system("")

    print("\n" + "=" * 56)
    print(bold(gold("  D&D 5e Character Builder")))
    print("=" * 56)
    print(dim("  Type a value and press Enter. Press Enter to accept defaults.\n"))

    classes_data = _load_classes()
    items_data   = _load_items()
    monsters_reg = _load_monsters()

    # ── 1. Name ──────────────────────────────────────────────────────────
    name = _ask("Character name", "Adventurer")

    # ── 2. Class & level ─────────────────────────────────────────────────
    class_names = sorted(classes_data.keys())
    chosen_class = _choose("Choose a class", class_names)
    class_data   = classes_data[chosen_class]

    level = _ask_int("Character level", 1, 20, 5)

    # ── 3. Subclass ───────────────────────────────────────────────────────
    subclass: str | None = None
    unlock = _subclass_unlock_level(class_data)
    if level >= unlock and class_data.get("subclasses"):
        sub_options = list(class_data["subclasses"].keys())
        sub_display = [s.title() for s in sub_options]
        chosen_display = _choose(
            f"Choose a {chosen_class} subclass (unlocked at lv{unlock})",
            sub_display,
        )
        # Map back to original key
        subclass = sub_options[sub_display.index(chosen_display)]

    # ── 4. Ability scores ─────────────────────────────────────────────────
    method = _choose(
        "How do you want to set ability scores?",
        ["Standard array (15/14/13/12/10/8)", "Point buy (27 points)", "Manual entry"],
    )
    if "standard" in method.lower():
        scores = _assign_standard_array()
    elif "point" in method.lower():
        scores = _point_buy()
    else:
        scores = _manual_stats()

    print(f"\n  {bold('Scores:')} " +
          "  ".join(f"{k}:{green(str(v))}" for k, v in scores.items()))

    # ── 5. Feature choices (fighting style, etc.) ─────────────────────────
    choices_needed = _get_choices_for_class(class_data, level, subclass)
    final_choices: list[list] = []

    if choices_needed:
        print(f"\n  {bold('Feature choices:')}")

    for cls_name, feat_level, feat_name, options in choices_needed:
        print(f"\n  lv{feat_level} {bold(feat_name)}")
        chosen_opt = _choose(f"  {feat_name}", options)
        final_choices.append([cls_name, feat_level, feat_name, chosen_opt])

    # ── 6. Equipment ──────────────────────────────────────────────────────
    armor_profs  = class_data.get("armor_proficiencies", [])
    weapon_profs = class_data.get("weapon_proficiencies", [])

    available_weapons = _weapons_for(armor_profs, weapon_profs)
    available_armor   = _armor_for(armor_profs)

    print(f"\n  {bold('Equipment selection')}")

    chosen_weapon = _choose(
        "Primary weapon",
        available_weapons,
        default_idx=0,
    )

    # Offer a second weapon slot if class can dual-wield or has two-handed
    item_meta = items_data.get(chosen_weapon, {})
    is_two_handed = "two-handed" in item_meta.get("properties", [])
    second_weapon: str | None = None
    if not is_two_handed:
        if _ask("Equip a second weapon? (y/n)", "n").lower().startswith("y"):
            second_weapon = _choose("Off-hand weapon", available_weapons, default_idx=0)

    chosen_armor = _choose(
        "Armor",
        available_armor if available_armor else ["None"],
        default_idx=0,
    )

    # Optional trinkets
    trinkets: list[str] = []
    trinket_options = sorted(_TRINKETS)
    if _ask("Add magic trinkets/items? (y/n)", "n").lower().startswith("y"):
        trinkets = _choose_many("Choose trinkets (all items stack)", trinket_options, n=3)

    # Build items and equipped lists
    all_items    = [chosen_weapon]
    all_equipped = [chosen_weapon]
    if second_weapon:
        all_items.append(second_weapon)
        all_equipped.append(second_weapon)
    if chosen_armor and chosen_armor != "None":
        all_items.append(chosen_armor)
        all_equipped.append(chosen_armor)
    all_items    += trinkets
    all_equipped += trinkets

    # ── 7. Feats ─────────────────────────────────────────────────────────
    from data.features.base import Feature as _Feature
    feat_options = sorted(
        name for name, cls in _Feature.REGISTRY.items()
        if not name.startswith("ASI") and "stub" not in name.lower()
        and name not in {
            # Exclude class features — only surfacing standalone feats
            "Rage", "Reckless Attack", "Danger Sense", "Extra Attack",
            "Fast Movement", "Feral Instinct", "Brutal Critical",
            "Relentless Rage", "Persistent Rage", "Primal Champion",
            "Frenzy", "Mindless Rage", "Retaliation", "Bear Totem Spirit",
            "Lay on Hands", "Divine Smite", "Aura of Protection",
            "Aura of Courage", "Improved Divine Smite",
            "Sacred Weapon", "Vow of Enmity", "Soul of Vengeance",
            "Sneak Attack", "Cunning Action", "Uncanny Dodge",
            "Evasion", "Slippery Mind", "Elusive", "Stroke of Luck",
            "Assassinate", "Death Strike", "Eldritch Blast",
            "Pact Magic", "Agonizing Blast", "Repelling Blast",
            "Hex", "Dark One's Blessing", "Fiendish Resilience",
            "Second Wind", "Action Surge", "Indomitable",
            "Improved Critical", "Superior Critical", "Survivor",
            "Favored Foe", "Roving", "Feral Senses", "Foe Slayer",
            "Dread Ambusher", "Iron Mind", "Stalker's Flurry",
            "Shadowy Dodge", "Nature's Veil",
        }
    )

    extra_features: list[str] = []
    if _ask("Add extra feats? (y/n)", "n").lower().startswith("y"):
        n_feats = _ask_int("How many feats?", 1, 3, 1)
        extra_features = _choose_many("Choose feats", feat_options, n=n_feats)

    # ── 8. Opponents ─────────────────────────────────────────────────────
    print(f"\n  {bold('Monster opponents')}")
    monster_types = sorted(monsters_reg.keys())
    monsters_list: list[dict] = []

    while True:
        mtype = _choose("Monster type", monster_types)
        count = _ask_int(f"How many {mtype.title()}?", 1, 20, 5)
        role  = _choose("Weapon role", ["random", "melee", "ranged", "all"])
        monsters_list.append({"type": mtype, "count": count, "weapon_role": role})
        if not _ask("Add another monster group? (y/n)", "n").lower().startswith("y"):
            break

    # ── 9. Map ────────────────────────────────────────────────────────────
    print(f"\n  {bold('Map settings')}")
    width  = _ask_int("Map width (squares)", 10, 40, 20)
    height = _ask_int("Map height (squares)", 10, 30, 16)

    # ── 10. Build scenario dict ───────────────────────────────────────────
    player = {
        "name":       name,
        "classes":    [[chosen_class, level]],
        "subclasses": {chosen_class: subclass.title()} if subclass else {},
        "stats":      scores,
        "choices":    final_choices,
        "items":      all_items,
        "equipped":   all_equipped,
        "features":   extra_features,
    }

    # Place player on the left, monsters spread on the right
    n_monsters_total = sum(m["count"] for m in monsters_list)
    player_pos = [3, height // 2]
    monster_positions = []
    rows = list(range(1, height))
    step = max(1, len(rows) // max(n_monsters_total, 1))
    for i in range(n_monsters_total):
        row = rows[min(i * step, len(rows) - 1)]
        monster_positions.append([width - 4, row])

    scenario = {
        "name": f"{name} vs {' + '.join(m['type'].title() for m in monsters_list)}",
        "max_rounds": 30,
        "map": {
            "width":  width,
            "height": height,
            "walls":  [],
            "difficult_terrain": [],
        },
        "positions": {
            name:       player_pos,
            "monsters": monster_positions,
        },
        "players":  [player],
        "monsters": monsters_list,
    }

    # ── 11. Save ──────────────────────────────────────────────────────────
    slug = name.lower().replace(" ", "_")
    default_file = f"{slug}_scenario.json"
    filename = _ask("Save as (filename in scenarios/)", default_file)
    if not filename.endswith(".json"):
        filename += ".json"

    out_path = ROOT / "scenarios" / filename
    out_path.write_text(json.dumps(scenario, indent=2))

    print(f"\n  {green('✓')} Saved → {bold(str(out_path))}")
    print(f"\n  {bold('Run it with:')}")
    print(f"    {cyan(f'python main.py run --json {filename} --no-vis')}")
    print(f"    {cyan(f'python main.py run --json {filename} --player')}")
    print()
