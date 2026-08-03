"""
data/features/bard_features.py

Bard class features -- combat-relevant through level 5, matching this sim's
existing class-file scope (Sorcerer/Druid also stop authoring flavor-only
higher-level features once past the mid-tier spike).

  lv1   Bardic Inspiration   (bonus action: buffs an ally's next attack roll)
  lv1   Vicious Mockery      (cantrip: WIS save, psychic dmg + disadvantage)
  lv2   Jack of All Trades   (non-combat -- skill checks only)
  lv2   Song of Rest         (non-combat -- short rest only)
  lv3   Bard College         (subclass choice; see below)
  lv5   Font of Inspiration  (Bardic Inspiration recharges on short rest --
                              not simulated; this sim doesn't model rest
                              cycles mid-combat, so uses stay at CHA-mod
                              per combat throughout)

College of Lore (lv3)
  Cutting Words        (reaction: subtract a Bardic Inspiration die from an
                        enemy's roll -- not simulated; would need the same
                        kind of roll-interception as BardicInspiration but
                        aimed at enemies instead of allies. Deferred.)

College of Valor (lv3)
  Combat Inspiration   (Bardic Inspiration die can also boost damage/AC --
                        folded into BardicInspiration's flat EV bonus.)
  Extra Attack         (reuses the existing "Extra Attack" feature.)
"""
import random

from data.features.base import Feature
from data.features.combat_spells import _ActionSpell, _cantrip_scale, _spell_dc
from core.saving_throw import SavingThrow, DamageOnSave


def _bardic_die_size(level: int) -> int:
    if level >= 15:
        return 12
    if level >= 10:
        return 10
    if level >= 5:
        return 8
    return 6


# =============================================================================
# Bardic Inspiration
# =============================================================================

class BardicInspiration(Feature):
    """
    Bonus action: grant Bardic Inspiration to an ally, who can add the die
    to one attack roll, ability check, or saving throw of their choice
    within the next 10 minutes.

    Implementation: Bardic Inspiration is normally spent reactively (after
    seeing whether it's needed), which isn't something an ally's own AI
    turn can decide for itself here. Approximated instead as a flat
    +avg-die-value bonus applied automatically to the inspired ally's next
    attack roll -- same expected value, no reactive decision to model.
    Uses = CHA modifier per combat (rest-cycle granularity not modeled,
    consistent with Rage/Action Surge elsewhere in this sim). Targets
    whichever living ally currently has the lowest HP ratio, on the
    assumption they're the one who most needs the help landing a hit.
    """
    name = "Bardic Inspiration"
    EVENT_MAP = {"TurnStarted": "on_turn_started", "attack": "on_attack"}

    def __init__(self):
        super().__init__()
        self._uses_remaining = 0
        self._die_size = 6
        self._inspired = None

    def attach(self, owner, bus):
        super().attach(owner, bus)
        cha_mod = owner.statblock.mods.get("Cha", 0)
        self._uses_remaining = max(1, cha_mod)
        level = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Bard"), 1
        )
        self._die_size = _bardic_die_size(level)
        print(f"  {owner.name}: Bardic Inspiration ready "
              f"({self._uses_remaining} uses, d{self._die_size})")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        if self._uses_remaining <= 0 or self._inspired is not None:
            return
        battle_map = getattr(self.owner, "battle_map", None)
        if not battle_map:
            return
        allies = [
            c for c in battle_map.all_creatures()
            if c.team == self.owner.team and c is not self.owner and c.is_alive()
        ]
        if not allies:
            return
        if not self.owner.actions.use_bonus_action():
            return
        target = min(allies, key=lambda c: c.hp / max(c.max_hp, 1))
        self._inspired = target
        self._uses_remaining -= 1
        print(f"  {self.owner.name} inspires {target.name} with Bardic Inspiration "
              f"(d{self._die_size}, {self._uses_remaining} uses left)")

    def on_attack(self, data):
        if not self._inspired:
            return
        if data.get("attacker") is not self._inspired:
            return
        attack = data.get("attack")
        bonus = (self._die_size + 1) / 2.0
        if attack:
            attack.to_hit_mod += bonus
            print(f"  {self._inspired.name}: Bardic Inspiration adds "
                  f"+{bonus:.1f} to the attack roll!")
        self._inspired = None


# =============================================================================
# Vicious Mockery
# =============================================================================

class ViciousMockery(_ActionSpell):
    """
    Cantrip. WIS save or take psychic damage and have disadvantage on the
    next attack roll it makes before the end of its next turn.
    """
    name       = "Vicious Mockery"
    IS_CANTRIP = True
    EVENT_MAP  = {**_ActionSpell.EVENT_MAP, "attack": "on_attack"}

    def __init__(self):
        super().__init__()
        self._mocked = None

    def _cast(self, caster, target, _slot):
        n   = _cantrip_scale(caster)
        dmg = sum(random.randint(1, 4) for _ in range(n))
        result = SavingThrow.roll(
            caster=caster, target=target,
            ability="Wis", dc=_spell_dc(caster),
            on_save=DamageOnSave.NONE,
            damage=dmg, damage_type="psychic",
        )
        if not result.success:
            self._mocked = target
        print(f"  {caster.name}: Vicious Mockery! ({n}d4 psychic, DC {_spell_dc(caster)})")

    def on_attack(self, data):
        if not self._mocked:
            return
        attacker = data.get("attacker")
        if attacker is not self._mocked:
            return
        attack = data.get("attack")
        if attack:
            attack.disadvantage = True
            print(f"  {attacker.name}: shaken by Vicious Mockery -- "
                  f"disadvantage on this attack!")
        self._mocked = None
