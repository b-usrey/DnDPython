GOBLIN = {
    "name": "Goblin",
    "hp": 12,
    "ac": 13,
    "cr": 0.25,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 8, "Dex": 14, "Con": 10, "Int": 10, "Wis": 8, "Cha": 8},
    "attacks": [
        {
            "name": "Scimitar",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Shortbow",
            "attack_type": "range",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 80,
            "long_range": 320,
        },
    ],
    #"features": ["Hellish Rebuke"]#,"Shield"],
}

ORC = {
    "name": "Orc",
    "hp": 15,
    "ac": 13,
    "cr": 0.5,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 16, "Dex": 12, "Con": 16, "Int": 7, "Wis": 11, "Cha": 10},
    "attacks": [
        {
            "name": "Greataxe",
            "attack_type": "melee",
            "attack_bonus": 5,
            "damage_die": 12,
            "damage_mod": 3,
            "normal_range": 5,
            "long_range": 5,
        }
    ],
}

HOBGOBLIN = {
    "name": "Hobgoblin",
    "hp": 22,
    "ac": 16,
    "cr": 0.5,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 13, "Dex": 12, "Con": 12, "Int": 10, "Wis": 10, "Cha": 9},
    "attacks": [
        {
            "name": "Longsword",
            "attack_type": "melee",
            "attack_bonus": 3,
            "damage_die": 8,
            "damage_mod": 1,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Longbow",
            "attack_type": "range",
            "attack_bonus": 3,
            "damage_die": 8,
            "damage_mod": 1,
            "normal_range": 150,
            "long_range": 600,
        },
    ],
}

BUGBEAR = {
    "name": "Bugbear",
    "hp": 27,
    "ac": 14,
    "cr": 1,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 15, "Dex": 14, "Con": 13, "Int": 8, "Wis": 11, "Cha": 9},
    "attacks": [
        {
            "name": "Morningstar",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 8,
            "damage_mod": 6,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Javelin",
            "attack_type": "range",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 30,
            "long_range": 120,
        },
    ],
}

OGRE = {
    "name": "Ogre",
    "hp": 59,
    "ac": 11,
    "cr": 2,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 19, "Dex": 8, "Con": 16, "Int": 5, "Wis": 10, "Cha": 7},
    "attacks": [
        {
            "name": "Greatclub",
            "attack_type": "melee",
            "attack_bonus": 6,
            "damage_die": 8,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Javelin",
            "attack_type": "range",
            "attack_bonus": 6,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 30,
            "long_range": 120,
        },
    ],
}

OWLBEAR = {
    "name": "Owlbear",
    "hp": 59,
    "ac": 13,
    "cr": 3,
    "multiattack": 2,
    "proficiency": 2,
    "stats": {"Str": 20, "Dex": 12, "Con": 17, "Int": 3, "Wis": 12, "Cha": 7},
    "attacks": [
        {
            "name": "Claw",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 8,
            "damage_mod": 5,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Beak",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 8,
            "damage_mod": 5,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

ETTIN = {
    "name": "Ettin",
    "hp": 110,
    "ac": 12,
    "cr": 4,
    "multiattack": 2,
    "proficiency": 3,
    "stats": {"Str": 21, "Dex": 8, "Con": 17, "Int": 3, "Wis": 10, "Cha": 8},
    "attacks": [
        {
            "name": "Greataxe",
            "attack_type": "melee",
            "attack_bonus": 8,
            "damage_die": 12,
            "damage_mod": 5,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

GHOUL = {
    "name": "Ghoul",
    "hp": 22,
    "ac": 12,
    "cr": 1,
    "multiattack": 2,
    "proficiency": 2,
    "stats": {"Str": 15, "Dex": 15, "Con": 10, "Int": 7, "Wis": 10, "Cha": 6},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Claw",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

WIGHT = {
    "name": "Wight",
    "hp": 45,
    "ac": 14,
    "cr": 3,
    "multiattack": 2,
    "proficiency": 2,
    "stats": {"Str": 15, "Dex": 10, "Con": 16, "Int": 10, "Wis": 13, "Cha": 15},
    "attacks": [
        {
            "name": "Longsword",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 8,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

YOUNG_GREEN_DRAGON = {
    "name": "Young Green Dragon",
    "hp": 110,
    "ac": 16,
    "cr": 8,
    "multiattack": 3,
    "proficiency": 3,
    "stats": {"Str": 19, "Dex": 12, "Con": 17, "Int": 16, "Wis": 13, "Cha": 15},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 6,
            "damage_die": 8,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Claw",
            "attack_type": "melee",
            "attack_bonus": 6,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Tail",
            "attack_type": "melee",
            "attack_bonus": 6,
            "damage_die": 8,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

KOBOLD = {
    "name": "Kobold",
    "hp": 5,
    "ac": 12,
    "cr": 0.125,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 7, "Dex": 15, "Con": 9, "Int": 8, "Wis": 7, "Cha": 8},
    "attacks": [
        {
            "name": "Dagger",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 4,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

SKELETON = {
    "name": "Skeleton",
    "hp": 13,
    "ac": 13,
    "cr": 0.25,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 10, "Dex": 14, "Con": 15, "Int": 6, "Wis": 8, "Cha": 5},
    "attacks": [
        {
            "name": "Shortsword",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Shortbow",
            "attack_type": "range",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 80,
            "long_range": 320,
        },
    ],
}

ZOMBIE = {
    "name": "Zombie",
    "hp": 22,
    "ac": 8,
    "cr": 0.25,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 13, "Dex": 6, "Con": 16, "Int": 3, "Wis": 6, "Cha": 5},
    "attacks": [
        {
            "name": "Slam",
            "attack_type": "melee",
            "attack_bonus": 3,
            "damage_die": 6,
            "damage_mod": 1,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

WOLF = {
    "name": "Wolf",
    "hp": 11,
    "ac": 13,
    "cr": 0.25,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 12, "Dex": 15, "Con": 12, "Int": 3, "Wis": 12, "Cha": 6},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 4,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

GNOLL = {
    "name": "Gnoll",
    "hp": 22,
    "ac": 15,
    "cr": 0.5,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 14, "Dex": 12, "Con": 11, "Int": 6, "Wis": 10, "Cha": 7},
    "attacks": [
        {
            "name": "Spear",
            "attack_type": "melee",
            "attack_bonus": 4,
            "damage_die": 6,
            "damage_mod": 2,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Longbow",
            "attack_type": "range",
            "attack_bonus": 3,
            "damage_die": 8,
            "damage_mod": 1,
            "normal_range": 150,
            "long_range": 600,
        },
    ],
}

GIANT_SPIDER = {
    "name": "Giant Spider",
    "hp": 26,
    "ac": 14,
    "cr": 1,
    "multiattack": 1,
    "proficiency": 2,
    "stats": {"Str": 14, "Dex": 16, "Con": 12, "Int": 2, "Wis": 11, "Cha": 4},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 5,
            "damage_die": 8,
            "damage_mod": 3,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

GHAST = {
    "name": "Ghast",
    "hp": 36,
    "ac": 13,
    "cr": 2,
    "multiattack": 2,
    "proficiency": 2,
    "stats": {"Str": 16, "Dex": 17, "Con": 10, "Int": 11, "Wis": 10, "Cha": 8},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 5,
            "damage_die": 8,
            "damage_mod": 3,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Claws",
            "attack_type": "melee",
            "attack_bonus": 5,
            "damage_die": 6,
            "damage_mod": 3,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

DISPLACER_BEAST = {
    "name": "Displacer Beast",
    "hp": 85,
    "ac": 13,
    "cr": 3,
    "multiattack": 2,
    "proficiency": 2,
    "stats": {"Str": 18, "Dex": 15, "Con": 16, "Int": 6, "Wis": 12, "Cha": 8},
    "attacks": [
        {
            "name": "Tentacle",
            "attack_type": "melee",
            "attack_bonus": 6,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 10,
            "long_range": 10,
        },
    ],
}

TROLL = {
    "name": "Troll",
    "hp": 84,
    "ac": 15,
    "cr": 5,
    "multiattack": 3,
    "proficiency": 3,
    "stats": {"Str": 18, "Dex": 13, "Con": 20, "Int": 7, "Wis": 9, "Cha": 7},
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Claw",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
}

HILL_GIANT = {
    "name": "Hill Giant",
    "hp": 105,
    "ac": 13,
    "cr": 5,
    "multiattack": 2,
    "proficiency": 3,
    "stats": {"Str": 21, "Dex": 8, "Con": 19, "Int": 5, "Wis": 9, "Cha": 6},
    "attacks": [
        {
            "name": "Greatclub",
            "attack_type": "melee",
            "attack_bonus": 8,
            "damage_die": 8,
            "damage_mod": 5,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Rock",
            "attack_type": "range",
            "attack_bonus": 8,
            "damage_die": 10,
            "damage_mod": 5,
            "normal_range": 60,
            "long_range": 240,
        },
    ],
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
    "GOBLIN": GOBLIN,
    "ORC": ORC,
    "HOBGOBLIN": HOBGOBLIN,
    "BUGBEAR": BUGBEAR,
    "KOBOLD": KOBOLD,
    "SKELETON": SKELETON,
    "ZOMBIE": ZOMBIE,
    "WOLF": WOLF,
    "GNOLL": GNOLL,
    "GIANT_SPIDER": GIANT_SPIDER,
    "GHAST": GHAST,
    "DISPLACER_BEAST": DISPLACER_BEAST,
    "TROLL": TROLL,
    "HILL_GIANT": HILL_GIANT,
    "OGRE": OGRE,
    "OWLBEAR": OWLBEAR,
    "ETTIN": ETTIN,
    "GHOUL": GHOUL,
    "WIGHT": WIGHT,
    "YOUNG_GREEN_DRAGON": YOUNG_GREEN_DRAGON,
    "TRAINING_DUMMY_AC12": TRAINING_DUMMY_AC12,
    "TRAINING_DUMMY_AC15": TRAINING_DUMMY_AC15,
    "TRAINING_DUMMY_AC18": TRAINING_DUMMY_AC18,
    "TRAINING_DUMMY_AC21": TRAINING_DUMMY_AC21,
}
