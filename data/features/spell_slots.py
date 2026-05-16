"""
data/features/spell_slots.py

Universal Spellcasting feature — handles all SRD spellcasting classes.

Registers under name="Spellcasting".  Imported after paladin_spells.py
alphabetically, so it overwrites PaladinSpellcasting in Feature.REGISTRY;
all JSON entries {"name": "Spellcasting"} resolve to this class.

Caster detection:
  Full casters  (Wizard, Sorcerer, Cleric, Druid, Bard)  — uses _FULL table
  Half casters  (Paladin, Ranger)                          — uses _HALF table

Sets owner.spell_slots = self so every spell feature can call
    slots = getattr(owner, "spell_slots", None)
    if slots and slots.has_slot(n): slots.spend_slot(n)
"""
from data.features.base import Feature


class Spellcasting(Feature):
    """
    Universal PC spellcasting slot pool.  Auto-detects caster class, level,
    and spellcasting ability from owner.classes.
    """
    name = "Spellcasting"

    _CASTING = {        # class → (ability, caster_type)
        "Wizard":   ("Int", "full"),
        "Sorcerer": ("Cha", "full"),
        "Cleric":   ("Wis", "full"),
        "Druid":    ("Wis", "full"),
        "Bard":     ("Cha", "full"),
        "Paladin":  ("Cha", "half"),
        "Ranger":   ("Wis", "half"),
    }

    _FULL = {
        1:  {1: 2},
        2:  {1: 3},
        3:  {1: 4, 2: 2},
        4:  {1: 4, 2: 3},
        5:  {1: 4, 2: 3, 3: 2},
        6:  {1: 4, 2: 3, 3: 3},
        7:  {1: 4, 2: 3, 3: 3, 4: 1},
        8:  {1: 4, 2: 3, 3: 3, 4: 2},
        9:  {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
        10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
        11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
        12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
        13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
        14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
        15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
        16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
        17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
        18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
        19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 2},
        20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 2},
    }

    _HALF = {
        2:  {1: 2},
        3:  {1: 3},
        5:  {1: 4, 2: 2},
        7:  {1: 4, 2: 3},
        9:  {1: 4, 2: 3, 3: 2},
        11: {1: 4, 2: 3, 3: 3},
        13: {1: 4, 2: 3, 3: 3, 4: 1},
        15: {1: 4, 2: 3, 3: 3, 4: 2},
        17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
        19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
    }

    def __init__(self):
        super().__init__()
        self._slots: dict = {}
        self.spell_attack: int = 0
        self.spell_dc:     int = 8

    def attach(self, owner, bus):
        super().attach(owner, bus)
        ability, ctype, lvl = self._detect(owner)
        prog      = self._FULL if ctype == "full" else self._HALF
        threshold = max((k for k in prog if k <= lvl), default=None)
        self._slots = dict(prog[threshold]) if threshold else {}

        pb = 2 + (lvl - 1) // 4
        mod = owner.statblock.mods.get(ability, 0)
        self.spell_attack = pb + mod
        self.spell_dc     = 8 + pb + mod
        owner.spell_slots = self
        print(f"  {owner.name}: Spellcasting [{ability}] "
              f"(attack +{self.spell_attack}, DC {self.spell_dc}, slots {self._slots})")

    def _detect(self, owner):
        """Return (ability, caster_type, level) for first spellcasting class found."""
        for cls, lvl in getattr(owner, "classes", []):
            if cls in self._CASTING:
                ab, ct = self._CASTING[cls]
                return ab, ct, lvl
        return "Int", "full", 1

    # ── Public spell-slot interface (shared with PactMagic) ──────────────────

    def has_slot(self, min_level: int = 1) -> bool:
        return any(cnt > 0 for lvl, cnt in self._slots.items() if lvl >= min_level)

    def spend_slot(self, min_level: int = 1) -> int | None:
        """Spend lowest available slot >= min_level. Returns slot level or None."""
        for lvl in sorted(self._slots):
            if lvl >= min_level and self._slots[lvl] > 0:
                self._slots[lvl] -= 1
                return lvl
        return None

    def remaining(self) -> dict:
        return {k: v for k, v in self._slots.items() if v > 0}
