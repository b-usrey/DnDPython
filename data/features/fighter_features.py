"""
data/features/fighter_features.py

Fighter class features — all combat-relevant features through level 20.

Base fighter
  lv1   Second Wind          (bonus action: heal 1d10 + level, once per rest)
  lv1   Fighting Style       (chosen at character creation — e.g. Archery, Defense)
  lv2   Action Surge         (1 extra action per short rest)
  lv5   Extra Attack         (2 attacks per action)
  lv9   Indomitable          (reroll a failed save, 1/2/3 uses)
  lv11  Extra Attack II      (3 attacks per action)
  lv17  Action Surge II      (upgrade to 2 uses)
  lv17  Indomitable II       (upgrade to 2 uses — handled by Indomitable attach)
  lv20  Extra Attack III     (4 attacks per action)

Champion subclass
  lv3   Improved Critical    (crit on 19-20)
  lv7   Remarkable Athlete   (skill/jump bonus — non-combat, skip)
  lv10  Additional Fighting Style (second style choice)
  lv15  Superior Critical    (crit on 18-20)
  lv18  Survivor             (regen 5 + CON mod HP at turn start when below half)
"""
import random
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Level 1 — Second Wind
# ---------------------------------------------------------------------------

class SecondWind(Feature):
    """
    Bonus action: regain 1d10 + fighter level HP once per short rest.
    AI triggers automatically when HP drops below 50% on turn start.
    """
    name = "Second Wind"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._used = False

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if self._used:
            return
        hp_frac = creature.hp / max(creature.max_hp, 1)
        if hp_frac < 0.5 and creature.actions.use_bonus_action():
            fighter_level = next(
                (lvl for cls, lvl in getattr(creature, "classes", [])
                 if cls == "Fighter"), 1
            )
            healed = random.randint(1, 10) + fighter_level
            creature.heal(healed)
            self._used = True
            print(f"  {creature.name} uses Second Wind — heals {healed} HP "
                  f"({creature.hp}/{creature.max_hp})")


# ---------------------------------------------------------------------------
# Level 2 — Action Surge
# ---------------------------------------------------------------------------

class ActionSurge(Feature):
    """
    Once per short rest: take one additional action on your turn.
    At lv17 (Action Surge II) this upgrades to 2 uses.
    """
    name = "Action Surge"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.max_action_surges = 1
        owner.actions.remaining_surges  = 1
        print(f"  {owner.name} gains Action Surge")


class ActionSurgeII(Feature):
    """Lv17 upgrade — increases Action Surge to 2 uses per short rest."""
    name = "Action Surge II"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.max_action_surges = 2
        owner.actions.remaining_surges  = min(2, owner.actions.remaining_surges + 1)
        print(f"  {owner.name}: Action Surge upgraded to 2 uses")


# ---------------------------------------------------------------------------
# Level 5 / 11 / 20 — Extra Attack
# ---------------------------------------------------------------------------

class ExtraAttack(Feature):
    """Lv5: 2 attacks per action (extra_attacks = 1)."""
    name = "Extra Attack"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 1
        owner.actions.remaining_extra_attacks = max(
            owner.actions.remaining_extra_attacks, 1
        )
        print(f"  {owner.name} gains Extra Attack (2 attacks)")


class ExtraAttackII(Feature):
    """Lv11: 3 attacks per action (extra_attacks = 2)."""
    name = "Extra Attack II"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 2
        owner.actions.remaining_extra_attacks = max(
            owner.actions.remaining_extra_attacks, 2
        )
        print(f"  {owner.name}: Extra Attack upgraded to 3 attacks")


class ExtraAttackIII(Feature):
    """Lv20: 4 attacks per action (extra_attacks = 3)."""
    name = "Extra Attack III"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 3
        owner.actions.remaining_extra_attacks = max(
            owner.actions.remaining_extra_attacks, 3
        )
        print(f"  {owner.name}: Extra Attack upgraded to 4 attacks")


# ---------------------------------------------------------------------------
# Level 9 — Indomitable
# ---------------------------------------------------------------------------

class Indomitable(Feature):
    """
    When you fail a saving throw, reroll it and use the new result.
    Uses: 1 at lv9, 2 at lv13, 3 at lv17.

    Hooks "saving_throw_resolved". If the save failed and uses remain,
    rolls a new d20 and checks it against the same DC and bonus.

    Damage reversal: if the reroll succeeds, heals back what was dealt:
      - HALF saves: heal back half (the difference between fail and succeed)
      - NONE saves: heal back all damage dealt
      - FULL saves: no reversal (damage is the same either way)
    Conditions recorded in result.notes are removed if the reroll succeeds.
    """
    name = "Indomitable"
    EVENT_MAP = {"saving_throw_resolved": "on_saving_throw_resolved"}

    def __init__(self):
        super().__init__()
        self._uses_remaining: int  = 0
        self._in_reroll:      bool = False   # prevent recursion

    def attach(self, owner, bus):
        super().attach(owner, bus)
        fighter_level = next(
            (lvl for cls, lvl in getattr(owner, "classes", [])
             if cls == "Fighter"), 1
        )
        # 1 use lv9-12, 2 uses lv13-16, 3 uses lv17+
        self._uses_remaining = 1 if fighter_level < 13 else 2 if fighter_level < 17 else 3
        print(f"  {owner.name}: Indomitable ({self._uses_remaining} uses)")

    def on_saving_throw_resolved(self, data):
        result = data.get("result")
        if not result:
            return
        if result.target is not self.owner:
            return
        if result.success:
            return
        if self._uses_remaining <= 0:
            return
        if self._in_reroll:
            return   # don't Indomitable the Indomitable reroll

        self._uses_remaining -= 1
        self._in_reroll = True

        # Reroll d20 with the same bonus
        new_d20   = random.randint(1, 20)
        new_total = new_d20 + result.bonus
        new_success = new_total >= result.dc

        print(f"  {self.owner.name} uses Indomitable! "
              f"Reroll {result.ability} save: {new_d20} + {result.bonus} = {new_total} "
              f"vs DC {result.dc} — {'SUCCESS' if new_success else 'FAILURE'} "
              f"({self._uses_remaining} uses left)")

        if new_success:
            # Reverse damage that was incorrectly applied
            from core.saving_throw import DamageOnSave
            if result.damage_dealt > 0:
                if result.on_save == DamageOnSave.HALF:
                    # Failed → full damage. Success → half damage.
                    # Reverse the extra half.
                    reversal = result.damage_dealt // 2
                elif result.on_save == DamageOnSave.NONE:
                    reversal = result.damage_dealt
                else:
                    reversal = 0
                if reversal > 0:
                    self.owner.heal(reversal)
                    print(f"  Indomitable: reversed {reversal} damage "
                          f"({self.owner.hp}/{self.owner.max_hp} HP)")

            # Remove any condition that was applied on failure
            for note in result.notes:
                if note.startswith("condition applied:"):
                    cond = note.split(":", 1)[1].strip()
                    self.owner.remove_condition(cond)
                    print(f"  Indomitable: removed condition '{cond}'")

        self._in_reroll = False


# ---------------------------------------------------------------------------
# Champion lv3 — Improved Critical
# ---------------------------------------------------------------------------

class ImprovedCritical(Feature):
    """
    Your weapon attacks score a critical hit on a roll of 19 or 20.
    Sets crit_threshold = 19 on the owner; Attack.__init__ reads it.
    """
    name = "Improved Critical"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        current = getattr(owner, "crit_threshold", 20)
        owner.crit_threshold = min(current, 19)
        print(f"  {owner.name}: Improved Critical (crits on 19-20)")


# ---------------------------------------------------------------------------
# Champion lv15 — Superior Critical
# ---------------------------------------------------------------------------

class SuperiorCritical(Feature):
    """
    Your weapon attacks score a critical hit on a roll of 18, 19, or 20.
    Replaces Improved Critical — sets crit_threshold = 18.
    """
    name = "Superior Critical"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.crit_threshold = 18
        print(f"  {owner.name}: Superior Critical (crits on 18-20)")


# ---------------------------------------------------------------------------
# Champion lv18 — Survivor
# ---------------------------------------------------------------------------

class Survivor(Feature):
    """
    At the start of your turn, if you have at least 1 HP but no more than
    half your HP, regain HP equal to 5 + your Constitution modifier.
    """
    name = "Survivor"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        hp      = creature.hp
        max_hp  = creature.max_hp
        if hp <= 0 or hp > max_hp // 2:
            return
        con_mod  = creature.statblock.mods.get("Con", 0)
        recovery = 5 + con_mod
        if recovery > 0:
            creature.heal(recovery)
            print(f"  {creature.name}: Survivor — regains {recovery} HP "
                  f"({creature.hp}/{max_hp})")


# ---------------------------------------------------------------------------
# Indomitable upgrade stubs — the single Indomitable class reads fighter
# level in attach() so these entries in the JSON need no code. Register them
# as no-ops so the loader doesn't print "feature not found" warnings.
# ---------------------------------------------------------------------------

class IndomitableII(Feature):
    """No-op stub — Indomitable reads level on attach."""
    name = "Indomitable II"


class IndomitableIII(Feature):
    """No-op stub — Indomitable reads level on attach."""
    name = "Indomitable III"


class RemarkableAthlete(Feature):
    """Non-combat skill bonus — no combat implementation needed."""
    name = "Remarkable Athlete"


# ---------------------------------------------------------------------------
# Fighting Style — Two-Weapon Fighting
# ---------------------------------------------------------------------------

class TwoWeaponFightingStyle(Feature):
    """
    Fighting Style: when you engage in two-weapon fighting you add your
    ability modifier to the damage of the off-hand attack.
    Sets twf_style=True on the owner; CombatManager reads this flag.
    """
    name = "Two-Weapon Fighting"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.twf_style = True
        print(f"  {owner.name}: Two-Weapon Fighting style "
              f"(off-hand adds ability mod to damage)")


# ---------------------------------------------------------------------------
# Feat — Dual Wielder
# ---------------------------------------------------------------------------

class DualWielder(Feature):
    """
    Feat: gain +1 AC while wielding a separate melee weapon in each hand,
    and you can use two-weapon fighting even when the weapons aren't light.
    Sets dual_wielder=True so _try_twf_attack skips the light-weapon check.
    """
    name = "Dual Wielder"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.dual_wielder = True
        owner.apply_misc_ac(1)
        print(f"  {owner.name}: Dual Wielder (+1 AC, non-light weapons qualify for TWF)")