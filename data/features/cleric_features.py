"""
data/features/cleric_features.py

Cleric class features.

Base cleric
  lv1   DivineDomain               Subclass selection stub.
  lv2   ChannelDivinity            Domain-specific ability stub (2 uses/rest at lv6, 3 at lv18).
  lv5   DestroyUndead              Channel Divinity upgrade vs undead. Non-combat stub.
  lv10  DivineIntervention         Ask deity for aid (10% + lvl chance). Non-combat stub.
  lv20  DivineInterventionImprovement  Auto-succeeds. Non-combat stub.

Life Domain
  lv1   BonusProficiency   Heavy armor proficiency.
  lv1   DiscipleOfLife     Healing spells restore extra HP. Non-combat stub.
  lv2   PreserveLife       Channel Divinity: distribute healing pool. Non-combat stub.
  lv6   BlessedHealer      Healing others heals caster. Non-combat stub.
  lv8   DivinestStrike     (see DivineStrike below)
  lv17  SupremeHealing     Maximize healing dice. Non-combat stub.

War Domain
  lv1   BonusProficiency   Heavy armor + martial weapon proficiency. (shared stub)
  lv1   WarPriest          WIS-mod uses/long rest: bonus-action weapon attack after Attack action.
  lv2   GuidedStrike       Channel Divinity: +10 to one attack roll. Non-combat stub.
  lv6   WarGodsBlessing    Channel Divinity reaction: +10 to ally attack roll. Non-combat stub.
  lv8   DivineStrike       Once per turn: +1d8 weapon damage (2d8 at lv14).
  lv17  AvatarOfBattle     Resistance to non-magical B/P/S damage. Non-combat stub.

Light Domain
  lv1   WardingFlare       Reaction: disadvantage on one attack. Non-combat stub.
  lv2   RadianceOfTheDawn  Channel Divinity AoE radiant. Non-combat stub.
  lv6   ImprovedFlare      Warding Flare protects allies. Non-combat stub.
  lv8   PotentSpellcasting +WIS mod to cleric cantrip damage. Non-combat stub.
  lv17  CoronaOfLight      Sunlight aura. Non-combat stub.
"""
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Base cleric stubs
# ---------------------------------------------------------------------------

class DivineDomain(Feature):
    """Subclass selection at level 1."""
    name = "Divine Domain"


class ChannelDivinity(Feature):
    """Channel Divinity: domain-specific uses. Non-combat stub."""
    name = "Channel Divinity"


class ChannelDivinityImprovement(Feature):
    """Upgrade to 2 then 3 Channel Divinity uses per short rest. Non-combat stub."""
    name = "Channel Divinity Improvement"


class DivineDomainFeature(Feature):
    """Subclass feature at levels 6, 8, and 17."""
    name = "Divine Domain Feature"


class DestroyUndead(Feature):
    """Channel Divinity improvement: automatically destroy low-CR undead. Non-combat stub."""
    name = "Destroy Undead"


class DestroyUndeadImprovement(Feature):
    """Destroy higher-CR undead. Non-combat stub."""
    name = "Destroy Undead Improvement"


class DivineIntervention(Feature):
    """Level 10: call on deity for miraculous aid. Non-combat stub."""
    name = "Divine Intervention"


class DivineInterventionImprovement(Feature):
    """Level 20: Divine Intervention automatically succeeds. Non-combat stub."""
    name = "Divine Intervention Improvement"


# ---------------------------------------------------------------------------
# Shared domain stubs
# ---------------------------------------------------------------------------

class BonusProficiency(Feature):
    """Domain-granted armor/weapon proficiency (Life: heavy armor; War: heavy armor + martial). Non-combat stub."""
    name = "Bonus Proficiency"


# ---------------------------------------------------------------------------
# Life Domain stubs
# ---------------------------------------------------------------------------

class DiscipleOfLife(Feature):
    """Life Domain lv1: healing spells restore 2 + spell_level extra HP. Non-combat stub."""
    name = "Disciple of Life"


class PreserveLife(Feature):
    """Life Domain Channel Divinity: distribute 5×cleric_level HP as healing. Non-combat stub."""
    name = "Preserve Life"


class BlessedHealer(Feature):
    """Life Domain lv6: healing another creature also heals you. Non-combat stub."""
    name = "Blessed Healer"


class SupremeHealing(Feature):
    """Life Domain lv17: maximize healing dice instead of rolling. Non-combat stub."""
    name = "Supreme Healing"


# ---------------------------------------------------------------------------
# War Domain — combat features
# ---------------------------------------------------------------------------

class WarPriest(Feature):
    """
    War Domain lv1. After taking the Attack action, make one weapon attack as
    a bonus action. Uses per long rest = WIS modifier (minimum 1).

    AI fires automatically on the first attack_resolved event each turn when
    uses remain and a bonus action is available.
    """
    name = "War Priest"
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._uses_remaining     = 0
        self._used_this_turn     = False

    def attach(self, owner, bus):
        super().attach(owner, bus)
        wis_mod = max(1, owner.statblock.mods.get("Wis", 0))
        self._uses_remaining = wis_mod
        print(f"  {owner.name}: War Priest ({wis_mod} uses)")

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used_this_turn = False

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        if self._uses_remaining <= 0 or self._used_this_turn:
            return
        target = data.get("target")
        if not (target and target.is_alive()):
            return
        if not self.owner.actions.use_bonus_action():
            return

        self._uses_remaining -= 1
        self._used_this_turn  = True   # prevent re-entry from the bonus attack's attack_resolved

        weapons = [i for i in self.owner.equipped_items if i.item_type == "weapon"]
        if not weapons:
            self.owner.actions.bonus_actions += 1   # refund
            return

        weapon = weapons[0]
        print(f"  {self.owner.name}: War Priest — bonus attack!")
        from core.attack import WeaponAttack
        WeaponAttack(self.owner, target, weapon.damage_die, item=weapon).declare_attack()


class GuidedStrike(Feature):
    """War Domain lv2: Channel Divinity — +10 to one attack roll. Non-combat stub."""
    name = "Guided Strike"


class WarGodsBlessing(Feature):
    """War Domain lv6: Channel Divinity reaction — +10 to an ally's attack roll. Non-combat stub."""
    name = "War God's Blessing"


class DivineStrike(Feature):
    """
    War Domain / Life Domain lv8: once per turn deal +1d8 weapon damage
    on a hit (scales to +2d8 at cleric level 14).
    """
    name = "Divine Strike"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._used_this_turn = False

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._used_this_turn = False

    def on_hit(self, data):
        if data.get("attacker") is not self.owner or self._used_this_turn:
            return
        attack = data.get("attack")
        if not attack:
            return
        cleric_lvl = next(
            (lvl for cls, lvl in getattr(self.owner, "classes", []) if cls == "Cleric"),
            1,
        )
        n_dice = 2 if cleric_lvl >= 14 else 1
        attack.extra_dice.extend([(1, 8)] * n_dice)
        self._used_this_turn = True
        print(f"  {self.owner.name}: Divine Strike +{n_dice}d8!")


class AvatarOfBattle(Feature):
    """War Domain lv17: resistance to non-magical bludgeoning/piercing/slashing damage. Non-combat stub."""
    name = "Avatar of Battle"


# ---------------------------------------------------------------------------
# Light Domain stubs
# ---------------------------------------------------------------------------

class WardingFlare(Feature):
    """Light Domain lv1: reaction — impose disadvantage on one attack against you or an ally. Non-combat stub."""
    name = "Warding Flare"


class RadianceOfTheDawn(Feature):
    """Light Domain Channel Divinity: deal 2d10 + cleric_level radiant to undead. Non-combat stub."""
    name = "Radiance of the Dawn"


class ImprovedFlare(Feature):
    """Light Domain lv6: Warding Flare can protect allies within 30ft. Non-combat stub."""
    name = "Improved Flare"


class PotentSpellcasting(Feature):
    """Light Domain lv8: add WIS modifier to cleric cantrip damage rolls. Non-combat stub."""
    name = "Potent Spellcasting"


class CoronaOfLight(Feature):
    """Light Domain lv17: sunlight aura — undead/vampire weaknesses within 60ft. Non-combat stub."""
    name = "Corona of Light"
