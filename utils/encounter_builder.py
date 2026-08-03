"""
utils/encounter_builder.py

Build a combat-balanced random encounter for a party, targeting one of the
5e DMG's four difficulty bands (easy/medium/hard/deadly), using the
official CR->XP table, per-character XP thresholds by level, and the
monster-count XP multiplier (adjusted for party size).

This is pure logic with no web/session dependency -- callers (e.g.
TheDM's webapp/dnd_api.py) just pass in party levels and a difficulty and
get back a monster list shaped like a scenario JSON's "monsters" entry.
"""

import random

from data.monsters.monsters import MONSTER_REGISTRY

DIFFICULTIES = ["easy", "medium", "hard", "deadly"]

# ---------------------------------------------------------------------------
# Official 5e DMG reference tables
# ---------------------------------------------------------------------------

# CR -> XP for a single monster of that CR (DMG p.274).
CR_TO_XP = {
    0: 10, 0.125: 25, 0.25: 50, 0.5: 100,
    1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800,
    6: 2300, 7: 2900, 8: 3900, 9: 5000, 10: 5900,
    11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000,
    16: 15000, 17: 18000, 18: 20000, 19: 22000, 20: 25000,
    21: 33000, 22: 41000, 23: 50000, 24: 62000, 25: 75000,
    26: 90000, 27: 105000, 28: 120000, 29: 135000, 30: 155000,
}

# Per-character XP threshold by level and difficulty band (DMG p.82).
XP_THRESHOLDS = {
    1:  {"easy": 25,   "medium": 50,   "hard": 75,   "deadly": 100},
    2:  {"easy": 50,   "medium": 100,  "hard": 150,  "deadly": 200},
    3:  {"easy": 75,   "medium": 150,  "hard": 225,  "deadly": 400},
    4:  {"easy": 125,  "medium": 250,  "hard": 375,  "deadly": 500},
    5:  {"easy": 250,  "medium": 500,  "hard": 750,  "deadly": 1100},
    6:  {"easy": 300,  "medium": 600,  "hard": 900,  "deadly": 1400},
    7:  {"easy": 350,  "medium": 750,  "hard": 1100, "deadly": 1700},
    8:  {"easy": 450,  "medium": 900,  "hard": 1400, "deadly": 2100},
    9:  {"easy": 550,  "medium": 1100, "hard": 1600, "deadly": 2400},
    10: {"easy": 600,  "medium": 1200, "hard": 1900, "deadly": 2800},
    11: {"easy": 800,  "medium": 1600, "hard": 2400, "deadly": 3600},
    12: {"easy": 1000, "medium": 2000, "hard": 3000, "deadly": 4500},
    13: {"easy": 1100, "medium": 2200, "hard": 3400, "deadly": 5100},
    14: {"easy": 1250, "medium": 2500, "hard": 3800, "deadly": 5700},
    15: {"easy": 1400, "medium": 2800, "hard": 4300, "deadly": 6400},
    16: {"easy": 1600, "medium": 3200, "hard": 4800, "deadly": 7200},
    17: {"easy": 2000, "medium": 3900, "hard": 5900, "deadly": 8800},
    18: {"easy": 2100, "medium": 4200, "hard": 6300, "deadly": 9500},
    19: {"easy": 2400, "medium": 4900, "hard": 7300, "deadly": 10900},
    20: {"easy": 2800, "medium": 5700, "hard": 8500, "deadly": 12700},
}

# Encounter multiplier tiers by monster count (DMG p.82). 0.5x only ever
# comes into play via the large-party-size adjustment below, never as a
# monster count's own base multiplier.
_MULTIPLIER_TIERS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]


def _base_multiplier(monster_count: int) -> float:
    if monster_count <= 1:
        return 1.0
    if monster_count == 2:
        return 1.5
    if monster_count <= 6:
        return 2.0
    if monster_count <= 10:
        return 2.5
    if monster_count <= 14:
        return 3.0
    return 4.0


def _party_adjusted_multiplier(monster_count: int, party_size: int) -> float:
    """
    DMG p.82: "For every two party members below three, or above five,
    increase or decrease the multiplier by one step" in the tier table.
    """
    idx = _MULTIPLIER_TIERS.index(_base_multiplier(monster_count))
    if party_size < 3:
        idx = min(idx + 1, len(_MULTIPLIER_TIERS) - 1)
    elif party_size > 5:
        idx = max(idx - 1, 0)
    return _MULTIPLIER_TIERS[idx]


def monster_xp(monster_data: dict) -> float:
    """XP for one instance of this monster. Raises if it has no usable 'cr'."""
    cr = monster_data.get("cr")
    if cr is None:
        raise KeyError("monster data has no 'cr' field")
    xp = CR_TO_XP.get(cr)
    if xp is None:
        raise ValueError(f"no XP mapping for CR {cr!r}")
    return xp


def party_xp_threshold(party_levels: list, difficulty: str) -> int:
    """Total party XP threshold for a difficulty band -- the sum of each
    character's own per-level threshold (DMG p.82)."""
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, got {difficulty!r}")
    return sum(XP_THRESHOLDS[lvl][difficulty] for lvl in party_levels)


def assess_difficulty(adjusted_xp: float, party_levels: list) -> str:
    """Which difficulty band a computed adjusted XP total actually lands in
    for this party -- "trivial" if it doesn't even clear "easy"."""
    achieved = "trivial"
    for band in DIFFICULTIES:
        if adjusted_xp >= party_xp_threshold(party_levels, band):
            achieved = band
    return achieved


def score_encounter(
    party_levels: list,
    monsters: list,
    monster_pool: dict | None = None,
) -> dict:
    """
    Score a FIXED encounter against the DMG's XP-budget difficulty math --
    the reverse of build_encounter's job (which searches for a composition
    hitting a target). Used to answer "what does the book think of this
    encounter I already have," e.g. for a saved scenario.

    Args:
        party_levels: character levels, e.g. [3, 3, 4, 3]
        monsters:     scenario-JSON-shaped list, e.g.
                      [{"type": "GOBLIN", "count": 4}, ...]
        monster_pool: {type_key: monster_data} -- defaults to the full
                      MONSTER_REGISTRY.

    Returns a dict: base_xp, adjusted_xp, multiplier, monster_count,
    party_size, party_xp_thresholds (all 4 bands), difficulty_achieved,
    and skipped_types (monster type keys with no usable 'cr' -- e.g. an
    unregistered homebrew monster -- excluded from the XP math rather
    than raising, so the rest of the encounter still gets scored).
    """
    if not party_levels:
        raise ValueError("party_levels must be non-empty")

    pool = monster_pool if monster_pool is not None else MONSTER_REGISTRY

    base_xp = 0.0
    monster_count = 0
    skipped_types = []
    for entry in monsters:
        mtype = entry.get("type", "").upper()
        count = entry.get("count", 1)
        data = pool.get(mtype)
        if data is None or data.get("cr") is None:
            skipped_types.append(mtype)
            continue
        base_xp += monster_xp(data) * count
        monster_count += count

    party_size = len(party_levels)
    multiplier = _party_adjusted_multiplier(monster_count, party_size) if monster_count else 1.0
    adjusted_xp = base_xp * multiplier

    return {
        "base_xp":             base_xp,
        "adjusted_xp":         adjusted_xp,
        "multiplier":          multiplier,
        "monster_count":       monster_count,
        "party_size":          party_size,
        "party_xp_thresholds": {d: party_xp_threshold(party_levels, d) for d in DIFFICULTIES},
        "difficulty_achieved": assess_difficulty(adjusted_xp, party_levels) if monster_count else "trivial",
        "skipped_types":       skipped_types,
    }


def _distribute(total: int, n: int, rng: random.Random) -> list:
    """Split `total` into `n` positive integers summing to `total`, randomly."""
    counts = [1] * n
    for _ in range(total - n):
        counts[rng.randrange(n)] += 1
    return counts


# ---------------------------------------------------------------------------
# Encounter builder
# ---------------------------------------------------------------------------

def build_encounter(
    party_levels: list,
    difficulty: str = "medium",
    monster_pool: dict | None = None,
    max_monsters: int = 8,
    max_distinct_types: int = 3,
    attempts: int = 300,
    rng: random.Random | None = None,
) -> dict:
    """
    Randomly compose a monster group whose adjusted XP is as close as
    possible to the party's XP threshold for `difficulty`.

    Args:
        party_levels:       character levels, e.g. [3, 3, 4, 3]
        difficulty:         one of DIFFICULTIES
        monster_pool:       {type_key: monster_data} -- defaults to the
                             full MONSTER_REGISTRY. Monsters without a
                             usable 'cr' are skipped, not errored on,
                             unless that leaves nothing to choose from.
        max_monsters:       upper bound on total monster count considered
        max_distinct_types: upper bound on how many different monster
                             types can appear in one encounter
        attempts:           how many random compositions to try before
                             returning the best-scoring one found
        rng:                optional random.Random for deterministic tests

    Returns a dict: monsters (scenario-JSON-shaped list), party_levels,
    difficulty_requested, difficulty_achieved, target_xp, base_xp,
    adjusted_xp, multiplier, monster_count.
    """
    if not party_levels:
        raise ValueError("party_levels must be non-empty")
    for lvl in party_levels:
        if not isinstance(lvl, int) or not (1 <= lvl <= 20):
            raise ValueError(f"party levels must be integers 1-20, got {lvl!r}")
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, got {difficulty!r}")
    if max_monsters < 1:
        raise ValueError("max_monsters must be at least 1")

    rng = rng or random.Random()
    pool = monster_pool if monster_pool is not None else MONSTER_REGISTRY
    pool_items = [(key, data) for key, data in pool.items() if data.get("cr") is not None]
    if not pool_items:
        raise ValueError("monster_pool has no monsters with a usable 'cr' field")

    target_xp = party_xp_threshold(party_levels, difficulty)
    party_size = len(party_levels)

    best = None
    best_score = None

    for _ in range(attempts):
        total_count = rng.randint(1, max_monsters)
        n_types = rng.randint(1, min(max_distinct_types, len(pool_items), total_count))
        chosen = rng.sample(pool_items, n_types)
        counts = _distribute(total_count, n_types, rng)

        composition: dict = {}
        base_xp = 0.0
        for (key, data), count in zip(chosen, counts):
            composition[key] = composition.get(key, 0) + count
            base_xp += monster_xp(data) * count

        monster_count = sum(composition.values())
        multiplier = _party_adjusted_multiplier(monster_count, party_size)
        adjusted_xp = base_xp * multiplier
        score = abs(adjusted_xp - target_xp)

        if best_score is None or score < best_score:
            best_score = score
            best = {
                "composition":  composition,
                "base_xp":      base_xp,
                "adjusted_xp":  adjusted_xp,
                "multiplier":   multiplier,
                "monster_count": monster_count,
            }

    monsters = [{"type": key, "count": count} for key, count in best["composition"].items()]
    monsters.sort(key=lambda m: m["type"])

    return {
        "monsters":             monsters,
        "party_levels":         list(party_levels),
        "difficulty_requested": difficulty,
        "difficulty_achieved":  assess_difficulty(best["adjusted_xp"], party_levels),
        "target_xp":            target_xp,
        "base_xp":              best["base_xp"],
        "adjusted_xp":          best["adjusted_xp"],
        "multiplier":           best["multiplier"],
        "monster_count":        best["monster_count"],
    }
