"""
data/features/barbarian_features.py

Barbarian class features — combat-relevant through level 20.

Base barbarian
  lv1   Rage                 (bonus action; B/P/S resistance, +2/3/4 melee damage; AI auto-activates)
  lv1   Unarmored Defense    (AC = 10 + DEX + CON when no armor — flag for setup_ac)
  lv2   Reckless Attack      (advantage on own attacks, advantage against you)
  lv2   Danger Sense         (advantage on DEX saves vs visible effects)
  lv5   Extra Attack         (2 attacks per action)
  lv5   Fast Movement        (+10ft speed)
  lv7   Feral Instinct       (advantage on initiative)
  lv9   Brutal Critical      (1/2/3 extra weapon die on crits)
  lv11  Relentless Rage      (CON save at 0 HP while raging → drop to 1 HP)
  lv15  Persistent Rage      (rage doesn't end from not attacking/taking damage)
  lv20  Primal Champion      (+4 STR, +4 CON)

Berserker subclass
  lv3   Frenzy               (while raging: bonus action extra melee attack)
  lv6   Mindless Rage        (can't be charmed/frightened while raging)
  lv14  Retaliation          (reaction: melee attack when hit by adjacent enemy)

Bear Totem subclass
  lv3   Bear Totem Spirit    (while raging: resistance to all damage except psychic)
  lv14  Totemic Attunement   (enemies within 5ft have disadvantage vs your allies)
"""
import random
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Level 1 — Rage
# ---------------------------------------------------------------------------

class Rage(Feature):
    """
    Bonus action: enter a rage (lasts ≤1 min).
    While raging:
      - Resistance to bludgeoning, piercing, slashing damage.
      - +2/+3/+4 bonus to melee weapon damage rolls.
    AI activates at the start of each turn if not already raging.
    Uses per long rest scale by level.
    """
    name = "Rage"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._raging         = False
        self._uses_remaining = 0
        self._damage_bonus   = 2

    def attach(self, owner, bus):
        super().attach(owner, bus)
        barb_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Barbarian"), 1
        )
        if barb_lvl >= 20:
            self._uses_remaining = 999
        elif barb_lvl >= 17:
            self._uses_remaining = 6
        elif barb_lvl >= 12:
            self._uses_remaining = 5
        elif barb_lvl >= 6:
            self._uses_remaining = 4
        elif barb_lvl >= 3:
            self._uses_remaining = 3
        else:
            self._uses_remaining = 2

        self._damage_bonus = 4 if barb_lvl >= 16 else 3 if barb_lvl >= 9 else 2
        print(f"  {owner.name}: Rage ready "
              f"({self._uses_remaining} uses, +{self._damage_bonus} melee)")

    def _start_rage(self):
        if self._raging or self._uses_remaining <= 0:
            return False
        if not self.owner.actions.use_bonus_action():
            return False
        self._raging = True
        if self._uses_remaining < 999:
            self._uses_remaining -= 1
        self.owner.resistances.update({"bludgeoning", "piercing", "slashing"})
        print(f"  {self.owner.name} enters RAGE! "
              f"(+{self._damage_bonus} melee, B/P/S resistance, "
              f"{self._uses_remaining} uses left)")
        return True

    def end_rage(self):
        if not self._raging:
            return
        self._raging = False
        self.owner.resistances.discard("bludgeoning")
        self.owner.resistances.discard("piercing")
        self.owner.resistances.discard("slashing")
        print(f"  {self.owner.name}'s Rage ends")

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        # AI: always enter rage if available and not raging
        if not self._raging and self._uses_remaining > 0:
            self._start_rage()

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        if not self._raging:
            return
        attack = data.get("attack")
        if attack and not getattr(attack, "range", False):
            attack.damage_mod += self._damage_bonus


# ---------------------------------------------------------------------------
# Level 1 — Unarmored Defense (Barbarian)
# ---------------------------------------------------------------------------

class UnarmoredDefenseBarbarian(Feature):
    """
    AC = 10 + DEX mod + CON mod when not wearing body armor.
    Sets a flag; PlayerCharacter.setup_ac() applies it after equipping items.
    """
    name = "Unarmored Defense (Barbarian)"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.barbarian_unarmored_defense = True
        print(f"  {owner.name}: Unarmored Defense — AC = 10+DEX+CON if unarmored")


# ---------------------------------------------------------------------------
# Level 2 — Reckless Attack
# ---------------------------------------------------------------------------

class RecklessAttack(Feature):
    """
    On your turn when you make an attack: gain advantage on all your attack
    rolls using STR this turn. Until the start of your next turn, attack
    rolls against you have advantage.
    AI always activates (damage output > defence for the barbarian).
    """
    name = "Reckless Attack"
    EVENT_MAP = {
        "attack":      "on_attack",
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._exposed = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._exposed = False
            self.owner._reckless_exposed = False

    def on_attack(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attack:
            return
        # Own outgoing attacks: advantage, mark as exposed
        if attacker is self.owner:
            attack.advantage = True
            if not self._exposed:
                self._exposed = True
                self.owner._reckless_exposed = True
        # Incoming attacks: advantage for the attacker if we're exposed
        if target is self.owner and getattr(self.owner, "_reckless_exposed", False):
            attack.advantage = True


# ---------------------------------------------------------------------------
# Level 2 — Danger Sense
# ---------------------------------------------------------------------------

class DangerSense(Feature):
    """
    Advantage on DEX saving throws against effects you can see.
    Hooks the "saving_throw" event and sets advantage when ability == "Dex".
    """
    name = "Danger Sense"
    EVENT_MAP = {"saving_throw": "on_saving_throw"}

    def on_saving_throw(self, ctx):
        if ctx.get("target") is not self.owner:
            return
        if ctx.get("ability") == "Dex":
            ctx["advantage"] = True


# ---------------------------------------------------------------------------
# Level 5 — Extra Attack
# ---------------------------------------------------------------------------

class ExtraAttack(Feature):
    """2 attacks per action at lv5."""
    name = "Extra Attack"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 1
        owner.actions.remaining_extra_attacks = max(
            owner.actions.remaining_extra_attacks, 1
        )
        print(f"  {owner.name}: Extra Attack (2 attacks)")


# ---------------------------------------------------------------------------
# Level 5 — Fast Movement
# ---------------------------------------------------------------------------

class FastMovement(Feature):
    """+10ft walking speed while not wearing heavy armor."""
    name = "Fast Movement"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.speed += 10
        print(f"  {owner.name}: Fast Movement — speed {owner.speed}ft")


# ---------------------------------------------------------------------------
# Level 7 — Feral Instinct
# ---------------------------------------------------------------------------

class FeralInstinct(Feature):
    """Advantage on initiative rolls."""
    name = "Feral Instinct"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.initiative_advantage = True
        print(f"  {owner.name}: Feral Instinct — advantage on initiative")


# ---------------------------------------------------------------------------
# Level 9 — Brutal Critical (scales to lv13 / lv17)
# ---------------------------------------------------------------------------

class BrutalCritical(Feature):
    """
    Roll one extra weapon damage die on a critical hit.
    lv9: 1 die, lv13: 2 dice, lv17: 3 dice.
    """
    name = "Brutal Critical"
    EVENT_MAP = {"hit": "on_hit"}

    def __init__(self):
        super().__init__()
        self._extra_dice_count = 1

    def attach(self, owner, bus):
        super().attach(owner, bus)
        barb_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Barbarian"), 1
        )
        self._extra_dice_count = 3 if barb_lvl >= 17 else 2 if barb_lvl >= 13 else 1
        print(f"  {owner.name}: Brutal Critical (+{self._extra_dice_count} die on crits)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or not attack.critical:
            return
        num, sides = attack.base_dice
        for _ in range(self._extra_dice_count):
            attack.extra_dice.append((num, sides))
        print(f"  {self.owner.name}: Brutal Critical! +{self._extra_dice_count}d{sides}")


# ---------------------------------------------------------------------------
# Level 11 — Relentless Rage
# ---------------------------------------------------------------------------

class RelentlessRage(Feature):
    """
    When reduced to 0 HP while raging, make a CON save (DC 10, +5 each use).
    On success, drop to 1 HP instead of falling unconscious.
    """
    name = "Relentless Rage"
    EVENT_MAP = {"creature_downed": "on_downed"}

    def __init__(self):
        super().__init__()
        self._dc = 10

    def on_downed(self, data):
        if data.get("creature") is not self.owner:
            return
        rage = next((f for f in self.owner.features if isinstance(f, Rage)), None)
        if not rage or not rage._raging:
            return

        from core.saving_throw import SavingThrow, DamageOnSave
        print(f"  {self.owner.name}: Relentless Rage! CON save DC {self._dc}")
        result = SavingThrow.roll(
            caster=self.owner, target=self.owner,
            ability="Con", dc=self._dc, on_save=DamageOnSave.NONE,
        )
        self._dc += 5
        if result.success:
            self.owner._current_hp = 1
            self.owner.conditions.discard("unconscious")
            self.owner.conditions.discard("dying")
            self.owner.death_save_successes = 0
            self.owner.death_save_failures  = 0
            print(f"  {self.owner.name} clings to life at 1 HP!")


# ---------------------------------------------------------------------------
# Level 15 — Persistent Rage
# ---------------------------------------------------------------------------

class PersistentRage(Feature):
    """Rage no longer ends involuntarily — passive flag."""
    name = "Persistent Rage"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.persistent_rage = True
        print(f"  {owner.name}: Persistent Rage — rage never ends involuntarily")


# ---------------------------------------------------------------------------
# Level 20 — Primal Champion
# ---------------------------------------------------------------------------

class PrimalChampion(Feature):
    """STR +4, CON +4 (increases max HP retroactively)."""
    name = "Primal Champion"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.statblock.scores["Str"] = owner.statblock.scores.get("Str", 10) + 4
        owner.statblock.scores["Con"] = owner.statblock.scores.get("Con", 10) + 4
        owner.statblock._recompute_mods()
        barb_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Barbarian"), 0
        )
        extra_hp = 4 * barb_lvl
        owner._max_hp     += extra_hp
        owner._current_hp  = min(owner._current_hp + extra_hp, owner._max_hp)
        print(f"  {owner.name}: Primal Champion "
              f"(+4 STR, +4 CON, +{extra_hp} HP → {owner._max_hp})")


# ---------------------------------------------------------------------------
# Brutal Critical upgrade stubs
# ---------------------------------------------------------------------------

class BrutalCriticalII(Feature):
    """No-op — BrutalCritical reads level in attach()."""
    name = "Brutal Critical II"


class BrutalCriticalIII(Feature):
    """No-op — BrutalCritical reads level in attach()."""
    name = "Brutal Critical III"


class IndomitableMightBarbarian(Feature):
    """Non-combat — minimum STR check = STR score. Stub."""
    name = "Indomitable Might (Barbarian)"


# ---------------------------------------------------------------------------
# Berserker lv3 — Frenzy
# ---------------------------------------------------------------------------

class Frenzy(Feature):
    """
    While raging: use your bonus action each turn to make one melee
    weapon attack. (Rage ends → gain one level of exhaustion — not tracked.)
    """
    name = "Frenzy"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        rage = next((f for f in self.owner.features if isinstance(f, Rage)), None)
        if not rage or not rage._raging:
            return
        # Bonus action was already spent to start rage on round 1;
        # subsequent turns the bonus action is free for Frenzy.
        if not self.owner.actions.use_bonus_action():
            return
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Frenzy — bonus action extra attack!")


# ---------------------------------------------------------------------------
# Berserker lv6 — Mindless Rage
# ---------------------------------------------------------------------------

class MindlessRage(Feature):
    """Can't be charmed or frightened while raging."""
    name = "Mindless Rage"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        print(f"  {owner.name}: Mindless Rage — charm/fright immunity while raging")


class IntimidatingPresence(Feature):
    """Non-combat action — stub."""
    name = "Intimidating Presence"


# ---------------------------------------------------------------------------
# Berserker lv14 — Retaliation
# ---------------------------------------------------------------------------

class Retaliation(Feature):
    """
    When you take damage from a creature within 5ft, use your reaction
    to make one melee weapon attack against that creature.
    """
    name = "Retaliation"
    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    def on_damage_dealt(self, data):
        target   = data.get("target")
        attacker = data.get("attacker")
        attack   = data.get("attack")
        if target is not self.owner:
            return
        if not attack or not attack.result.get("hit"):
            return
        if not self._owner_can_react():
            return
        if not self.owner.actions.use_reaction():
            return
        # Must be adjacent (≤1 grid square = 5ft)
        from core.battle_map import BattleMap
        if (getattr(self.owner, "pos", None) and getattr(attacker, "pos", None)):
            dx = abs(self.owner.pos[0] - attacker.pos[0])
            dy = abs(self.owner.pos[1] - attacker.pos[1])
            if max(dx, dy) > 1:
                self.owner.actions.reactions += 1  # refund
                return

        weapons = [i for i in self.owner.equipped_items if i.item_type == "weapon"
                   and getattr(i, "attack_type", "melee") == "melee"]
        if not weapons:
            self.owner.actions.reactions += 1
            return
        weapon = weapons[0]
        print(f"  {self.owner.name}: Retaliation — strikes back at {attacker.name}!")
        from core.attack import WeaponAttack
        WeaponAttack(self.owner, attacker, weapon.damage_die, item=weapon).declare_attack()


# ---------------------------------------------------------------------------
# Bear Totem lv3 — Bear Totem Spirit
# ---------------------------------------------------------------------------

_BEAR_RESIST_TYPES = {
    "acid", "bludgeoning", "cold", "fire", "force",
    "lightning", "necrotic", "piercing", "poison",
    "radiant", "slashing", "thunder",
}


class BearTotemSpirit(Feature):
    """
    While raging: resistance to all damage types except psychic.
    Extends and supersedes the base Rage B/P/S resistances.
    """
    name = "Bear Totem Spirit"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        if ctx.get("creature") is not self.owner:
            return
        rage = next((f for f in self.owner.features if isinstance(f, Rage)), None)
        if rage and rage._raging:
            before = len(self.owner.resistances)
            self.owner.resistances.update(_BEAR_RESIST_TYPES)
            if len(self.owner.resistances) > before:
                print(f"  {self.owner.name}: Bear Totem — resistance to all damage but psychic!")


class AspectOfTheBear(Feature):
    """Non-combat — stub."""
    name = "Aspect of the Bear"


class SpiritWalker(Feature):
    """Non-combat — stub."""
    name = "Spirit Walker"


# ---------------------------------------------------------------------------
# Bear Totem lv14 — Totemic Attunement (Bear)
# ---------------------------------------------------------------------------

class TotemicAttunementBear(Feature):
    """
    While raging, creatures within 5ft have disadvantage on attack rolls
    against targets other than you.
    Hooks the "attack" event; if attacker is within 5ft of the owner and
    not targeting the owner, impose disadvantage.
    """
    name = "Totemic Attunement (Bear)"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attack or target is self.owner:
            return

        rage = next((f for f in self.owner.features if isinstance(f, Rage)), None)
        if not rage or not rage._raging:
            return

        if getattr(self.owner, "pos", None) and getattr(attacker, "pos", None):
            dx = abs(self.owner.pos[0] - attacker.pos[0])
            dy = abs(self.owner.pos[1] - attacker.pos[1])
            if max(dx, dy) <= 1:
                attack.disadvantage = True
                print(f"  {self.owner.name}: Bear Totem — "
                      f"{attacker.name} has disadvantage on {target.name}!")


class PrimalPath(Feature):
    """Subclass selection at level 3. Non-combat stub."""
    name = "Primal Path"
