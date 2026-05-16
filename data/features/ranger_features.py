"""
data/features/ranger_features.py

Ranger class features — all combat-relevant features through level 20.

Base ranger
  lv1   FavoredFoe
  lv5   ExtraAttack
  lv6   Roving              (+5ft speed, climb/swim speed)
  lv8   LandsStride         (difficult terrain costs normal movement)
  lv10  NaturesVeil         (bonus action: invisible for one turn, PB uses)
  lv18  FeralSenses         (no penalty attacking invisible creatures)
  lv20  FoeSlayer           (once per turn: +WIS mod to attack OR damage)

Gloom Stalker subclass
  lv3   DreadAmbusher       (round 1: +10ft speed, extra attack, +1d8)
  lv7   IronMind            (WIS save proficiency)
  lv11  StalkersFlurry      (miss once per turn → free extra attack)
  lv15  ShadowyDodge        (reaction: impose disadvantage on incoming attack)
"""
import random
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Level 1 — Favored Foe
# ---------------------------------------------------------------------------

class FavoredFoe(Feature):
    """
    Mark the first creature you hit each combat. Your first hit each turn
    against that creature deals bonus damage (1d4/1d6/1d8 scaling with
    ranger level). Requires concentration, PB uses per long rest.
    """
    name = "Favored Foe"
    EVENT_MAP = {
        "hit":         "on_hit",
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._marked:          object | None = None
        self._bonus_used_turn: bool          = False
        self._uses_remaining:  int           = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._uses_remaining = owner.proficiency
        print(f"  {owner.name}: Favored Foe ready ({self._uses_remaining} uses)")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._bonus_used_turn = False

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        target = data.get("target")
        attack = data.get("attack")

        if target is not self._marked and self._uses_remaining > 0:
            if self.owner.concentration and self.owner.concentration != "Favored Foe":
                return
            self._marked          = target
            self._uses_remaining -= 1
            self._bonus_used_turn = False
            self.owner.start_concentration("Favored Foe", feature=self)
            print(f"  {self.owner.name} marks {target.name} with Favored Foe "
                  f"({self._uses_remaining} uses remaining)")

        if target is self._marked and not self._bonus_used_turn and attack:
            ranger_level = next(
                (lvl for cls, lvl in self.owner.classes if cls == "Ranger"), 1
            )
            die = 4 if ranger_level <= 5 else 6 if ranger_level <= 13 else 8
            attack.extra_dice.append((1, die))
            self._bonus_used_turn = True
            print(f"  Favored Foe: adding 1d{die} to {target.name}")

    def on_concentration_broken(self):
        if self._marked:
            print(f"  {self.owner.name} loses Favored Foe mark on {self._marked.name}")
        self._marked          = None
        self._bonus_used_turn = False


# ---------------------------------------------------------------------------
# Level 5 — Extra Attack
# ---------------------------------------------------------------------------

class ExtraAttack(Feature):
    """One additional attack when taking the Attack action."""
    name = "Extra Attack"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 1
        owner.actions.remaining_extra_attacks = 1
        print(f"  {owner.name} gains Extra Attack")


# ---------------------------------------------------------------------------
# Level 6 — Roving  (Deft Explorer improvement)
# ---------------------------------------------------------------------------

class Roving(Feature):
    """
    +5ft walking speed. Also gain climb and swim speed equal to walking speed.
    Climb/swim are flavour only in our 2D map — only the speed bonus applies.
    """
    name = "Roving"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.speed += 5
        print(f"  {owner.name}: Roving — speed increased to {owner.speed}ft")


# ---------------------------------------------------------------------------
# Level 8 — Land's Stride
# ---------------------------------------------------------------------------

class LandsStride(Feature):
    """
    Difficult terrain costs no extra movement.
    Implemented by setting a flag that BattleMap._movement_cost checks.
    """
    name = "Land's Stride"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.ignore_difficult_terrain = True
        print(f"  {owner.name}: Land's Stride — difficult terrain ignored")

    def detach(self):
        self.owner.ignore_difficult_terrain = False
        super().detach()


# ---------------------------------------------------------------------------
# Level 10 — Nature's Veil
# ---------------------------------------------------------------------------

class NaturesVeil(Feature):
    """
    Bonus action: turn invisible until the start of your next turn.
    Limited to proficiency bonus uses per long rest.

    While invisible:
      - Your attacks have advantage (wired in Creature._on_attack_event)
      - Attacks against you have disadvantage (same)
    The invisible condition is cleared at TurnStarted.
    """
    name = "Nature's Veil"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._uses_remaining: int = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._uses_remaining = owner.proficiency
        print(f"  {owner.name}: Nature's Veil ready ({self._uses_remaining} uses)")

    def activate(self) -> bool:
        """
        Called when the player/AI chooses to use the bonus action.
        Returns True if successful.
        """
        if self._uses_remaining <= 0:
            print(f"  {self.owner.name}: Nature's Veil — no uses remaining")
            return False
        if not self.owner.actions.use_bonus_action():
            print(f"  {self.owner.name}: Nature's Veil — no bonus action available")
            return False
        self._uses_remaining -= 1
        self.owner.add_condition("invisible")
        print(f"  {self.owner.name} vanishes! (Nature's Veil, "
              f"{self._uses_remaining} uses left)")
        return True

    def on_turn_started(self, ctx):
        """Clear invisibility at the start of the owner's next turn."""
        if ctx.get("creature") is self.owner and self.owner.has_condition("invisible"):
            self.owner.remove_condition("invisible")
            print(f"  {self.owner.name} reappears (Nature's Veil fades)")


# ---------------------------------------------------------------------------
# Level 18 — Feral Senses
# ---------------------------------------------------------------------------

class FeralSenses(Feature):
    """
    You don't have disadvantage on attack rolls against invisible creatures,
    and you are aware of invisible creatures within 30ft.

    Implemented by hooking Phase 1 "attack" and cancelling the disadvantage
    that Creature._on_attack_event sets when the target is invisible.
    """
    name = "Feral Senses"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        target = data.get("target")
        if attack and target and target.has_condition("invisible"):
            attack.disadvantage = False
            print(f"  {self.owner.name}: Feral Senses — no penalty vs invisible")


# ---------------------------------------------------------------------------
# Level 20 — Foe Slayer
# ---------------------------------------------------------------------------

class FoeSlayer(Feature):
    """
    Once per turn, add your WIS modifier to either one attack roll or
    one damage roll against a creature.

    AI heuristic: add to the attack roll if to-hit would benefit most
    (target has high AC relative to our bonus), otherwise add to damage.
    For simplicity we always add to damage via extra_dice — it's reliable
    and the WIS mod at level 20 is typically +4 or +5.
    """
    name = "Foe Slayer"
    EVENT_MAP = {
        "hit":         "on_hit",
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._used_this_turn = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used_this_turn = False

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        if self._used_this_turn:
            return
        attack = data.get("attack")
        if not attack:
            return
        wis_mod = self.owner.statblock.mods.get("Wis", 0)
        if wis_mod <= 0:
            return
        # Add WIS mod as flat damage bonus this hit
        attack.damage_mod  += wis_mod
        self._used_this_turn = True
        print(f"  {self.owner.name}: Foe Slayer +{wis_mod} damage")


# ---------------------------------------------------------------------------
# Gloom Stalker lv3 — Dread Ambusher
# ---------------------------------------------------------------------------

class DreadAmbusher(Feature):
    """
    Round 1 only:
      - +10ft movement
      - One extra attack granted into the pool
      - That extra attack deals +1d8 on hit (added to extra_dice in Phase 2)
    """
    name = "Dread Ambusher"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":      "on_attack",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._last_granted_round = -1
        self._bonus_active       = False

    def on_turn_started(self, ctx):
        creature  = ctx.get("creature")
        round_num = ctx.get("round", 1)
        if creature is not self.owner:
            return
        if round_num != 1:
            return
        if self._last_granted_round == round_num:
            return
        self._last_granted_round = round_num
        self._bonus_active       = True
        self.owner.speed += 10
        print(f"  {self.owner.name}: Dread Ambusher — +10ft speed this turn")
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Dread Ambusher — extra attack this turn")

    def on_attack(self, data):
        if not self._bonus_active:
            return
        if data.get("attacker") is not self.owner:
            return
        if self.owner.actions.remaining_extra_attacks == 0:
            attack = data.get("attack")
            if attack:
                attack.tags.add("dread_ambusher_bonus")
            self._bonus_active = False

    def on_hit(self, data):
        attack = data.get("attack")
        if attack and "dread_ambusher_bonus" in attack.tags:
            attack.extra_dice.append((1, 8))
            print(f"  {self.owner.name}: Dread Ambusher +1d8 damage!")


# ---------------------------------------------------------------------------
# Gloom Stalker lv7 — Iron Mind
# ---------------------------------------------------------------------------

class IronMind(Feature):
    """WIS saving throw proficiency (or INT/CHA if already proficient)."""
    name = "Iron Mind"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        if not owner.statblock.save_profs.get("Wis", 0):
            owner.statblock.save_profs["Wis"] = 1
            print(f"  {owner.name}: Iron Mind — WIS save proficiency")
        elif not owner.statblock.save_profs.get("Int", 0):
            owner.statblock.save_profs["Int"] = 1
            print(f"  {owner.name}: Iron Mind — INT save proficiency")
        else:
            owner.statblock.save_profs["Cha"] = 1
            print(f"  {owner.name}: Iron Mind — CHA save proficiency")


# ---------------------------------------------------------------------------
# Gloom Stalker lv11 — Stalker's Flurry
# ---------------------------------------------------------------------------

class StalkersFlurry(Feature):
    """
    Once per turn: if you miss with a weapon attack, you can immediately
    make one additional weapon attack as part of the same action.

    Hooks Phase 5 "attack_resolved" for misses. Grants a single temp
    extra attack that the existing _do_attack_action loop will fire.
    The flag resets at TurnStarted.
    """
    name = "Stalker's Flurry"
    EVENT_MAP = {
        "attack_resolved": "on_attack_resolved",
        "TurnStarted":     "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._triggered_this_turn = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._triggered_this_turn = False

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        if self._triggered_this_turn:
            return
        attack = data.get("attack")
        if not attack or attack.result.get("hit", True):
            return   # only fires on a miss
        self._triggered_this_turn = True
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Stalker's Flurry — missed, gaining free attack!")


# ---------------------------------------------------------------------------
# Gloom Stalker lv15 — Shadowy Dodge
# ---------------------------------------------------------------------------

class ShadowyDodge(Feature):
    """
    Reaction: when a creature makes an attack roll against you, impose
    disadvantage on that roll before it resolves.

    Hooks Phase 1 "attack" so disadvantage applies before roll_to_hit().
    Spends the reaction; resets each turn via start_turn() → actions.reset().
    """
    name = "Shadowy Dodge"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        target = data.get("target")
        attack = data.get("attack")
        if target is not self.owner:
            return
        if not self.owner.actions.use_reaction():
            return
        attack.disadvantage = True
        print(f"  {self.owner.name}: Shadowy Dodge — imposing disadvantage!")


# ---------------------------------------------------------------------------
# Non-combat stubs — required so feature names resolve in ranger.json
# ---------------------------------------------------------------------------

class DeftExplorer(Feature):
    """Lv1/lv6/lv10 Deft Explorer improvements (languages, skills, terrain). Non-combat stub."""
    name = "Deft Explorer"

class PretermaturalAwareness(Feature):
    """Lv3: detect invisible/hidden creatures in 30ft. Non-combat stub."""
    name = "Preternatural Awareness"

class Tireless(Feature):
    """Lv9: reduce exhaustion and gain temp HP on short rest. Non-combat stub."""
    name = "Tireless"

class Vanish(Feature):
    """Lv14: Hide as a bonus action; can't be tracked by non-magical means. Non-combat stub."""
    name = "Vanish"

class UmbralSight(Feature):
    """Gloom Stalker lv3: darkvision 60ft (or +30ft); invisible to darkvision. Non-combat stub."""
    name = "Umbral Sight"