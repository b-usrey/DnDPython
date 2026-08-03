"""
data/features/feat_features.py

Combat-relevant SRD feats.

Implemented:
  Sharpshooter        — ranged -5/+10 (original)
  Great Weapon Master — heavy melee -5/+10; bonus attack on crit/kill
  Savage Attacker     — reroll melee damage dice once per turn, take higher
  Alert               — +5 initiative, cannot be surprised
  Tough               — +2 max HP per level (retroactive)
  Mobile              — +10 ft speed; no opportunity attacks after attacking
  Heavy Armor Master  — +1 Str; reduce B/P/S damage by 3 in heavy armor
  Sentinel            — reaction attack when adjacent ally is attacked; target
                        cannot disengage (speed 0 on OA hit)
  Polearm Master      — bonus action butt-end attack (1d4) with polearms
  Lucky               — 3 luck points per long rest; reroll attack rolls
  Resilient           — +1 to a stat + proficiency in that saving throw
                        (Con default; named variants for each stat)
  Crossbow Expert     — no melee disadvantage with ranged weapons;
                        bonus hand-crossbow attack after Attack action
  Dual Wielder        — already in fighter_features.py (registered there)
"""
import random
from data.features.base import Feature
from core.attack import WeaponAttack, hit_probability

# ── Helpers ───────────────────────────────────────────────────────────────────

_POLEARM_NAMES = {"quarterstaff", "glaive", "halberd", "pike", "spear"}
_HAND_XBOW_NAMES = {"hand crossbow"}


def _wears_heavy_armor(creature) -> bool:
    return any(
        getattr(i, "armor_type", "") == "heavy"
        for i in getattr(creature, "equipped_items", [])
    )


def _wielded_weapon(creature, melee=True):
    """Return the first equipped weapon of the requested attack type, or None."""
    for item in getattr(creature, "equipped_items", []):
        if getattr(item, "item_type", "") == "weapon":
            is_range = getattr(item, "attack_type", "melee") == "range"
            if melee and not is_range:
                return item
            if not melee and is_range:
                return item
    return None


# =============================================================================
# Original feat
# =============================================================================

def _worth_the_power_attack_trade(attack, target) -> bool:
    """
    Shared EV comparison for Sharpshooter/Great Weapon Master's -5/+10
    trade: take it only when it raises expected damage, using the
    attacker's actual to-hit bonus and the target's actual AC -- not a
    flat target-HP threshold, which gets the same answer regardless of
    whether the attacker can realistically land the harder shot at all.

    Expected damage is capped at the target's remaining HP (same pattern
    used for AOE placement scoring) so the trade isn't taken to pile
    overkill damage onto a target the normal hit would already finish --
    once both options are HP-capped to the same value, the -5 accuracy
    hit no longer buys anything, and the EV comparison naturally declines
    the trade without needing a separate "is this overkill" check.
    """
    num, sides = attack.base_dice
    avg_damage = num * (sides + 1) / 2.0 + attack.damage_mod
    target_hp  = getattr(target, "hp", avg_damage + 10)

    p_normal = hit_probability(attack.to_hit_mod, target.ac)
    p_traded = hit_probability(attack.to_hit_mod - 5, target.ac)

    ev_normal = p_normal * min(avg_damage, target_hp)
    ev_traded = p_traded * min(avg_damage + 10, target_hp)

    return ev_traded > ev_normal


class Sharpshooter(Feature):
    """
    Feat. Before making a ranged weapon attack you can opt to take
    -5 to hit in exchange for +10 damage on a hit.

    The AI takes the trade only when it raises expected damage -- see
    _worth_the_power_attack_trade() -- rather than using a flat target-HP
    threshold that ignored the attacker's own accuracy and the target's AC.
    """
    name = "Sharpshooter"

    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attack   = data.get("attack")
        attacker = data.get("attacker")
        target   = data.get("target")

        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or not attack.range:
            return

        if _worth_the_power_attack_trade(attack, target):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
            attack.tags.add("sharpshooter")


# =============================================================================
# Great Weapon Master
# =============================================================================

class GreatWeaponMaster(Feature):
    """
    Two effects:
    1. -5/+10 trade: when making a melee attack with a heavy weapon, the AI
       takes the trade only when it raises expected damage -- see
       _worth_the_power_attack_trade() -- rather than a flat target-HP
       threshold that ignored the attacker's own accuracy and the target's AC.
    2. Bonus attack: when you score a critical hit or reduce a creature to 0 HP
       with a melee weapon attack, use your bonus action to make one more
       melee weapon attack.
    """
    name = "Great Weapon Master"

    EVENT_MAP = {
        "attack":       "on_attack",
        "damage_dealt": "on_damage_dealt",
    }

    def on_attack(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        target   = data.get("target")
        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or attack.range:
            return
        item = attack.item
        if not item or "heavy" not in getattr(item, "properties", []):
            return
        if _worth_the_power_attack_trade(attack, target):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
            attack.tags.add("great_weapon_master")

    def on_damage_dealt(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        target   = data.get("target")
        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or attack.range:
            return
        is_crit = getattr(attack, "critical", False)
        is_kill = target is not None and not target.is_alive()
        if (is_crit or is_kill) and self.owner.actions.use_bonus_action():
            self.owner.actions.grant_temp_extra_attack()
            print(f"  {self.owner.name}: Great Weapon Master — "
                  f"bonus attack from {'crit' if is_crit else 'kill'}!")


# =============================================================================
# Savage Attacker
# =============================================================================

class SavageAttacker(Feature):
    """
    Once per turn when rolling melee weapon damage, reroll all the weapon's
    damage dice and use either total — whichever is higher.

    Implementation: on the "hit" event (before roll_damage runs), we pre-roll
    the base dice twice, keep the higher result, store it in damage_mod, and
    zero out base_dice so roll_damage doesn't also roll them. Critical hits
    are handled by doubling the better result when attack.critical is True.
    """
    name = "Savage Attacker"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._used = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used = False

    def on_hit(self, data):
        if self._used:
            return
        attacker = data.get("attacker")
        attack   = data.get("attack")
        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or attack.range:
            return

        num, sides = attack.base_dice
        roll1 = sum(random.randint(1, sides) for _ in range(num))
        roll2 = sum(random.randint(1, sides) for _ in range(num))
        better = max(roll1, roll2)
        if attack.critical:
            better *= 2   # crit doubles the base dice

        attack.damage_mod += better
        attack.base_dice   = (0, sides)   # prevent roll_damage rolling them again
        self._used = True
        print(f"  {self.owner.name}: Savage Attacker — "
              f"rolled {roll1} vs {roll2}, using {better}!")


# =============================================================================
# Alert
# =============================================================================

class Alert(Feature):
    """
    +5 bonus to initiative. Cannot be surprised (flag; CombatManager reads it).
    Other creatures don't gain advantage on attack rolls against you as a result
    of being hidden before you act.
    """
    name = "Alert"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.initiative_mod = getattr(owner, "initiative_mod", 0) + 5
        owner.alert          = True
        print(f"  {owner.name}: Alert (+5 initiative, cannot be surprised)")


# =============================================================================
# Tough
# =============================================================================

class Tough(Feature):
    """
    Your hit point maximum increases by 2 for each level you have.
    Retroactive: on attach, grants +2 × total_level HP immediately.
    """
    name = "Tough"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        level  = getattr(owner, "total_level", 1)
        bonus  = level * 2
        owner._max_hp     += bonus
        owner._current_hp  = min(owner._current_hp + bonus, owner._max_hp)
        print(f"  {owner.name}: Tough — +{bonus} max HP ({owner._max_hp} total)")


# =============================================================================
# Mobile
# =============================================================================

class Mobile(Feature):
    """
    +10 ft walking speed.
    After you make a melee attack against a creature, you don't provoke
    opportunity attacks from that creature for the rest of the turn.
    (Speed bonus applied on attach; OA prevention flagged via owner.mobile.)
    """
    name = "Mobile"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.speed += 10
        owner.mobile = True
        print(f"  {owner.name}: Mobile — speed {owner.speed}ft, no OA after attacking")


# =============================================================================
# Heavy Armor Master
# =============================================================================

class HeavyArmorMaster(Feature):
    """
    +1 Strength.
    While wearing heavy armor, reduce bludgeoning, piercing, and slashing
    damage from non-magical weapons by 3.

    Implementation: hooks "damage_dealt" (after damage applied) and heals
    back 3 HP if the attack was non-magical B/P/S and the owner wears heavy
    armor — effectively reducing the net damage taken.
    """
    name = "Heavy Armor Master"

    _RESIST_TYPES = {"bludgeoning", "piercing", "slashing"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.statblock.scores["Str"] = owner.statblock.scores.get("Str", 10) + 1
        owner.statblock._recompute_mods()
        print(f"  {owner.name}: Heavy Armor Master (+1 Str, -3 B/P/S in heavy armor)")

    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    def on_damage_dealt(self, data):
        target  = data.get("target")
        attack  = data.get("attack")
        if target is not self.owner:
            return
        if not isinstance(attack, WeaponAttack):
            return
        if "magical" in getattr(attack, "tags", set()):
            return
        dtype = getattr(attack, "damage_type", "")
        if dtype.lower() not in self._RESIST_TYPES:
            return
        if not _wears_heavy_armor(self.owner):
            return
        reduction = min(3, self.owner.hp)   # can't reduce below 0
        if reduction > 0:
            self.owner.heal(reduction)
            print(f"  {self.owner.name}: Heavy Armor Master — "
                  f"reduced {dtype} damage by {reduction}")


# =============================================================================
# Sentinel
# =============================================================================

class Sentinel(Feature):
    """
    Three effects:
    1. Reaction attack when a creature within 5ft attacks an ally (not you).
    2. Creatures you hit with an opportunity attack have their speed reduced
       to 0 for the rest of the turn (tag check; CombatManager honours it).
    3. Creatures cannot Disengage to avoid your opportunity attacks
       (flag-based; CombatManager reads owner.sentinel).

    Hooks "damage_dealt": if an adjacent attacker hits an ally, use reaction
    to strike back.
    """
    name = "Sentinel"

    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.sentinel = True
        print(f"  {owner.name}: Sentinel — reaction to protect allies")

    def on_damage_dealt(self, data):
        target   = data.get("target")
        attacker = data.get("attacker")
        attack   = data.get("attack")
        # We want: someone else (an ally) was hit, attacker is adjacent to us
        if target is self.owner:
            return
        if attacker is self.owner:
            return
        if not attack or not attack.result.get("hit"):
            return
        if getattr(target, "team", None) != getattr(self.owner, "team", None):
            return
        if not self._owner_can_react():
            return
        if not self.owner.actions.use_reaction():
            return

        # Check adjacency (≤1 grid square = 5ft)
        if getattr(self.owner, "pos", None) and getattr(attacker, "pos", None):
            dx = abs(self.owner.pos[0] - attacker.pos[0])
            dy = abs(self.owner.pos[1] - attacker.pos[1])
            if max(dx, dy) > 1:
                self.owner.actions.reactions += 1   # refund
                return

        weapon = _wielded_weapon(self.owner, melee=True)
        if not weapon:
            self.owner.actions.reactions += 1
            return

        print(f"  {self.owner.name}: Sentinel — protecting {target.name}, "
              f"striking {attacker.name}!")
        WeaponAttack(self.owner, attacker, weapon.damage_die, item=weapon).declare_attack()


# =============================================================================
# Polearm Master
# =============================================================================

class PolearmMaster(Feature):
    """
    When you take the Attack action and attack with a glaive, halberd, pike,
    quarterstaff, or spear, you can use a bonus action to make a melee attack
    with the butt end of the weapon (1d4 bludgeoning).

    Implementation: on TurnStarted, if the owner is wielding a polearm and
    has a bonus action available, grant one temporary extra attack for the
    turn (the combat manager will fire it as a normal 1d4 attack using the
    same weapon).  The damage die override uses a flag on the owner.
    """
    name = "Polearm Master"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        weapon = _wielded_weapon(self.owner, melee=True)
        if not weapon:
            return
        wname = weapon.name.lower()
        if not any(p in wname for p in _POLEARM_NAMES):
            return
        if not self.owner.actions.use_bonus_action():
            return
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Polearm Master — "
              f"bonus butt-end attack with {weapon.name}!")


# =============================================================================
# Lucky
# =============================================================================

class Lucky(Feature):
    """
    You have 3 luck points per long rest. Whenever you make an attack roll,
    ability check, or saving throw, you can spend one luck point to roll an
    additional d20 and choose which die to use.

    Implementation: hooks "attack" — if owner's attack roll seems low
    (d20 < 10) and luck points remain, rerolls and takes the better result
    by adding the delta to to_hit_mod. Resets on long rest.
    """
    name = "Lucky"
    LUCK_THRESHOLD = 10   # AI spends a point when the natural d20 is below this

    EVENT_MAP = {"attack": "on_attack"}

    def __init__(self):
        super().__init__()
        self._luck_points = 3

    def attach(self, owner, bus):
        super().attach(owner, bus)
        print(f"  {owner.name}: Lucky (3 luck points)")

    def on_attack(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack):
            return
        if self._luck_points <= 0:
            return
        # Peek at a "prospective" d20 to decide whether to spend luck.
        # We simulate the original roll by reading to_hit_mod baseline.
        # Simple AI heuristic: spend a point once per encounter if available.
        trial_roll = random.randint(1, 20)
        if trial_roll >= self.LUCK_THRESHOLD:
            return   # roll looks fine, save the point

        reroll = random.randint(1, 20)
        better = max(trial_roll, reroll)
        self._luck_points -= 1
        # Express the improvement as a to_hit_mod bonus for this attack
        attack.to_hit_mod += (better - trial_roll)
        attack.tags.add("lucky")
        print(f"  {self.owner.name}: Lucky! rerolled {trial_roll}→{better} "
              f"({self._luck_points} points left)")


# =============================================================================
# Resilient — generic (Con) and per-stat named variants
# =============================================================================

class _ResilientBase(Feature):
    """
    +1 to the chosen ability score, and proficiency in saving throws using
    that ability.  The stat is defined by the subclass attribute `_stat`.
    """
    _stat: str = "Con"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        stat = self._stat
        owner.statblock.scores[stat] = owner.statblock.scores.get(stat, 10) + 1
        owner.statblock._recompute_mods()
        owner.statblock.save_profs[stat] = 1
        print(f"  {owner.name}: Resilient ({stat}) — +1 {stat}, {stat} save proficiency")


class Resilient(_ResilientBase):
    """Default: +1 Con, Constitution save proficiency (most common for martials)."""
    name = "Resilient"
    _stat = "Con"


class ResilientStr(_ResilientBase):
    name = "Resilient (Str)"
    _stat = "Str"


class ResilientDex(_ResilientBase):
    name = "Resilient (Dex)"
    _stat = "Dex"


class ResilientCon(_ResilientBase):
    name = "Resilient (Con)"
    _stat = "Con"


class ResilientInt(_ResilientBase):
    name = "Resilient (Int)"
    _stat = "Int"


class ResilientWis(_ResilientBase):
    name = "Resilient (Wis)"
    _stat = "Wis"


class ResilientCha(_ResilientBase):
    name = "Resilient (Cha)"
    _stat = "Cha"


# =============================================================================
# Crossbow Expert
# =============================================================================

class CrossbowExpert(Feature):
    """
    Three effects:
    1. Ignore the loading property of crossbows (passive; handled by having
       enough attacks).
    2. Being within 5ft of a hostile creature doesn't impose disadvantage on
       your ranged attack rolls.
    3. When you use the Attack action and attack with a one-handed weapon, you
       can use your bonus action to attack with a hand crossbow.

    Implementation:
      - "attack": remove disadvantage flag from the owner's ranged attacks.
      - "TurnStarted": if wielding a hand crossbow, grant one temp extra attack
        for the bonus action attack (bonus action consumed).
    """
    name = "Crossbow Expert"
    EVENT_MAP = {
        "attack":       "on_attack",
        "TurnStarted":  "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._bonus_used = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._bonus_used = False

    def on_attack(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or not attack.range:
            return
        # Effect 2: clear melee-range disadvantage
        attack.disadvantage = False

        # Effect 3: grant bonus hand-crossbow attack on first ranged attack
        if self._bonus_used:
            return
        weapon = _wielded_weapon(self.owner, melee=False)
        if not weapon:
            return
        wname = weapon.name.lower()
        if not any(p in wname for p in _HAND_XBOW_NAMES):
            return
        if not self.owner.actions.use_bonus_action():
            return
        self._bonus_used = True
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Crossbow Expert — "
              f"bonus hand-crossbow attack!")


# =============================================================================
# Shield Master
# =============================================================================

class ShieldMaster(Feature):
    """
    If you take the Attack action on your turn, you can use a bonus action to
    try to shove a creature within 5ft prone.

    Implementation: on TurnStarted, if the owner has a shield equipped and a
    bonus action available, grant one temporary extra attack tagged as a shove
    attempt. On a successful hit the target is knocked prone.
    (Full contested Athletics check not implemented; uses a simplified to-hit
    roll and applies "prone" on success.)
    """
    name = "Shield Master"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    _SHOVE_BONUS_ACTION_TAG = "shield_master_shove"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.shield_master = True
        print(f"  {owner.name}: Shield Master — bonus action shove when wielding shield")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        has_shield = any(
            getattr(i, "armor_type", "") == "shield"
            for i in getattr(self.owner, "equipped_items", [])
        )
        if not has_shield:
            return
        if not self.owner.actions.use_bonus_action():
            return
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Shield Master — bonus-action shove ready!")
