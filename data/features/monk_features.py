"""
data/features/monk_features.py

Monk class features -- combat-relevant through level 5.

  lv1   Martial Arts           (scaling unarmed/monk-weapon die, DEX option,
                                bonus-action unarmed strike)
  lv1   Unarmored Defense      (AC = 10 + DEX + WIS when unarmored -- flag,
                                same documented limitation as Barbarian's
                                Unarmored Defense: not yet wired into
                                setup_ac)
  lv2   Ki                     (resource pool; fuels Flurry of Blows below)
  lv2   Flurry of Blows        (1 ki, bonus action: 2 extra unarmed strikes)
  lv2   Patient Defense        (1 ki, bonus action Dodge -- not simulated;
                                overlaps with the tactical AI's existing
                                retreat/kite strategy options)
  lv2   Step of the Wind       (1 ki, bonus action Disengage/Dash -- not
                                simulated, same reason as Patient Defense)
  lv2   Unarmored Movement    (+speed while unarmored, scales with level)
  lv3   Deflect Missiles       (reaction: reduce incoming ranged weapon
                                damage)
  lv3   Monastic Tradition     (subclass choice; non-combat in this sim)
  lv4   Slow Fall              (non-combat -- falling damage only)
  lv5   Extra Attack           (reuses the existing "Extra Attack" feature)
  lv5   Stunning Strike        (1 ki on hit: CON save or stunned)
"""
import random

from data.features.base import Feature
from core.item import Item
from core.saving_throw import SavingThrow, DamageOnSave


def _monk_level(owner) -> int:
    return next(
        (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Monk"), 1
    )


def _martial_arts_die(level: int) -> int:
    if level >= 17:
        return 10
    if level >= 11:
        return 8
    if level >= 5:
        return 6
    return 4


def _ki_save_dc(owner) -> int:
    return 8 + owner.proficiency + owner.statblock.mods.get("Wis", 0)


_MONK_WEAPON_NAMES = {
    "quarterstaff", "dagger", "handaxe", "javelin", "light hammer", "mace",
    "sickle", "spear", "dart", "shortsword",
}


# =============================================================================
# Martial Arts
# =============================================================================

class MartialArts(Feature):
    """
    Unarmed strikes and monk weapons (shortsword + any simple melee weapon
    without the two-handed or heavy property) use a scaling martial-arts
    die once it exceeds the weapon's own die, and can use DEX instead of
    STR for both the attack and damage rolls.

    Implementation: class features attach during PlayerCharacter.__init__,
    before ScenarioLoader equips any items, so the weapon-upgrade scan
    can't run at attach time -- it would find equipped_items empty. It
    runs instead the first time this creature's turn starts (equip_item +
    setup_ac have both run by then), upgrading the ability/damage_die on
    any already-equipped monk weapon and injecting an "Unarmed Strike"
    pseudo-item so unarmed attacks compete fairly in TacticalAI's normal
    weapon-scoring pass -- no changes needed there. Also grants a bonus-
    action unarmed strike after the Attack action every turn, mirroring
    Polearm Master's bonus-attack pattern (grant_temp_extra_attack at
    TurnStarted, gated on a free bonus action). Yields the bonus action to
    Ki's Flurry of Blows when ki is available, since Flurry is strictly
    better (2 attacks instead of 1).
    """
    name = "Martial Arts"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._weapons_upgraded = False

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._die = _martial_arts_die(_monk_level(owner))
        print(f"  {owner.name}: Martial Arts ready (d{self._die} unarmed/monk-weapon die)")

    def _upgrade_weapons(self):
        owner = self.owner
        str_mod = owner.statblock.mods.get("Str", 0)
        dex_mod = owner.statblock.mods.get("Dex", 0)
        use_dex = dex_mod >= str_mod

        for item in owner.equipped_items:
            if item.item_type != "weapon":
                continue
            if item.name.lower() not in _MONK_WEAPON_NAMES:
                continue
            props = getattr(item, "properties", [])
            if "two-handed" in props or "heavy" in props:
                continue
            try:
                cur_sides = int(item.damage_die.split("d")[1])
            except (ValueError, AttributeError, IndexError):
                cur_sides = 0
            if self._die > cur_sides:
                item.damage_die = f"1d{self._die}"
            if use_dex:
                item.ability = "Dex"

        unarmed = Item(
            "Unarmed Strike", "weapon",
            damage_die=f"1d{self._die}", damageType="bludgeoning",
            ability="Dex" if use_dex else "Str",
            weapon_type="simple", attack_type="melee",
            normal_range=5, long_range=5,
            attack_bonus=0, damage_bonus=0, properties=["monk"],
        )
        owner.equipped_items.append(unarmed)
        print(f"  {owner.name}: Martial Arts -- "
              f"{'DEX' if use_dex else 'STR'}-based unarmed/monk-weapon attacks (d{self._die})")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        if not self._weapons_upgraded:
            self._upgrade_weapons()
            self._weapons_upgraded = True
        ki = next(
            (f for f in self.owner.features if isinstance(f, Ki)), None
        )
        if ki and ki.ki_remaining > 0:
            return   # Flurry of Blows is strictly better -- let it take the bonus action
        if not self.owner.actions.use_bonus_action():
            return
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Martial Arts -- bonus-action unarmed strike!")


# =============================================================================
# Unarmored Defense (Monk)
# =============================================================================

class UnarmoredDefenseMonk(Feature):
    """
    AC = 10 + DEX mod + WIS mod when not wearing armor or using a shield.
    Sets a flag, matching Barbarian's Unarmored Defense -- neither flag is
    currently consulted by PlayerCharacter.setup_ac(), a pre-existing gap
    in this sim (not introduced here).
    """
    name = "Unarmored Defense (Monk)"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.monk_unarmored_defense = True
        print(f"  {owner.name}: Unarmored Defense -- AC = 10+DEX+WIS if unarmored")


# =============================================================================
# Unarmored Movement
# =============================================================================

def _unarmored_movement_bonus(level: int) -> int:
    if level >= 18:
        return 30
    if level >= 14:
        return 25
    if level >= 10:
        return 20
    if level >= 6:
        return 15
    return 10


class UnarmoredMovement(Feature):
    """+speed while not wearing armor or wielding a shield, scaling with
    monk level. Applied unconditionally at attach time, matching
    Barbarian's Fast Movement (no dynamic armor check there either)."""
    name = "Unarmored Movement"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        bonus = _unarmored_movement_bonus(_monk_level(owner))
        owner.speed += bonus
        print(f"  {owner.name}: Unarmored Movement -- speed {owner.speed}ft")


# =============================================================================
# Ki / Flurry of Blows
# =============================================================================

class Ki(Feature):
    """
    Ki point pool = monk level (from level 2). Fuels Flurry of Blows,
    Patient Defense, and Step of the Wind. Only Flurry of Blows is
    simulated here -- Patient Defense and Step of the Wind spend the same
    bonus action for pure defense/mobility, which the tactical AI already
    covers through its own retreat/kite strategy options.

    Uses per combat only (rest-cycle granularity not modeled, consistent
    with Rage/Action Surge elsewhere in this sim). ki_remaining is also
    read/spent directly by MartialArts (bonus-action priority) and
    StunningStrike (1 ki per stun attempt).
    """
    name = "Ki"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self.ki_remaining = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self.ki_remaining = _monk_level(owner)
        print(f"  {owner.name}: Ki ready ({self.ki_remaining} points)")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        if self.ki_remaining <= 0:
            return
        if not self.owner.actions.use_bonus_action():
            return
        self.ki_remaining -= 1
        self.owner.event_manager.broadcast("resource_spent", {
            "creature":  self.owner,
            "resource":  "ki",
            "remaining": self.ki_remaining,
            "detail":    "Flurry of Blows",
        })
        self.owner.actions.grant_temp_extra_attack()
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Flurry of Blows! "
              f"(2 bonus unarmed strikes, {self.ki_remaining} ki left)")


# =============================================================================
# Deflect Missiles
# =============================================================================

class DeflectMissiles(Feature):
    """
    Reaction: reduce damage from a ranged weapon attack that hits you by
    1d10 + DEX mod + monk level. Catching and throwing the missile back is
    a non-combat flavor option, not simulated here.

    Implementation: mirrors Heavy Armor Master's pattern -- hooks
    "damage_dealt" (damage already applied) and heals back the reduction
    amount, gated on having a reaction available.
    """
    name = "Deflect Missiles"
    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._level = _monk_level(owner)

    def on_damage_dealt(self, data):
        target = data.get("target")
        if target is not self.owner:
            return
        attack = data.get("attack")
        if not (attack and getattr(attack, "range", False)):
            return
        if not self.owner.actions.use_reaction():
            return
        dex_mod = self.owner.statblock.mods.get("Dex", 0)
        reduction = random.randint(1, 10) + dex_mod + self._level
        reduction = min(reduction, self.owner.hp)
        if reduction > 0:
            self.owner.heal(reduction)
            print(f"  {self.owner.name}: Deflect Missiles -- "
                  f"reduces the hit by {reduction} damage!")


# =============================================================================
# Stunning Strike
# =============================================================================

class StunningStrike(Feature):
    """
    Lv5. When you hit with a monk weapon or unarmed strike, spend 1 ki to
    force a CON save (your ki save DC) or the target is stunned until the
    end of your next turn.

    Implementation note: this sim doesn't model turn-skipping for
    incapacitating conditions -- the same simplification already accepted
    for Hold Person's "paralyzed" -- so a stunned target still acts
    normally, but attacks against it get advantage (tactical_ai.py's
    existing paralyzed/restrained/blinded advantage check is extended to
    include "stunned"). AI always spends ki on a hit when available --
    Stunning Strike is close to always worth it for a monk.
    """
    name = "Stunning Strike"
    EVENT_MAP = {"hit": "on_hit", "TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._stunned_target = None

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        item = attack.item if attack else None
        is_monk_weapon = bool(item) and (
            item.name == "Unarmed Strike" or item.name.lower() in _MONK_WEAPON_NAMES
        )
        if not is_monk_weapon:
            return
        ki = next((f for f in self.owner.features if isinstance(f, Ki)), None)
        if not ki or ki.ki_remaining <= 0:
            return
        target = data.get("target")
        if not target:
            return
        ki.ki_remaining -= 1
        self.owner.event_manager.broadcast("resource_spent", {
            "creature":  self.owner,
            "resource":  "ki",
            "remaining": ki.ki_remaining,
            "detail":    "Stunning Strike",
        })
        result = SavingThrow.roll(
            caster=self.owner, target=target,
            ability="Con", dc=_ki_save_dc(self.owner),
            on_save=DamageOnSave.NONE, damage=0, damage_type="",
            condition_on_fail="stunned",
        )
        if not result.success:
            self._stunned_target = target
            print(f"  {self.owner.name}: Stunning Strike -- {target.name} is STUNNED!")
        else:
            print(f"  {self.owner.name}: Stunning Strike -- {target.name} resists.")

    def on_turn_started(self, ctx):
        # Stunned lasts until the end of the monk's next turn; clear it the
        # next time the monk's own turn comes back around.
        if ctx.get("creature") is not self.owner:
            return
        if self._stunned_target:
            self._stunned_target.remove_condition("stunned")
            self._stunned_target = None
