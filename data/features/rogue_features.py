"""
data/features/rogue_features.py

Rogue class features — combat-relevant through level 20.

Base rogue
  lv1   Sneak Attack        (1d6 per 2 rogue levels when attacking with advantage
                             or with an ally adjacent to the target)
  lv2   Cunning Action      (bonus action: Dash each turn for kiting)
  lv5   Uncanny Dodge       (reaction: halve damage from one attacker per turn)
  lv7   Evasion             (DEX save: success → no damage; fail → half)
  lv15  Slippery Mind       (WIS save proficiency)
  lv18  Elusive             (no advantage on attack rolls against you)
  lv20  Stroke of Luck      (once per rest: miss becomes hit)

Assassin subclass
  lv3   Assassinate         (advantage on attacks in round 1;
                             auto-crit vs creature that hasn't acted)
  lv17  Death Strike        (CON save vs double damage on first crit in round 1)

Thief subclass
  lv9   Supreme Sneak       (advantage on stealth while moving ≤half speed — passive)
  lv17  Thief's Reflexes    (two turns in round 1)
"""
import random
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Level 1 — Sneak Attack
# ---------------------------------------------------------------------------

class SneakAttack(Feature):
    """
    Once per turn: deal extra damage when you attack with advantage OR when an
    ally is adjacent to the target and you don't have disadvantage.
    Damage: 1d6 per 2 rogue levels (1d6 at lv1-2, 2d6 at lv3-4, etc.).
    Only works with finesse or ranged weapons (attack.range or item has finesse).
    """
    name = "Sneak Attack"
    EVENT_MAP = {
        "hit":         "on_hit",
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._sneak_dice      = 1
        self._used_this_turn  = False

    def attach(self, owner, bus):
        super().attach(owner, bus)
        rogue_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Rogue"), 1
        )
        self._sneak_dice = (rogue_lvl + 1) // 2
        print(f"  {owner.name}: Sneak Attack ({self._sneak_dice}d6)")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used_this_turn = False

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        if self._used_this_turn:
            return
        attack = data.get("attack")
        target = data.get("target")
        if not attack:
            return

        # Only finesse or ranged weapons qualify
        item = getattr(attack, "item", None)
        is_ranged = getattr(attack, "range", False)
        is_finesse = item and "finesse" in getattr(item, "properties", [])
        if not (is_ranged or is_finesse):
            return

        qualifies = False
        if attack.advantage:
            qualifies = True
        elif not attack.disadvantage:
            # Check for an ally adjacent to the target
            own_pos = getattr(self.owner, "pos", None)
            tgt_pos = getattr(target, "pos", None)
            if own_pos and tgt_pos:
                # Any ally within 5ft (1 sq) of the target that isn't the rogue
                for feat_owner in self._find_adjacent_allies(target):
                    qualifies = True
                    break

        if not qualifies:
            return

        attack.extra_dice.extend([(1, 6)] * self._sneak_dice)
        self._used_this_turn = True
        print(f"  {self.owner.name}: Sneak Attack! +{self._sneak_dice}d6")

    def _find_adjacent_allies(self, target):
        """Yield allies of the rogue that are within 1 square of target."""
        tgt_pos = getattr(target, "pos", None)
        if not tgt_pos:
            return
        # Walk all subscribers on the bus to find ally creatures
        for cb_list in self.bus.subscribers.values():
            for cb in cb_list:
                owner = getattr(cb, "__self__", None)
                if owner is None or owner is self.owner or owner is target:
                    continue
                if getattr(owner, "team", None) != self.owner.team:
                    continue
                if not getattr(owner, "is_alive", lambda: False)():
                    continue
                ally_pos = getattr(owner, "pos", None)
                if ally_pos:
                    dist = max(abs(ally_pos[0] - tgt_pos[0]),
                               abs(ally_pos[1] - tgt_pos[1]))
                    if dist <= 1:
                        yield owner


# ---------------------------------------------------------------------------
# Level 2 — Cunning Action
# ---------------------------------------------------------------------------

class CunningAction(Feature):
    """
    Bonus action: Dash (double movement this turn), Disengage, or Hide.
    AI: Dash each turn to improve positioning and kiting.
    """
    name = "Cunning Action"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if creature.actions.use_bonus_action():
            creature.speed += creature.speed   # Dash: double movement this turn
            print(f"  {creature.name}: Cunning Action (Dash) — speed {creature.speed}ft this turn")


# ---------------------------------------------------------------------------
# Level 5 — Uncanny Dodge
# ---------------------------------------------------------------------------

class UncannyDodge(Feature):
    """
    When an attacker you can see hits you, use your reaction to halve the
    damage. Implemented by healing back half after damage is dealt.
    """
    name = "Uncanny Dodge"
    EVENT_MAP = {"damage_dealt": "on_damage_dealt"}

    def __init__(self):
        super().__init__()
        self._used_this_turn = False

    def attach(self, owner, bus):
        super().attach(owner, bus)
        # Reset each turn via TurnStarted
        bus.subscribe("TurnStarted", self._on_turn_started)
        self._subscriptions.append(("TurnStarted", self._on_turn_started))

    def _on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used_this_turn = False

    def on_damage_dealt(self, data):
        target   = data.get("target")
        attack   = data.get("attack")
        if target is not self.owner:
            return
        if not attack or not attack.result.get("hit"):
            return
        if self._used_this_turn:
            return
        if not self._owner_can_react():
            return
        if not self.owner.actions.use_reaction():
            return

        self._used_this_turn = True
        # Heal back half of damage dealt (simulates halving)
        dmg = attack.result.get("damage", 0)
        refund = dmg // 2
        if refund > 0:
            self.owner.heal(refund)
            print(f"  {self.owner.name}: Uncanny Dodge! Halves damage "
                  f"(+{refund} HP → {self.owner.hp}/{self.owner.max_hp})")


# ---------------------------------------------------------------------------
# Level 7 — Evasion
# ---------------------------------------------------------------------------

class Evasion(Feature):
    """
    When you make a DEX saving throw:
      - Success: no damage (instead of half).
      - Failure: half damage (instead of full).
    Hooks "saving_throw" to flag evasion; the resolution logic for evasion
    is applied in the event context so SavingThrow respects it via bonus.

    Implemented as: on DEX save success, reduce damage to 0 via a very
    large bonus (effectively). Instead we override by hooking
    "saving_throw_resolved" and healing back excess damage.
    """
    name = "Evasion"
    EVENT_MAP = {"saving_throw_resolved": "on_saving_throw_resolved"}

    def on_saving_throw_resolved(self, data):
        result = data.get("result")
        if not result:
            return
        if result.target is not self.owner:
            return
        if result.ability != "Dex":
            return

        if result.success and result.damage_dealt > 0:
            # Success → should take 0, but took half. Heal it all back.
            self.owner.heal(result.damage_dealt)
            print(f"  {self.owner.name}: Evasion — no damage on successful DEX save!")
        elif not result.success and result.damage_dealt > 0:
            # Failure → should take half, and we already took full.
            refund = result.damage_dealt // 2
            if refund > 0:
                self.owner.heal(refund)
                print(f"  {self.owner.name}: Evasion — half damage on failed DEX save "
                      f"(+{refund} HP back)")


# ---------------------------------------------------------------------------
# Level 15 — Slippery Mind
# ---------------------------------------------------------------------------

class SlipperyMind(Feature):
    """Proficiency in Wisdom saving throws."""
    name = "Slippery Mind"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.statblock.save_profs["Wis"] = 1
        print(f"  {owner.name}: Slippery Mind — WIS save proficiency")


# ---------------------------------------------------------------------------
# Level 18 — Elusive
# ---------------------------------------------------------------------------

class Elusive(Feature):
    """
    No attack roll has advantage against you while you aren't incapacitated.
    """
    name = "Elusive"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        target = data.get("target")
        attack = data.get("attack")
        if target is not self.owner or not attack:
            return
        if self.owner.has_condition("incapacitated"):
            return
        if attack.advantage:
            attack.advantage = False
            print(f"  {self.owner.name}: Elusive — advantage cancelled!")


# ---------------------------------------------------------------------------
# Level 20 — Stroke of Luck
# ---------------------------------------------------------------------------

class StrokeOfLuck(Feature):
    """
    Once per rest: when you miss an attack, turn the miss into a hit.
    """
    name = "Stroke of Luck"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def __init__(self):
        super().__init__()
        self._available = True

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        if not self._available:
            return
        attack = data.get("attack")
        if not attack or attack.result.get("hit", True):
            return
        self._available = False
        attack.result["hit"] = True
        print(f"  {self.owner.name}: Stroke of Luck — miss becomes a hit!")


# ---------------------------------------------------------------------------
# Non-combat stubs
# ---------------------------------------------------------------------------

class Expertise(Feature):
    name = "Expertise"

class ThievesCant(Feature):
    name = "Thieves Cant"

class ReliableTalent(Feature):
    name = "Reliable Talent"

class Blindsense(Feature):
    name = "Blindsense"


# ---------------------------------------------------------------------------
# Assassin lv3 — Assassinate
# ---------------------------------------------------------------------------

class Assassinate(Feature):
    """
    Advantage on attack rolls against creatures that haven't taken a turn yet.
    In round 1, you automatically crit creatures that are surprised.
    AI: grants advantage + auto-crit on all attacks in round 1.
    """
    name = "Assassinate"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        if attacker is not self.owner or not attack:
            return

        round_num = getattr(self.owner, "_current_round", 1)
        # Use event context round if available (set in TurnStarted)
        if round_num == 1:
            attack.advantage = True
            attack.crit_threshold = 2   # effectively auto-crit (d20 ≥ 2)
            print(f"  {self.owner.name}: Assassinate! Advantage + auto-crit in round 1")

    def attach(self, owner, bus):
        super().attach(owner, bus)
        bus.subscribe("TurnStarted", self._track_round)
        self._subscriptions.append(("TurnStarted", self._track_round))
        print(f"  {owner.name}: Assassinate ready")

    def _track_round(self, ctx):
        if ctx.get("creature") is self.owner:
            self.owner._current_round = ctx.get("round", 1)


# ---------------------------------------------------------------------------
# Assassin lv17 — Death Strike
# ---------------------------------------------------------------------------

class DeathStrike(Feature):
    """
    When you Assassinate (round 1 crit), the target must make a CON save
    (DC = 8 + prof + DEX mod). On failure, double the damage of the attack.
    """
    name = "Death Strike"
    EVENT_MAP = {"hit": "on_hit"}

    def __init__(self):
        super().__init__()
        self._triggered_this_combat = False

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        if self._triggered_this_combat:
            return
        attack = data.get("attack")
        target = data.get("target")
        if not attack or not attack.critical:
            return
        round_num = getattr(self.owner, "_current_round", 99)
        if round_num != 1:
            return

        dc = 8 + self.owner.proficiency + self.owner.statblock.mods.get("Dex", 0)
        from core.saving_throw import SavingThrow, DamageOnSave
        result = SavingThrow.roll(
            caster=self.owner, target=target,
            ability="Con", dc=dc, on_save=DamageOnSave.NONE,
        )
        if not result.success:
            # Double the attack's base_dice count to simulate double damage
            num, sides = attack.base_dice
            attack.base_dice = (num * 2, sides)
            self._triggered_this_combat = True
            print(f"  {self.owner.name}: Death Strike! {target.name} failed CON save "
                  f"(DC {dc}) — damage doubled!")
        else:
            self._triggered_this_combat = True


class InfiltrationExpertise(Feature):
    name = "Infiltration Expertise"

class Impostor(Feature):
    name = "Impostor"


# ---------------------------------------------------------------------------
# Thief lv9 — Supreme Sneak
# ---------------------------------------------------------------------------

class SupremeSneak(Feature):
    """Advantage on Stealth checks when moving at half speed — passive."""
    name = "Supreme Sneak"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        print(f"  {owner.name}: Supreme Sneak — stealth advantage at half speed")


class FastHands(Feature):
    name = "Fast Hands"

class UseMagicDevice(Feature):
    name = "Use Magic Device"


# ---------------------------------------------------------------------------
# Thief lv17 — Thief's Reflexes
# ---------------------------------------------------------------------------

class ThiefsReflexes(Feature):
    """
    Take two turns in the first round of combat (at your initiative and
    initiative -10). Simulated by granting a temporary extra action in round 1.
    """
    name = "Thief's Reflexes"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._used_round1 = False

    def on_turn_started(self, ctx):
        creature  = ctx.get("creature")
        round_num = ctx.get("round", 1)
        if creature is not self.owner or round_num != 1:
            return
        if self._used_round1:
            return
        self._used_round1 = True
        creature.actions.actions += 1
        print(f"  {creature.name}: Thief's Reflexes — extra action in round 1!")


class RoguishArchetype(Feature):
    """Subclass selection at level 3. Non-combat stub."""
    name = "Roguish Archetype"
