GOBLIN = {
    "name": "Goblin",
    "hp": 12,
    "ac": 13,
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
    "features": ["Hellish Rebuke"],
}

ORC = {
    "name": "Orc",
    "hp": 15,
    "ac": 13,
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

MONSTER_REGISTRY = {
    "GOBLIN": GOBLIN,
    "ORC": ORC,
}
