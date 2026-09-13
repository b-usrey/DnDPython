"""
core/monster_stats.py

The one place that turns a monster attack template into dice.

Templates used to carry only `damage_die: 8`, which always meant a single
die, so a dragon's 2d10 bite or a troll's 2d6 claw could not be written down
at all. A template may now say `damage_dice: "2d10"`; the legacy integer
`damage_die` is still read as 1dN so existing scenario data keeps working.

Every consumer -- the AI's weapon profiles, attack execution, and the team
memory's threat estimate -- goes through these helpers, so the planner and
the dice can never disagree about what an attack does.
"""


def _parse(text: str) -> tuple[int, int]:
    n, s = str(text).lower().split("d", 1)
    return max(1, int(n or 1)), max(1, int(s))


def template_dice(atk: dict) -> tuple[int, int]:
    """(number of dice, sides) for an attack template."""
    raw = atk.get("damage_dice")
    if isinstance(raw, str) and "d" in raw:
        return _parse(raw)
    sides = atk.get("damage_die", 6)
    if isinstance(sides, str) and "d" in sides:
        return _parse(sides)
    return 1, max(1, int(sides))


def template_dice_str(atk: dict) -> str:
    n, s = template_dice(atk)
    return f"{n}d{s}"


def template_average(atk: dict) -> float:
    """Average damage of one hit, dice plus flat modifier."""
    n, s = template_dice(atk)
    return n * (s + 1) / 2.0 + atk.get("damage_mod", 0)


def parse_dice(text) -> tuple[int, int]:
    """Parse an "NdM" string, falling back to 1d6 on anything unreadable."""
    try:
        return _parse(text)
    except (ValueError, AttributeError, TypeError):
        return 1, 6
