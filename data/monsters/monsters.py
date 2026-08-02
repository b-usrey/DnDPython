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

MONSTER_REGISTRY = {
    "GOBLIN": GOBLIN,
    "ORC": ORC,
    "HOBGOBLIN": HOBGOBLIN,
    "BUGBEAR": BUGBEAR,
    "OGRE": OGRE,
    "OWLBEAR": OWLBEAR,
    "ETTIN": ETTIN,
    "GHOUL": GHOUL,
    "WIGHT": WIGHT,
    "YOUNG_GREEN_DRAGON": YOUNG_GREEN_DRAGON,
}
