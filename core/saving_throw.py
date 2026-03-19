"""
core/saving_throw.py

Full saving throw system for D&D 5e.

Usage — anywhere a save is needed (features, spells, traps):

    from core.saving_throw import SavingThrow, SaveOutcome, DamageOnSave

    result = SavingThrow.roll(
        caster      = goblin,
        target      = brendiir,
        ability     = "Dex",
        dc          = 11,
        on_save     = DamageOnSave.HALF,
        damage      = 14,
        damage_type = "fire",
    )
    # result.success, result.damage_dealt, result.total are all set

The method broadcasts a "saving_throw" event on the target's event_manager
so features (Evasion, Aura of Protection, Bless, etc.) can modify the roll
before it resolves, and "saving_throw_resolved" afterward for reactions.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.creature import Creature


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DamageOnSave(Enum):
    """What happens to damage when the target succeeds the save."""
    FULL = auto()   # full damage even on success (some traps)
    HALF = auto()   # half damage on success (Fireball, Hellish Rebuke)
    NONE = auto()   # no damage on success (Evasion, some cantrips)


# ---------------------------------------------------------------------------
# SaveResult
# ---------------------------------------------------------------------------

@dataclass
class SaveResult:
    """Everything about how a saving throw resolved."""
    target:        object
    ability:       str
    dc:            int
    roll:          int          # raw d20
    bonus:         int          # total modifier applied
    total:         int          # roll + bonus
    success:       bool
    damage_dealt:  int = 0
    damage_type:   str = ""
    notes:         list = field(default_factory=list)

    def __str__(self):
        outcome  = "SUCCESS" if self.success else "FAILURE"
        note_str = f"  [{', '.join(self.notes)}]" if self.notes else ""
        dmg_str  = f"  ({self.damage_dealt} {self.damage_type} dmg)" if self.damage_dealt else ""
        return (
            f"  {self.target.name} {self.ability} save vs DC {self.dc}: "
            f"rolled {self.roll} + {self.bonus} = {self.total} — {outcome}"
            f"{note_str}{dmg_str}"
        )


# ---------------------------------------------------------------------------
# SavingThrow
# ---------------------------------------------------------------------------

class SavingThrow:
    """
    Stateless helper. Call SavingThrow.roll() to resolve a save.

    Flow:
      1. Broadcast "saving_throw" — features grant advantage/disadvantage or
         flat bonuses (Bless, Aura of Protection, etc.)
      2. Roll d20 with advantage/disadvantage
      3. Add save_bonus from target's StatBlock (ability mod + proficiency)
      4. Compare total to DC
      5. Apply damage per DamageOnSave rule
      6. Apply condition on failure if specified
      7. Broadcast "saving_throw_resolved" with SaveResult
    """

    @staticmethod
    def roll(
        caster,
        target,
        ability:           str,
        dc:                int,
        on_save:           DamageOnSave = DamageOnSave.HALF,
        damage:            int = 0,
        damage_type:       str = "",
        condition_on_fail: str | None = None,
        advantage:         bool = False,
        disadvantage:      bool = False,
    ) -> SaveResult:
        """
        Resolve a saving throw and apply its consequences.

        Args:
            caster:            creature forcing the save (for event context)
            target:            creature making the save
            ability:           matches StatBlock key — "Str","Dex","Con",
                               "Int","Wis","Cha"
            dc:                difficulty class to beat
            on_save:           DamageOnSave.HALF / NONE / FULL
            damage:            base damage before save outcome (0 = no damage)
            damage_type:       "fire", "cold", "bludgeoning", etc.
            condition_on_fail: condition string added on failure
                               e.g. "prone", "frightened", "poisoned"
            advantage:         initial advantage flag (features may also set)
            disadvantage:      initial disadvantage flag
        """
        notes = []

        # ── Phase 1: pre-roll event so features can modify ─────────────
        ctx = {
            "caster":       caster,
            "target":       target,
            "ability":      ability,
            "dc":           dc,
            "advantage":    advantage,
            "disadvantage": disadvantage,
            "bonus":        0,
        }
        target.event_manager.broadcast("saving_throw", ctx)

        advantage    = ctx["advantage"]
        disadvantage = ctx["disadvantage"]
        extra_bonus  = ctx.get("bonus", 0)

        # Advantage and disadvantage cancel each other
        if advantage and disadvantage:
            advantage = disadvantage = False
            notes.append("adv/dis cancel")

        # ── Phase 2: roll d20 ──────────────────────────────────────────
        roll1 = random.randint(1, 20)
        if advantage:
            roll2 = random.randint(1, 20)
            d20   = max(roll1, roll2)
            notes.append(f"advantage ({roll1},{roll2})")
        elif disadvantage:
            roll2 = random.randint(1, 20)
            d20   = min(roll1, roll2)
            notes.append(f"disadvantage ({roll1},{roll2})")
        else:
            d20 = roll1

        # ── Phase 3: save bonus from StatBlock ────────────────────────
        save_mod = target.statblock.save_bonus(ability) + extra_bonus
        if target.statblock.save_profs.get(ability, 0):
            notes.append(f"{ability} save proficiency")

        total   = d20 + save_mod
        success = total >= dc

        # ── Phase 4: apply damage ──────────────────────────────────────
        damage_dealt = 0
        if damage > 0:
            if on_save == DamageOnSave.HALF:
                damage_dealt = damage // 2 if success else damage
            elif on_save == DamageOnSave.NONE:
                damage_dealt = 0 if success else damage
            elif on_save == DamageOnSave.FULL:
                damage_dealt = damage

            if damage_dealt > 0:
                target.take_damage(damage_dealt, damage_type=damage_type)

        # ── Phase 5: condition on failure ─────────────────────────────
        if condition_on_fail and not success:
            target.add_condition(condition_on_fail)
            notes.append(f"condition applied: {condition_on_fail}")

        # ── Phase 6: build result, print, broadcast ───────────────────
        result = SaveResult(
            target       = target,
            ability      = ability,
            dc           = dc,
            roll         = d20,
            bonus        = save_mod,
            total        = total,
            success      = success,
            damage_dealt = damage_dealt,
            damage_type  = damage_type,
            notes        = notes,
        )

        print(result)

        target.event_manager.broadcast("saving_throw_resolved", {
            "caster": caster,
            "result": result,
        })

        return result


# ---------------------------------------------------------------------------
# CommonSaves — pre-built patterns for Feature subclasses
# ---------------------------------------------------------------------------

class CommonSaves:
    """
    Convenience wrappers for frequently used save patterns.
    Use these in Feature subclasses to keep on_* handlers readable.

    Example:
        result = CommonSaves.dex_half(self.owner, attacker, dc=11,
                                      damage=14, damage_type="fire")
    """

    @staticmethod
    def dex_half(caster, target, dc: int, damage: int,
                 damage_type: str = "fire") -> SaveResult:
        """DEX save, half on success. Hellish Rebuke, Fireball, Lightning Bolt."""
        return SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=dc,
            on_save=DamageOnSave.HALF,
            damage=damage, damage_type=damage_type,
        )

    @staticmethod
    def con_half(caster, target, dc: int, damage: int,
                 damage_type: str = "poison") -> SaveResult:
        """CON save, half on success. Poison, Constitution-based effects."""
        return SavingThrow.roll(
            caster=caster, target=target,
            ability="Con", dc=dc,
            on_save=DamageOnSave.HALF,
            damage=damage, damage_type=damage_type,
        )

    @staticmethod
    def wis_condition(caster, target, dc: int, condition: str) -> SaveResult:
        """WIS save, condition on fail. Frightened, Charmed, Hold Person."""
        return SavingThrow.roll(
            caster=caster, target=target,
            ability="Wis", dc=dc,
            on_save=DamageOnSave.NONE,
            condition_on_fail=condition,
        )

    @staticmethod
    def str_condition(caster, target, dc: int, condition: str) -> SaveResult:
        """STR save, condition on fail. Prone, Grappled effects."""
        return SavingThrow.roll(
            caster=caster, target=target,
            ability="Str", dc=dc,
            on_save=DamageOnSave.NONE,
            condition_on_fail=condition,
        )

    @staticmethod
    def dex_none(caster, target, dc: int, damage: int,
                 damage_type: str = "fire") -> SaveResult:
        """DEX save, no damage on success. Evasion-style effects."""
        return SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=dc,
            on_save=DamageOnSave.NONE,
            damage=damage, damage_type=damage_type,
        )


# ---------------------------------------------------------------------------
# Ability name normaliser
# ---------------------------------------------------------------------------

_ABILITY_MAP = {
    "strength":     "Str", "str": "Str",
    "dexterity":    "Dex", "dex": "Dex",
    "constitution": "Con", "con": "Con",
    "intelligence": "Int", "int": "Int",
    "wisdom":       "Wis", "wis": "Wis",
    "charisma":     "Cha", "cha": "Cha",
}

def normalise_ability(name: str) -> str:
    """
    Convert any common ability name variant to the StatBlock key.
    e.g. "Dexterity", "DEX", "dex" → "Dex"
    Raises ValueError for unknown names.
    """
    key = _ABILITY_MAP.get(name.lower())
    if key is None:
        raise ValueError(f"Unknown ability name: {name!r}")
    return key