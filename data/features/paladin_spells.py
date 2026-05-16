"""
data/features/paladin_spells.py

Paladin spellcasting and combat spells.

PaladinSpellcasting  — half-caster slot pool; sets owner.spell_slots
Bless                — concentration, +1d4 to attack rolls and saving throws (self)
DivineFavor          — concentration, +1d4 radiant on weapon hits
ThunderousSmite      — 1st-level, +2d6 thunder, STR save or prone
WrathfulSmite        — 1st-level, +1d6 psychic, WIS save or frightened
SearingSmite         — 1st-level, +1d6 fire + ongoing CON save vs 1d6 fire each turn
BrandingSmite        — 2nd-level, +2d6 radiant
BlindingSmite        — 3rd-level, +3d8 radiant, CON save or blinded
StaggeringSmite      — 4th-level, +4d6 psychic, WIS save or disadvantaged
"""
import random
from data.features.base import Feature
from core.saving_throw import SavingThrow, DamageOnSave


# ---------------------------------------------------------------------------
# Spell slot pool
# ---------------------------------------------------------------------------

class PaladinSpellcasting(Feature):
    """
    Half-caster spell slot pool.  Attaches when 'Spellcasting' is listed in
    paladin.json features.  Sets owner.spell_slots = self so DivineSmite and
    all smite spells draw from the same pool.
    """
    name = "Spellcasting"

    _PROGRESSION = {
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
        self.spell_dc: int     = 8

    def attach(self, owner, bus):
        super().attach(owner, bus)
        pal_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Paladin"), 1
        )
        threshold = max((k for k in self._PROGRESSION if k <= pal_lvl), default=None)
        self._slots = dict(self._PROGRESSION[threshold]) if threshold else {}

        pb = 2 + (pal_lvl - 1) // 4
        cha_mod = owner.statblock.mods.get("Cha", 0)
        self.spell_attack = pb + cha_mod
        self.spell_dc     = 8 + pb + cha_mod
        owner.spell_slots = self
        print(f"  {owner.name}: Spellcasting (attack +{self.spell_attack}, "
              f"DC {self.spell_dc}, slots {self._slots})")

    # ── public helpers used by DivineSmite and smite spells ──────────────────

    def has_slot(self, min_level: int = 1) -> bool:
        return any(cnt > 0 for lvl, cnt in self._slots.items() if lvl >= min_level)

    def spend_slot(self, min_level: int = 1) -> int | None:
        """Spend the lowest available slot >= min_level. Returns slot level or None."""
        for lvl in sorted(self._slots):
            if lvl >= min_level and self._slots[lvl] > 0:
                self._slots[lvl] -= 1
                return lvl
        return None

    def remaining(self) -> dict:
        return {k: v for k, v in self._slots.items() if v > 0}


# ---------------------------------------------------------------------------
# Bless
# ---------------------------------------------------------------------------

class Bless(Feature):
    """
    Concentration, up to 1 minute. Bonus action to cast.
    Blessed creatures gain +1d4 to attack rolls and saving throws.
    AI blesses self only; expand _blessed set to include allies if needed.
    """
    name = "Bless"
    EVENT_MAP = {
        "TurnStarted":  "on_turn_started",
        "attack":       "on_attack",
        "saving_throw": "on_saving_throw",
    }

    def __init__(self):
        super().__init__()
        self._active  = False
        self._blessed: set = set()

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or self._active:
            return
        if getattr(creature, "concentration", None):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(1)):
            return
        if not creature.actions.use_bonus_action():
            return
        slots.spend_slot(1)
        self._active  = True
        self._blessed = {id(creature)}
        creature.start_concentration(self.name, feature=self)
        print(f"  {creature.name}: Bless! (+1d4 to attacks and saves)")

    def on_attack(self, data):
        if not self._active or id(data.get("attacker")) not in self._blessed:
            return
        attack = data.get("attack")
        if attack:
            attack.to_hit_mod += random.randint(1, 4)

    def on_saving_throw(self, ctx):
        if not self._active or id(ctx.get("target")) not in self._blessed:
            return
        ctx["bonus"] = ctx.get("bonus", 0) + random.randint(1, 4)

    def on_concentration_broken(self):
        self._active  = False
        self._blessed = set()
        print(f"  {self.owner.name}: Bless fades")


# ---------------------------------------------------------------------------
# Divine Favor
# ---------------------------------------------------------------------------

class DivineFavor(Feature):
    """
    Concentration, up to 1 minute. Bonus action to cast.
    Your weapon attacks deal an extra 1d4 radiant damage.
    """
    name = "Divine Favor"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._active = False

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or self._active:
            return
        if getattr(creature, "concentration", None):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(1)):
            return
        if not creature.actions.use_bonus_action():
            return
        slots.spend_slot(1)
        self._active = True
        creature.start_concentration(self.name, feature=self)
        print(f"  {creature.name}: Divine Favor active! (+1d4 radiant on hits)")

    def on_hit(self, data):
        if not self._active or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if attack:
            attack.extra_dice.append((1, 4))

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: Divine Favor fades")


# ---------------------------------------------------------------------------
# Smite spell base class
# ---------------------------------------------------------------------------

class _SmiteSpell(Feature):
    """
    Base for concentration smite spells that end on the first hit.

    - TurnStarted (owner's turn): cast as a bonus action when concentration is
      free and the required slot level is available.
    - hit (melee only, by owner): add extra_dice, break concentration, then
      roll any on-hit saving throw.
    """
    SLOT_LEVEL:   int             = 1
    DICE:         list            = []   # [(count, sides), ...]
    DAMAGE_TYPE:  str             = "radiant"
    SAVE_ABILITY: str | None      = None
    CONDITION:    str | None      = None

    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._active = False

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or self._active:
            return
        if getattr(creature, "concentration", None):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(self.SLOT_LEVEL)):
            return
        if not creature.actions.use_bonus_action():
            return
        slots.spend_slot(self.SLOT_LEVEL)
        self._active = True
        creature.start_concentration(self.name, feature=self)
        print(f"  {creature.name}: {self.name} ready! (concentration, slot {self.SLOT_LEVEL})")

    def on_hit(self, data):
        if not self._active or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or getattr(attack, "range", False):
            return   # melee only
        target = data.get("target")

        for count, sides in self.DICE:
            attack.extra_dice.extend([(1, sides)] * count)

        self.owner.break_concentration()   # sets _active = False via on_concentration_broken

        if self.SAVE_ABILITY and target:
            slots = getattr(self.owner, "spell_slots", None)
            dc = slots.spell_dc if slots else 13
            SavingThrow.roll(
                caster             = self.owner,
                target             = target,
                ability            = self.SAVE_ABILITY,
                dc                 = dc,
                on_save            = DamageOnSave.NONE,
                condition_on_fail  = self.CONDITION,
            )

        dice_str = "+".join(f"{c}d{s}" for c, s in self.DICE)
        print(f"  {self.owner.name}: {self.name} strikes! "
              f"({dice_str} {self.DAMAGE_TYPE})")

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: {self.name} fades")


# ---------------------------------------------------------------------------
# Concrete smite spells
# ---------------------------------------------------------------------------

class ThunderousSmite(_SmiteSpell):
    """1st-level. +2d6 thunder; STR save or target is knocked prone."""
    name         = "Thunderous Smite"
    SLOT_LEVEL   = 1
    DICE         = [(2, 6)]
    DAMAGE_TYPE  = "thunder"
    SAVE_ABILITY = "Str"
    CONDITION    = "prone"


class WrathfulSmite(_SmiteSpell):
    """1st-level. +1d6 psychic; WIS save or target is frightened."""
    name         = "Wrathful Smite"
    SLOT_LEVEL   = 1
    DICE         = [(1, 6)]
    DAMAGE_TYPE  = "psychic"
    SAVE_ABILITY = "Wis"
    CONDITION    = "frightened"


class BrandingSmite(_SmiteSpell):
    """2nd-level. +2d6 radiant; target can't become invisible."""
    name        = "Branding Smite"
    SLOT_LEVEL  = 2
    DICE        = [(2, 6)]
    DAMAGE_TYPE = "radiant"


class BlindingSmite(_SmiteSpell):
    """3rd-level. +3d8 radiant; CON save or target is blinded."""
    name         = "Blinding Smite"
    SLOT_LEVEL   = 3
    DICE         = [(3, 8)]
    DAMAGE_TYPE  = "radiant"
    SAVE_ABILITY = "Con"
    CONDITION    = "blinded"


class StaggeringSmite(_SmiteSpell):
    """4th-level. +4d6 psychic; WIS save or target has disadvantage on attacks."""
    name         = "Staggering Smite"
    SLOT_LEVEL   = 4
    DICE         = [(4, 6)]
    DAMAGE_TYPE  = "psychic"
    SAVE_ABILITY = "Wis"
    CONDITION    = "disadvantaged"


# ---------------------------------------------------------------------------
# Searing Smite  (special: concentration persists after the hit)
# ---------------------------------------------------------------------------

class SearingSmite(Feature):
    """
    1st-level, concentration.  On hit: +1d6 fire.  Target then makes a CON
    save at the start of each of its turns (DC = spell DC) or takes 1d6 fire.
    On a successful save the burning ends and concentration breaks.
    """
    name = "Searing Smite"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._charging       = False   # ready to discharge on next hit
        self._burning_target = None    # creature currently burning

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        if creature is self.owner:
            # Activate if not already active and concentration is free
            if not self._charging and self._burning_target is None:
                if not getattr(creature, "concentration", None):
                    slots = getattr(creature, "spell_slots", None)
                    if slots and slots.has_slot(1):
                        if creature.actions.use_bonus_action():
                            slots.spend_slot(1)
                            self._charging = True
                            creature.start_concentration(self.name, feature=self)
                            print(f"  {creature.name}: Searing Smite ready! (concentration)")

        elif creature is self._burning_target and creature.is_alive():
            # Burning creature makes a CON save at the start of its turn
            dmg   = random.randint(1, 6)
            slots = getattr(self.owner, "spell_slots", None)
            dc    = slots.spell_dc if slots else 13
            result = SavingThrow.roll(
                caster            = self.owner,
                target            = creature,
                ability           = "Con",
                dc                = dc,
                on_save           = DamageOnSave.NONE,   # success = 0 dmg, spell ends
                damage            = dmg,
                damage_type       = "fire",
            )
            if result.success:
                self._burning_target = None   # clear before breaking concentration
                self.owner.break_concentration()
                print(f"  {creature.name}: extinguishes the searing flame!")

    def on_hit(self, data):
        if not self._charging or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or getattr(attack, "range", False):
            return
        target = data.get("target")

        attack.extra_dice.append((1, 6))
        self._charging       = False
        self._burning_target = target
        # concentration continues — do NOT break it here
        print(f"  {self.owner.name}: Searing Smite ignites {target.name}! (+1d6 fire)")

    def on_concentration_broken(self):
        self._charging       = False
        self._burning_target = None
        print(f"  {self.owner.name}: Searing Smite fades")
