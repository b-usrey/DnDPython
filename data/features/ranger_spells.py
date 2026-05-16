"""
data/features/ranger_spells.py

Ranger combat spells — all use the universal Spellcasting slot pool (WIS, half-caster).

  HuntersMark       1st  concentration  bonus action; +1d6 on hits vs marked target;
                                         re-mark (no slot) when target dies
  EnsnaringStrike   1st  concentration  bonus action; on hit STR save or restrained;
                                         target repeats save at start of each its turns
  ZephyrStrike      1st  concentration  bonus action; once: advantage + 1d8 force on
                                         next attack, then concentration ends
  HailOfThorns      1st  concentration  bonus action; on ranged hit DEX save or 1d10
                                         piercing, concentration ends
"""
import random
from data.features.base import Feature
from core.saving_throw import SavingThrow, DamageOnSave


# ---------------------------------------------------------------------------
# Hunter's Mark
# ---------------------------------------------------------------------------

class HuntersMark(Feature):
    """
    Concentration, up to 1 hour. Bonus action to cast.
    Mark one creature: deal +1d6 damage each time you hit it.
    When the marked target drops to 0 HP, bonus action to move the mark
    to a new creature (no additional slot required).

    AI flow:
      TurnStarted → cast if no active mark, using bonus action + slot.
                    If the previous mark died, re-mark for free (bonus action only).
      hit         → if _pending_mark, set target as mark.
                    If target is the current mark, append 1d6 to extra_dice.
    """
    name = "Hunter's Mark"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._marked:        object | None = None
        self._pending_mark:  bool          = False   # bonus action spent, waiting for first hit

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return

        # If marked target has died, clear the mark (concentration persists)
        if self._marked is not None and not self._marked.is_alive():
            self._marked       = None
            self._pending_mark = False

        if self._pending_mark or self._marked is not None:
            return   # already active

        concentrating = getattr(creature, "concentration", None)

        if concentrating == self.name:
            # Re-mark after target death — no slot needed, just bonus action
            if creature.actions.use_bonus_action():
                self._pending_mark = True
                print(f"  {creature.name}: Hunter's Mark — re-marking new target!")
        elif not concentrating:
            # First cast — spend a slot
            slots = getattr(creature, "spell_slots", None)
            if not (slots and slots.has_slot(1)):
                return
            if not creature.actions.use_bonus_action():
                return
            slots.spend_slot(1)
            self._pending_mark = True
            creature.start_concentration(self.name, feature=self)
            print(f"  {creature.name}: Hunter's Mark — ready, awaiting first hit!")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        target = data.get("target")
        if not (attack and target):
            return

        if self._pending_mark:
            self._marked       = target
            self._pending_mark = False
            print(f"  {self.owner.name}: Hunter's Mark on {target.name}!")

        if target is self._marked:
            attack.extra_dice.append((1, 6))

    def on_concentration_broken(self):
        self._marked       = None
        self._pending_mark = False
        print(f"  {self.owner.name}: Hunter's Mark fades")


# ---------------------------------------------------------------------------
# Ensnaring Strike
# ---------------------------------------------------------------------------

class EnsnaringStrike(Feature):
    """
    Concentration, up to 1 minute. Bonus action to cast.
    On next hit (melee or ranged): target makes a STR save or is restrained.
    At the start of each of the restrained creature's turns it repeats the
    save; on success, it breaks free and concentration ends.
    """
    name = "Ensnaring Strike"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._charging:       bool          = False   # ready to discharge on next hit
        self._snared_target:  object | None = None

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        if creature is self.owner:
            if not self._charging and self._snared_target is None:
                if not getattr(creature, "concentration", None):
                    slots = getattr(creature, "spell_slots", None)
                    if slots and slots.has_slot(1):
                        if creature.actions.use_bonus_action():
                            slots.spend_slot(1)
                            self._charging = True
                            creature.start_concentration(self.name, feature=self)
                            print(f"  {creature.name}: Ensnaring Strike ready!")

        elif creature is self._snared_target and creature.is_alive():
            slots = getattr(self.owner, "spell_slots", None)
            dc    = slots.spell_dc if slots else 13
            result = SavingThrow.roll(
                caster            = self.owner,
                target            = creature,
                ability           = "Str",
                dc                = dc,
                on_save           = DamageOnSave.NONE,
            )
            if result.success:
                if creature.has_condition("restrained"):
                    creature.remove_condition("restrained")
                self._snared_target = None
                self.owner.break_concentration()
                print(f"  {creature.name}: breaks free from Ensnaring Strike!")

    def on_hit(self, data):
        if not self._charging or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        target = data.get("target")
        if not (attack and target):
            return

        slots  = getattr(self.owner, "spell_slots", None)
        dc     = slots.spell_dc if slots else 13
        result = SavingThrow.roll(
            caster            = self.owner,
            target            = target,
            ability           = "Str",
            dc                = dc,
            on_save           = DamageOnSave.NONE,
        )
        self._charging = False
        if not result.success:
            target.add_condition("restrained")
            self._snared_target = target
            print(f"  {self.owner.name}: Ensnaring Strike — "
                  f"{target.name} is restrained!")
        else:
            self.owner.break_concentration()
            print(f"  {self.owner.name}: Ensnaring Strike — "
                  f"{target.name} resisted!")

    def on_concentration_broken(self):
        if self._snared_target and self._snared_target.has_condition("restrained"):
            self._snared_target.remove_condition("restrained")
        self._charging      = False
        self._snared_target = None
        print(f"  {self.owner.name}: Ensnaring Strike fades")


# ---------------------------------------------------------------------------
# Zephyr Strike
# ---------------------------------------------------------------------------

class ZephyrStrike(Feature):
    """
    Concentration, up to 1 minute. Bonus action to cast.
    Once before concentration ends: one attack roll gains advantage and
    deals an extra 1d8 force damage. Concentration ends after the bonus fires.

    (Movement OA immunity is not simulated.)
    """
    name = "Zephyr Strike"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":      "on_attack",
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
        print(f"  {creature.name}: Zephyr Strike — ready! "
              f"(advantage + 1d8 force on next attack)")

    def on_attack(self, data):
        if not self._active or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if attack:
            attack.advantage = True

    def on_hit(self, data):
        if not self._active or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack:
            return
        attack.extra_dice.append((1, 8))
        self._active = False
        self.owner.break_concentration()
        print(f"  {self.owner.name}: Zephyr Strike — 1d8 force bonus triggered!")

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: Zephyr Strike fades")


# ---------------------------------------------------------------------------
# Hail of Thorns
# ---------------------------------------------------------------------------

class HailOfThorns(Feature):
    """
    Concentration, up to 1 minute. Bonus action to cast.
    On next ranged weapon hit: target (and nearby creatures — simplified to
    target only) makes a DEX save or takes 1d10 piercing (HALF on save).
    Concentration ends after the burst fires.
    """
    name = "Hail of Thorns"
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
        print(f"  {creature.name}: Hail of Thorns ready!")

    def on_hit(self, data):
        if not self._active or data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or not getattr(attack, "range", False):
            return   # ranged hits only
        target = data.get("target")

        slots = getattr(self.owner, "spell_slots", None)
        dc    = slots.spell_dc if slots else 13
        dmg   = random.randint(1, 10)
        SavingThrow.roll(
            caster      = self.owner,
            target      = target,
            ability     = "Dex",
            dc          = dc,
            on_save     = DamageOnSave.HALF,
            damage      = dmg,
            damage_type = "piercing",
        )
        self._active = False
        self.owner.break_concentration()
        print(f"  {self.owner.name}: Hail of Thorns — {dmg} piercing burst!")

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: Hail of Thorns fades")
