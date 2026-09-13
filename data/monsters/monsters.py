"""
data/monsters/monsters.py

SRD 5.1 monsters, transcribed as data for the combat engine.

Every number here reaches the dice. Until September 2026 none of the attack
numbers did: monster attacks resolved at +0 to hit for 1d6 regardless of the
stat block, so only HP, AC and attack count ever mattered. Fixing that also
meant correcting entries that had drifted from the SRD (hobgoblin HP and AC,
ghouls and ghasts given a Multiattack they do not have, one-die damage where
the SRD says 2d10, and so on).

Monster template schema
-----------------------
Required   name, hp, ac, cr, stats, attacks
Optional
  type                     creature type: "undead", "dragon", "beast", ...
  speed                    feet per turn (default 30)
  flying                   True: ignores difficult terrain
  proficiency, multiattack, save_proficiencies
  damage_resistances / damage_immunities / damage_vulnerabilities
                           lists of damage types
  nonmagical_physical      "resist" or "immune": bludgeoning, piercing and
                           slashing from nonmagical attacks
  condition_immunities     list of conditions
  traits                   names, or {"name": ..., params} dicts
  actions                  recharge / limited-use actions (breath weapons)
  spellcasting             {"ability", "dc", "attack", "caster_level",
                            "slots", "spells"}
  legendary_resistance     uses per day
  legendary_actions        {"count": 3, "options": [...]}

Attack template
  name, attack_type ("melee" / "range"), attack_bonus, damage_dice ("2d10"),
  damage_mod, damage_type, normal_range, long_range (reach for melee),
  magical, no_damage, on_hit (see MonsterRiders in monster_features.py).
  The legacy single-die "damage_die": 8 still loads as 1d8.

Simplifications: Multiattack repeats the one attack the planner chooses
rather than following a "bite and two claws" routine, so a creature with
differing attacks makes its best one each time. Traits the engine cannot
express (charges, sunlight sensitivity, shapechanging) are listed in
monster_features.py.
"""


def _stats(s, d, c, i, w, ch):
    return {"Str": s, "Dex": d, "Con": c, "Int": i, "Wis": w, "Cha": ch}


def _atk(name, bonus, dice, mod, dtype, kind="melee", rng=(5, 5), **extra):
    a = {
        "name": name, "attack_type": kind, "attack_bonus": bonus,
        "damage_dice": dice, "damage_mod": mod, "damage_type": dtype,
        "normal_range": rng[0], "long_range": rng[1],
    }
    a.update(extra)
    return a


# ── CR 1/8 ───────────────────────────────────────────────────────────────────

KOBOLD = {
    "name": "Kobold", "type": "humanoid", "cr": 0.125, "hp": 5, "ac": 12,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(7, 15, 9, 8, 7, 8),
    "attacks": [
        _atk("Dagger", 4, "1d4", 2, "piercing"),
        _atk("Sling", 4, "1d4", 2, "bludgeoning", "range", (30, 120)),
    ],
    "traits": ["Pack Tactics"],
}

CULTIST = {
    "name": "Cultist", "type": "humanoid", "cr": 0.125, "hp": 9, "ac": 12,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(11, 12, 10, 10, 11, 10),
    "attacks": [_atk("Scimitar", 3, "1d6", 1, "slashing")],
}

# ── CR 1/4 ───────────────────────────────────────────────────────────────────

GOBLIN = {
    "name": "Goblin", "type": "humanoid", "cr": 0.25, "hp": 7, "ac": 15,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(8, 14, 10, 10, 8, 8),
    "attacks": [
        _atk("Scimitar", 4, "1d6", 2, "slashing"),
        _atk("Shortbow", 4, "1d6", 2, "piercing", "range", (80, 320)),
    ],
    "traits": ["Nimble Escape"],
}

SKELETON = {
    "name": "Skeleton", "type": "undead", "cr": 0.25, "hp": 13, "ac": 13,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(10, 14, 15, 6, 8, 5),
    "damage_vulnerabilities": ["bludgeoning"],
    "damage_immunities": ["poison"],
    "condition_immunities": ["exhaustion", "poisoned"],
    "attacks": [
        _atk("Shortsword", 4, "1d6", 2, "piercing"),
        _atk("Shortbow", 4, "1d6", 2, "piercing", "range", (80, 320)),
    ],
}

ZOMBIE = {
    "name": "Zombie", "type": "undead", "cr": 0.25, "hp": 22, "ac": 8,
    "speed": 20, "proficiency": 2, "multiattack": 1,
    "stats": _stats(13, 6, 16, 3, 6, 5),
    "save_proficiencies": ["Wis"],
    "damage_immunities": ["poison"],
    "condition_immunities": ["poisoned"],
    "attacks": [_atk("Slam", 3, "1d6", 1, "bludgeoning")],
    "traits": ["Undead Fortitude"],
}

WOLF = {
    "name": "Wolf", "type": "beast", "cr": 0.25, "hp": 11, "ac": 13,
    "speed": 40, "proficiency": 2, "multiattack": 1,
    "stats": _stats(12, 15, 12, 3, 12, 6),
    "attacks": [
        _atk("Bite", 4, "2d4", 2, "piercing",
             on_hit={"save": "Str", "dc": 11, "condition": "prone"}),
    ],
    "traits": ["Pack Tactics"],
}

# ── CR 1/2 ───────────────────────────────────────────────────────────────────

ORC = {
    "name": "Orc", "type": "humanoid", "cr": 0.5, "hp": 15, "ac": 13,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(16, 12, 16, 7, 11, 10),
    "attacks": [
        _atk("Greataxe", 5, "1d12", 3, "slashing"),
        _atk("Javelin", 5, "1d6", 3, "piercing", "range", (30, 120)),
    ],
    "traits": ["Aggressive"],
}

HOBGOBLIN = {
    "name": "Hobgoblin", "type": "humanoid", "cr": 0.5, "hp": 11, "ac": 18,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(13, 12, 12, 10, 10, 9),
    "attacks": [
        _atk("Longsword", 3, "1d8", 1, "slashing"),
        _atk("Longbow", 3, "1d8", 1, "piercing", "range", (150, 600)),
    ],
    "traits": ["Martial Advantage"],
}

GNOLL = {
    "name": "Gnoll", "type": "humanoid", "cr": 0.5, "hp": 22, "ac": 15,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(14, 12, 11, 6, 10, 7),
    "attacks": [
        _atk("Bite", 4, "1d4", 2, "piercing"),
        _atk("Spear", 4, "1d6", 2, "piercing"),
        _atk("Longbow", 3, "1d8", 1, "piercing", "range", (150, 600)),
    ],
}

# ── CR 1 ─────────────────────────────────────────────────────────────────────

BUGBEAR = {
    # Brute (one extra weapon die on a melee hit) is folded into the dice.
    "name": "Bugbear", "type": "humanoid", "cr": 1, "hp": 27, "ac": 16,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(15, 14, 13, 8, 11, 9),
    "attacks": [
        _atk("Morningstar", 4, "2d8", 2, "piercing"),
        _atk("Javelin", 4, "1d6", 2, "piercing", "range", (30, 120)),
    ],
}

GIANT_SPIDER = {
    "name": "Giant Spider", "type": "beast", "cr": 1, "hp": 26, "ac": 14,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(14, 16, 12, 2, 11, 4),
    "attacks": [
        _atk("Bite", 5, "1d8", 3, "piercing",
             on_hit={"extra_damage": "2d8", "extra_damage_type": "poison",
                     "save": "Con", "dc": 11, "save_effect": "half"}),
    ],
    "actions": [
        {"name": "Web", "kind": "attack", "recharge": 5,
         "attack": _atk("Web", 5, "1d1", 0, "bludgeoning", "range", (30, 60),
                        no_damage=True,
                        on_hit={"condition": "restrained",
                                "escape": {"ability": "Str", "dc": 12}})},
    ],
}

GHOUL = {
    "name": "Ghoul", "type": "undead", "cr": 1, "hp": 22, "ac": 12,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(13, 15, 10, 7, 10, 6),
    "damage_immunities": ["poison"],
    "condition_immunities": ["charmed", "exhaustion", "poisoned"],
    "attacks": [
        _atk("Bite", 2, "2d6", 2, "piercing"),
        _atk("Claws", 4, "2d4", 2, "slashing",
             on_hit={"save": "Con", "dc": 10, "condition": "paralyzed",
                     "repeat_save": True, "not_types": ["undead"]}),
    ],
}

DIRE_WOLF = {
    "name": "Dire Wolf", "type": "beast", "cr": 1, "hp": 37, "ac": 14,
    "speed": 50, "proficiency": 2, "multiattack": 1,
    "stats": _stats(17, 15, 15, 3, 12, 7),
    "attacks": [
        _atk("Bite", 5, "2d6", 3, "piercing",
             on_hit={"save": "Str", "dc": 13, "condition": "prone"}),
    ],
    "traits": ["Pack Tactics"],
}

# ── CR 2 ─────────────────────────────────────────────────────────────────────

GHAST = {
    "name": "Ghast", "type": "undead", "cr": 2, "hp": 36, "ac": 13,
    "speed": 30, "proficiency": 2, "multiattack": 1,
    "stats": _stats(16, 17, 10, 11, 10, 8),
    "damage_resistances": ["necrotic"],
    "damage_immunities": ["poison"],
    "condition_immunities": ["charmed", "exhaustion", "poisoned"],
    "attacks": [
        _atk("Bite", 3, "2d8", 3, "piercing"),
        _atk("Claws", 5, "2d6", 3, "slashing",
             on_hit={"save": "Con", "dc": 10, "condition": "paralyzed",
                     "repeat_save": True, "not_types": ["undead"]}),
    ],
    "traits": [{"name": "Stench", "dc": 10}],
}

OGRE = {
    "name": "Ogre", "type": "giant", "cr": 2, "hp": 59, "ac": 11,
    "speed": 40, "proficiency": 2, "multiattack": 1,
    "stats": _stats(19, 8, 16, 5, 7, 7),
    "attacks": [
        _atk("Greatclub", 6, "2d8", 4, "bludgeoning"),
        _atk("Javelin", 6, "2d6", 4, "piercing", "range", (30, 120)),
    ],
}

CULT_FANATIC = {
    "name": "Cult Fanatic", "type": "humanoid", "cr": 2, "hp": 33, "ac": 13,
    "speed": 30, "proficiency": 2, "multiattack": 2,
    "stats": _stats(11, 14, 12, 10, 13, 14),
    "attacks": [_atk("Dagger", 4, "1d4", 2, "piercing")],
    "spellcasting": {
        "ability": "Wis", "dc": 11, "attack": 3, "caster_level": 4,
        "slots": {1: 4, 2: 3},
        "spells": ["Sacred Flame", "Inflict Wounds", "Shield of Faith",
                   "Hold Person", "Spiritual Weapon"],
    },
}

# ── CR 3 ─────────────────────────────────────────────────────────────────────

OWLBEAR = {
    "name": "Owlbear", "type": "monstrosity", "cr": 3, "hp": 59, "ac": 13,
    "speed": 40, "proficiency": 2, "multiattack": 2,
    "stats": _stats(20, 12, 17, 3, 12, 7),
    "attacks": [
        _atk("Beak", 7, "1d10", 5, "piercing"),
        _atk("Claws", 7, "2d8", 5, "slashing"),
    ],
}

MINOTAUR = {
    "name": "Minotaur", "type": "monstrosity", "cr": 3, "hp": 76, "ac": 14,
    "speed": 40, "proficiency": 2, "multiattack": 1,
    "stats": _stats(18, 11, 16, 6, 16, 9),
    "attacks": [
        _atk("Greataxe", 6, "2d12", 4, "slashing"),
        _atk("Gore", 6, "2d8", 4, "piercing"),
    ],
    "traits": ["Reckless"],
}

DISPLACER_BEAST = {
    "name": "Displacer Beast", "type": "monstrosity", "cr": 3, "hp": 85, "ac": 13,
    "speed": 40, "proficiency": 2, "multiattack": 2,
    "stats": _stats(18, 15, 16, 6, 12, 8),
    "attacks": [
        _atk("Tentacle", 6, "1d6", 4, "bludgeoning", rng=(10, 10),
             on_hit={"extra_damage": "1d6", "extra_damage_type": "piercing"}),
    ],
    "traits": ["Displacement"],
}

WIGHT = {
    "name": "Wight", "type": "undead", "cr": 3, "hp": 45, "ac": 14,
    "speed": 30, "proficiency": 2, "multiattack": 2,
    "stats": _stats(15, 14, 16, 10, 13, 15),
    "damage_resistances": ["necrotic"],
    "nonmagical_physical": "resist",
    "damage_immunities": ["poison"],
    "condition_immunities": ["exhaustion", "poisoned"],
    "attacks": [
        _atk("Longsword", 4, "1d8", 2, "slashing"),
        _atk("Longbow", 4, "1d8", 2, "piercing", "range", (150, 600)),
        _atk("Life Drain", 4, "1d6", 2, "necrotic",
             on_hit={"save": "Con", "dc": 13, "max_hp_reduction": True}),
    ],
}

# ── CR 4 ─────────────────────────────────────────────────────────────────────

ETTIN = {
    "name": "Ettin", "type": "giant", "cr": 4, "hp": 85, "ac": 12,
    "speed": 40, "proficiency": 2, "multiattack": 2,
    "stats": _stats(21, 8, 17, 6, 10, 8),
    "attacks": [
        _atk("Battleaxe", 7, "2d8", 5, "slashing"),
        _atk("Morningstar", 7, "2d8", 5, "piercing"),
    ],
}

# ── CR 5 ─────────────────────────────────────────────────────────────────────

TROLL = {
    "name": "Troll", "type": "giant", "cr": 5, "hp": 84, "ac": 15,
    "speed": 30, "proficiency": 3, "multiattack": 3,
    "stats": _stats(18, 13, 20, 7, 9, 7),
    "attacks": [
        _atk("Bite", 7, "1d6", 4, "piercing"),
        _atk("Claw", 7, "2d6", 4, "slashing"),
    ],
    "traits": [{"name": "Regeneration", "hp": 10, "stopped_by": ["fire", "acid"]}],
}

HILL_GIANT = {
    "name": "Hill Giant", "type": "giant", "cr": 5, "hp": 105, "ac": 13,
    "speed": 40, "proficiency": 3, "multiattack": 2,
    "stats": _stats(21, 8, 19, 5, 9, 6),
    "attacks": [
        _atk("Greatclub", 8, "3d8", 5, "bludgeoning", rng=(10, 10)),
        _atk("Rock", 8, "3d10", 5, "bludgeoning", "range", (60, 240)),
    ],
}

WRAITH = {
    "name": "Wraith", "type": "undead", "cr": 5, "hp": 67, "ac": 13,
    "speed": 60, "flying": True, "proficiency": 3, "multiattack": 1,
    "stats": _stats(6, 16, 16, 12, 14, 15),
    "damage_resistances": ["acid", "cold", "fire", "lightning", "thunder"],
    "nonmagical_physical": "resist",
    "damage_immunities": ["necrotic", "poison"],
    "condition_immunities": ["charmed", "exhaustion", "grappled", "paralyzed",
                             "petrified", "poisoned", "prone", "restrained"],
    "attacks": [
        _atk("Life Drain", 6, "4d8", 3, "necrotic",
             on_hit={"save": "Con", "dc": 14, "max_hp_reduction": True}),
    ],
}

VAMPIRE_SPAWN = {
    "name": "Vampire Spawn", "type": "undead", "cr": 5, "hp": 82, "ac": 15,
    "speed": 30, "proficiency": 3, "multiattack": 2,
    "stats": _stats(16, 16, 16, 11, 10, 12),
    "save_proficiencies": ["Dex", "Wis"],
    "damage_resistances": ["necrotic"],
    "nonmagical_physical": "resist",
    "attacks": [
        _atk("Claws", 6, "2d4", 3, "slashing"),
        _atk("Bite", 6, "1d6", 3, "piercing",
             on_hit={"extra_damage": "2d6", "extra_damage_type": "necrotic",
                     "max_hp_reduction": "extra", "heal_self": True}),
    ],
    "traits": [{"name": "Regeneration", "hp": 10, "stopped_by": ["radiant"]}],
}

# ── CR 6 ─────────────────────────────────────────────────────────────────────

MAGE = {
    # AC 15 assumes Mage Armor was cast before the fight, as the SRD notes.
    "name": "Mage", "type": "humanoid", "cr": 6, "hp": 40, "ac": 15,
    "speed": 30, "proficiency": 3, "multiattack": 1,
    "stats": _stats(9, 14, 11, 17, 12, 11),
    "save_proficiencies": ["Int", "Wis"],
    "attacks": [_atk("Dagger", 5, "1d4", 2, "piercing")],
    "spellcasting": {
        "ability": "Int", "dc": 14, "attack": 6, "caster_level": 9,
        "slots": {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
        "spells": ["Fire Bolt", "Magic Missile", "Shield", "Misty Step",
                   "Fireball", "Cone of Cold"],
    },
}

CHIMERA = {
    "name": "Chimera", "type": "monstrosity", "cr": 6, "hp": 114, "ac": 14,
    "speed": 30, "flying": True, "proficiency": 3, "multiattack": 3,
    "stats": _stats(19, 11, 19, 3, 14, 10),
    "attacks": [
        _atk("Bite", 7, "2d6", 4, "piercing"),
        _atk("Horns", 7, "1d12", 4, "bludgeoning"),
        _atk("Claws", 7, "2d6", 4, "slashing"),
    ],
    "actions": [
        {"name": "Fire Breath", "kind": "save_aoe", "shape": "cone", "size_ft": 15,
         "save": "Dex", "dc": 15, "damage_dice": "7d8", "damage_type": "fire",
         "save_effect": "half", "recharge": 5},
    ],
}

# ── Dragons ──────────────────────────────────────────────────────────────────

YOUNG_BLACK_DRAGON = {
    "name": "Young Black Dragon", "type": "dragon", "cr": 7, "hp": 127, "ac": 18,
    "speed": 40, "flying": True, "proficiency": 3, "multiattack": 3,
    "stats": _stats(19, 14, 17, 12, 11, 15),
    "save_proficiencies": ["Dex", "Con", "Wis", "Cha"],
    "damage_immunities": ["acid"],
    "attacks": [
        _atk("Bite", 7, "2d10", 4, "piercing", rng=(10, 10),
             on_hit={"extra_damage": "1d8", "extra_damage_type": "acid"}),
        _atk("Claw", 7, "2d6", 4, "slashing"),
    ],
    "actions": [
        {"name": "Acid Breath", "kind": "save_aoe", "shape": "line", "size_ft": 30,
         "width_ft": 5, "save": "Dex", "dc": 14, "damage_dice": "11d8",
         "damage_type": "acid", "save_effect": "half", "recharge": 5},
    ],
}

YOUNG_GREEN_DRAGON = {
    "name": "Young Green Dragon", "type": "dragon", "cr": 8, "hp": 136, "ac": 18,
    "speed": 40, "flying": True, "proficiency": 3, "multiattack": 3,
    "stats": _stats(19, 12, 17, 16, 13, 15),
    "save_proficiencies": ["Dex", "Con", "Wis", "Cha"],
    "damage_immunities": ["poison"],
    "condition_immunities": ["poisoned"],
    "attacks": [
        _atk("Bite", 7, "2d10", 4, "piercing", rng=(10, 10),
             on_hit={"extra_damage": "2d6", "extra_damage_type": "poison"}),
        _atk("Claw", 7, "2d6", 4, "slashing"),
    ],
    "actions": [
        {"name": "Poison Breath", "kind": "save_aoe", "shape": "cone", "size_ft": 30,
         "save": "Con", "dc": 14, "damage_dice": "12d6", "damage_type": "poison",
         "save_effect": "half", "recharge": 5},
    ],
}

YOUNG_BLUE_DRAGON = {
    "name": "Young Blue Dragon", "type": "dragon", "cr": 9, "hp": 152, "ac": 18,
    "speed": 40, "flying": True, "proficiency": 4, "multiattack": 3,
    "stats": _stats(21, 10, 19, 14, 13, 17),
    "save_proficiencies": ["Dex", "Con", "Wis", "Cha"],
    "damage_immunities": ["lightning"],
    "attacks": [
        _atk("Bite", 9, "2d10", 5, "piercing", rng=(10, 10),
             on_hit={"extra_damage": "1d10", "extra_damage_type": "lightning"}),
        _atk("Claw", 9, "2d6", 5, "slashing"),
    ],
    "actions": [
        {"name": "Lightning Breath", "kind": "save_aoe", "shape": "line", "size_ft": 60,
         "width_ft": 5, "save": "Dex", "dc": 16, "damage_dice": "10d10",
         "damage_type": "lightning", "save_effect": "half", "recharge": 5},
    ],
}

YOUNG_RED_DRAGON = {
    "name": "Young Red Dragon", "type": "dragon", "cr": 10, "hp": 178, "ac": 18,
    "speed": 40, "flying": True, "proficiency": 4, "multiattack": 3,
    "stats": _stats(23, 10, 21, 14, 11, 19),
    "save_proficiencies": ["Dex", "Con", "Wis", "Cha"],
    "damage_immunities": ["fire"],
    "attacks": [
        _atk("Bite", 10, "2d10", 6, "piercing", rng=(10, 10),
             on_hit={"extra_damage": "1d6", "extra_damage_type": "fire"}),
        _atk("Claw", 10, "2d6", 6, "slashing"),
    ],
    "actions": [
        {"name": "Fire Breath", "kind": "save_aoe", "shape": "cone", "size_ft": 30,
         "save": "Dex", "dc": 17, "damage_dice": "16d6", "damage_type": "fire",
         "save_effect": "half", "recharge": 5},
    ],
}

ADULT_RED_DRAGON = {
    "name": "Adult Red Dragon", "type": "dragon", "cr": 17, "hp": 256, "ac": 19,
    "speed": 40, "flying": True, "proficiency": 6, "multiattack": 3,
    "stats": _stats(27, 10, 25, 16, 13, 21),
    "save_proficiencies": ["Dex", "Con", "Wis", "Cha"],
    "damage_immunities": ["fire"],
    "attacks": [
        _atk("Bite", 14, "2d10", 8, "piercing", rng=(10, 10),
             on_hit={"extra_damage": "2d6", "extra_damage_type": "fire"}),
        _atk("Claw", 14, "2d6", 8, "slashing"),
        _atk("Tail", 14, "2d8", 8, "bludgeoning", rng=(15, 15)),
    ],
    "traits": [{"name": "Frightful Presence", "range_ft": 120, "dc": 19}],
    "actions": [
        {"name": "Fire Breath", "kind": "save_aoe", "shape": "cone", "size_ft": 60,
         "save": "Dex", "dc": 21, "damage_dice": "18d6", "damage_type": "fire",
         "save_effect": "half", "recharge": 5},
    ],
    "legendary_resistance": 3,
    "legendary_actions": {
        "count": 3,
        "options": [
            {"name": "Tail Attack", "cost": 1, "kind": "attack", "attack": "Tail"},
            {"name": "Wing Attack", "cost": 2, "kind": "save_aoe", "shape": "burst",
             "size_ft": 10, "save": "Dex", "dc": 22, "damage_dice": "2d6",
             "damage_mod": 8, "damage_type": "bludgeoning", "save_effect": "negates",
             "condition": "prone", "min_targets": 2},
        ],
    },
}

# ── CR 21 ────────────────────────────────────────────────────────────────────

LICH = {
    # Spells limited to those the engine implements; the SRD list is longer.
    "name": "Lich", "type": "undead", "cr": 21, "hp": 135, "ac": 17,
    "speed": 30, "proficiency": 7, "multiattack": 1,
    "stats": _stats(11, 16, 16, 20, 14, 16),
    "save_proficiencies": ["Con", "Int", "Wis"],
    "damage_resistances": ["cold", "lightning", "necrotic"],
    "damage_immunities": ["poison"],
    "nonmagical_physical": "immune",
    "condition_immunities": ["charmed", "exhaustion", "frightened", "paralyzed",
                             "poisoned"],
    "attacks": [
        _atk("Paralyzing Touch", 12, "3d6", 0, "cold",
             on_hit={"save": "Con", "dc": 18, "condition": "paralyzed",
                     "repeat_save": True}),
    ],
    "spellcasting": {
        "ability": "Int", "dc": 20, "attack": 12, "caster_level": 18,
        "slots": {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
        "spells": ["Ray of Frost", "Magic Missile", "Shield", "Thunderwave",
                   "Mirror Image", "Fireball", "Blight"],
    },
    "legendary_resistance": 3,
    "legendary_actions": {
        "count": 3,
        "options": [
            {"name": "Cantrip", "cost": 1, "kind": "attack", "attack": "Ray of Frost"},
            {"name": "Paralyzing Touch", "cost": 2, "kind": "attack",
             "attack": "Paralyzing Touch"},
            {"name": "Disrupt Life", "cost": 3, "kind": "save_aoe", "shape": "burst",
             "size_ft": 20, "save": "Con", "dc": 18, "damage_dice": "6d6",
             "damage_type": "necrotic", "save_effect": "half",
             "not_types": ["undead"], "min_targets": 2},
        ],
    },
}

# ---------------------------------------------------------------------------
# Training dummies -- not real SRD monsters. Stationary, no attacks (so
# plan_turn always skips their turn -- see tactical_ai.py's early "no
# weapons available" check), very high HP so they survive a full test
# window regardless of a character's damage output. Exist purely so a
# single character can be simulated against a fixed defense (AC) with no
# party-composition or counter-damage noise -- see TheDM's dummy-tester
# page, which is the actual consumer of these.
# ---------------------------------------------------------------------------
_DUMMY_STATS = {"Str": 10, "Dex": 10, "Con": 10, "Int": 10, "Wis": 10, "Cha": 10}

TRAINING_DUMMY_AC12 = {
    "name": "Training Dummy (AC 12)", "hp": 500, "ac": 12, "cr": 0,
    "multiattack": 1, "proficiency": 2, "stats": _DUMMY_STATS, "attacks": [],
}
TRAINING_DUMMY_AC15 = {
    "name": "Training Dummy (AC 15)", "hp": 500, "ac": 15, "cr": 0,
    "multiattack": 1, "proficiency": 2, "stats": _DUMMY_STATS, "attacks": [],
}
TRAINING_DUMMY_AC18 = {
    "name": "Training Dummy (AC 18)", "hp": 500, "ac": 18, "cr": 0,
    "multiattack": 1, "proficiency": 2, "stats": _DUMMY_STATS, "attacks": [],
}
TRAINING_DUMMY_AC21 = {
    "name": "Training Dummy (AC 21)", "hp": 500, "ac": 21, "cr": 0,
    "multiattack": 1, "proficiency": 2, "stats": _DUMMY_STATS, "attacks": [],
}

MONSTER_REGISTRY = {
    # CR 1/8 - 1/2
    "KOBOLD": KOBOLD,
    "CULTIST": CULTIST,
    "GOBLIN": GOBLIN,
    "SKELETON": SKELETON,
    "ZOMBIE": ZOMBIE,
    "WOLF": WOLF,
    "ORC": ORC,
    "HOBGOBLIN": HOBGOBLIN,
    "GNOLL": GNOLL,
    # CR 1 - 2
    "BUGBEAR": BUGBEAR,
    "GIANT_SPIDER": GIANT_SPIDER,
    "GHOUL": GHOUL,
    "DIRE_WOLF": DIRE_WOLF,
    "GHAST": GHAST,
    "OGRE": OGRE,
    "CULT_FANATIC": CULT_FANATIC,
    # CR 3 - 6
    "OWLBEAR": OWLBEAR,
    "MINOTAUR": MINOTAUR,
    "DISPLACER_BEAST": DISPLACER_BEAST,
    "WIGHT": WIGHT,
    "ETTIN": ETTIN,
    "TROLL": TROLL,
    "HILL_GIANT": HILL_GIANT,
    "WRAITH": WRAITH,
    "VAMPIRE_SPAWN": VAMPIRE_SPAWN,
    "MAGE": MAGE,
    "CHIMERA": CHIMERA,
    # Dragons and beyond
    "YOUNG_BLACK_DRAGON": YOUNG_BLACK_DRAGON,
    "YOUNG_GREEN_DRAGON": YOUNG_GREEN_DRAGON,
    "YOUNG_BLUE_DRAGON": YOUNG_BLUE_DRAGON,
    "YOUNG_RED_DRAGON": YOUNG_RED_DRAGON,
    "ADULT_RED_DRAGON": ADULT_RED_DRAGON,
    "LICH": LICH,
    # Test fixtures
    "TRAINING_DUMMY_AC12": TRAINING_DUMMY_AC12,
    "TRAINING_DUMMY_AC15": TRAINING_DUMMY_AC15,
    "TRAINING_DUMMY_AC18": TRAINING_DUMMY_AC18,
    "TRAINING_DUMMY_AC21": TRAINING_DUMMY_AC21,
}
