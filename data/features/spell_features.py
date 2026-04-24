import random
from data.features.base import Feature
from core.saving_throw import CommonSaves


class HellishRebuke(Feature):
    """
    Reaction (Phase 4 — "damage_dealt"): when the owner takes damage
    from a creature that hit them, the attacker must make a DEX save
    (DC 11) or take 2d10 fire damage (half on success).

    Hooks "damage_dealt" which fires after take_damage() has run but
    before the attack is fully resolved. The target has taken damage
    at this point but is still alive to cast the reaction if HP > 0.
    """
    name = "Hellish Rebuke"
    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    SAVE_DC = 11

    def on_damage_dealt(self, data):
        target   = data.get("target")
        attacker = data.get("attacker")
        attack   = data.get("attack")

        if target is not self.owner:
            return
        if not attack or not attack.result.get("hit", False):
            return
        if not self.owner.is_alive():
            return   # can't cast if the hit killed us
        if not self.owner.actions.use_reaction():
            return

        damage = sum(random.randint(1, 10) for _ in range(2))

        print(
            f"  {self.owner.name} uses Hellish Rebuke on "
            f"{attacker.name}! ({damage} fire damage, DEX save DC {self.SAVE_DC})"
        )

        CommonSaves.dex_half(
            caster      = self.owner,
            target      = attacker,
            dc          = self.SAVE_DC,
            damage      = damage,
            damage_type = "fire",
        )
class ConcentrationACBonus(Feature):
    """Base for any concentration effect that grants a flat AC bonus."""
    BONUS = 0   # override in subclass

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.start_concentration(self.name, feature=self)
        owner.apply_misc_ac(self.BONUS)
        print(f"  {owner.name}: {self.name} (+{self.BONUS} AC → {owner.ac})")

    def on_concentration_broken(self):
        self.owner.apply_misc_ac(-self.BONUS)
        print(f"  {self.owner.name}: {self.name} fades (AC → {self.owner.ac})")

    def detach(self):
        if self.owner.concentration == self.name:
            self.owner.break_concentration()
        super().detach()


class ShieldOfFaith(ConcentrationACBonus):
    name  = "Shield of Faith"
    BONUS = 2

class BarkskinSpell(ConcentrationACBonus):
    name  = "Barkskin"
    BONUS = 3   # sets minimum AC 16 — would need a min-AC variant



class ShieldSpell(Feature):
    """
    Reaction (Phase 2 — "hit"): when hit by an attack, gain +5 AC until
    the start of your next turn, potentially turning the hit into a miss.

    Timing:
      - Fires in Phase 2, after the hit is confirmed
      - If attack_total < new_ac, sets result["hit"] = False — declare_attack
        then skips Phases 3 and 4 (no damage, no damage_dealt reactions)
      - If it still hits even with +5, the spell is not worth casting
        (in AI mode) but a player might cast it for the duration bonus

    The +5 AC lasts until the owner's next turn start and is tracked via
    apply_misc_ac() so it interacts correctly with the AC system.
    """
    name = "Shield"
    EVENT_MAP = {
        "hit":         "on_hit",
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._active = False

    def on_hit(self, data):
        target = data.get("target")
        attack = data.get("attack")

        if target is not self.owner:
            return
        if not attack:
            return
        if not self.owner.actions.use_reaction():
            return

        # Apply the +5 AC bonus
        self.owner.apply_misc_ac(+5)
        self._active = True

        new_ac    = self.owner.ac
        atk_total = attack.result.get("attack_total", 0)

        if atk_total < new_ac:
            # The +5 turns the hit into a miss
            attack.result["hit"] = False
            print(f"  {self.owner.name} casts Shield! "
                  f"(+5 AC → {new_ac}, attack total {atk_total} now misses)")
        else:
            # Still hits, but the duration bonus applies going forward
            print(f"  {self.owner.name} casts Shield! "
                  f"(+5 AC → {new_ac}, but {atk_total} still hits)")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner and self._active:
            self.owner.apply_misc_ac(-5)
            self._active = False
            print(f"  {self.owner.name}'s Shield expires")