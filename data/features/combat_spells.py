"""
data/features/combat_spells.py

Combat-relevant SRD spells for all spellcasting classes.

── Pseudo-weapon cantrips (spell attack → TacticalAI picks them up) ──────────
  FireBolt          Wizard/Sorcerer  1d10 fire, range 120
  RayOfFrost        Wizard           1d8 cold, range 60, -10ft speed on hit
  ChillTouch        Wizard           1d8 necrotic, range 120, no healing
  GuidingBolt       Cleric           4d6 radiant, next attacker vs target has adv
  InflictWounds     Cleric           3d10 necrotic, melee

── Save-based cantrips (TurnStarted, use_action, _last_target) ───────────────
  SacredFlame       Cleric  DEX save, 1d8 radiant — ignores cover
  TollTheDead       Cleric  WIS save, 1d8 necrotic (1d12 if missing HP)
  PoisonSpray       Druid   CON save, 1d12 poison (10ft range)

── Healing / utility ─────────────────────────────────────────────────────────
  HealingWord       Cleric/Druid   bonus action, 1d4+mod HP when < 35%
  CureWounds        Cleric/Druid   action, 1d8+mod HP when < 25%
  MistyStep         Wizard/Sorce.  bonus action, teleport 30ft (when adjacent enemy)

── Action damage spells: 1st level ──────────────────────────────────────────
  MagicMissile      Wizard/Sorc.  3 darts, auto-hit, 1d4+1 each (+ 1 per upcast)
  BurningHands      Wizard/Sorc.  DEX save, 3d6 fire (+ 1d6/upcast)
  Thunderwave       Wizard/Cleric STR save, 2d8 thunder (+ 1d8/upcast)
  ScorchingRay      Wizard/Sorc.  3 rays × 2d6 fire (+ 1 ray/upcast)

── Action damage spells: 3rd–5th level ──────────────────────────────────────
  Fireball          Wizard/Sorc.  DEX save, 8d6 fire (+ 1d6/upcast)
  LightningBolt     Wizard/Sorc.  DEX save, 8d6 lightning (+ 1d6/upcast)
  Blight            Cleric/Druid  CON save, 8d8 necrotic (no upcast; single target)
  ConeOfCold        Wizard        CON save, 8d8 cold (+ 1d8/upcast)
  FlameStrike       Cleric        DEX save, 4d6 fire + 4d6 radiant (+ 1d6/upcast)

── Defensive ─────────────────────────────────────────────────────────────────
  MirrorImage       Wizard/Sorc.  bonus action, 3 illusory duplicates absorb hits

── Concentration control ─────────────────────────────────────────────────────
  HoldPerson        Wizard/Cleric WIS save or paralyzed; save again each turn
  HoldMonster       Wizard        WIS save or paralyzed; any creature type
  Slow              Wizard        WIS save; halved speed, -2 AC, no reactions

── Concentration AoE ─────────────────────────────────────────────────────────
  SpiritGuardians   Cleric        3d8 radiant/necrotic around caster each turn
  MoonbeamSpell     Druid         CON save, 2d10 radiant around caster each turn

── Bonus-action attack ───────────────────────────────────────────────────────
  SpiritualWeapon   Cleric        NOT concentration; bonus action attack each turn

── Banishment ────────────────────────────────────────────────────────────────
  Banishment        Cleric/Paladin CHA save; target incapacitated while conc. holds
"""
import random
from data.features.base import Feature
from core.saving_throw import SavingThrow, DamageOnSave
from core.item import Item


# ── Module-level helpers ─────────────────────────────────────────────────────

_ABILITY_BY_CLASS = {
    "Wizard": "Int", "Sorcerer": "Cha", "Cleric": "Wis",
    "Druid": "Wis", "Bard": "Cha", "Paladin": "Cha", "Ranger": "Wis",
}


def _spell_ability(owner) -> str:
    for cls, _ in getattr(owner, "classes", []):
        if cls in _ABILITY_BY_CLASS:
            return _ABILITY_BY_CLASS[cls]
    return "Int"


def _cantrip_scale(owner) -> int:
    """Cantrip damage scaling: 1 die at lv1, +1 at lv5/11/17."""
    lvl = max((l for _, l in getattr(owner, "classes", [])), default=1)
    return 1 + (lvl >= 5) + (lvl >= 11) + (lvl >= 17)


def _spell_dc(owner) -> int:
    slots = getattr(owner, "spell_slots", None)
    if slots:
        return slots.spell_dc
    ab  = _spell_ability(owner)
    mod = owner.statblock.mods.get(ab, 0)
    return 8 + owner.proficiency + mod


def _spell_atk(owner) -> int:
    slots = getattr(owner, "spell_slots", None)
    if slots:
        return slots.spell_attack
    ab  = _spell_ability(owner)
    mod = owner.statblock.mods.get(ab, 0)
    return owner.proficiency + mod


def _make_spell_weapon(owner, name, damage_die, damage_type,
                       attack_type="range", normal_range=120, long_range=120):
    """
    Create and equip a pseudo-weapon item for a spell that uses a spell attack roll.
    Cancels ability-mod contribution to damage (spells don't add it unless noted).
    """
    ability = _spell_ability(owner)
    ab_mod  = owner.statblock.mods.get(ability, 0)
    item = Item(
        name         = name,
        type         = "weapon",
        damage_die   = damage_die,
        damageType   = damage_type,
        ability      = ability,
        weapon_type  = "simple",
        attack_type  = attack_type,
        attack_bonus = 0,
        damage_bonus = -ab_mod,   # cancel ability mod — spells don't add it to dmg
        normal_range = normal_range,
        long_range   = long_range,
        properties   = [],
    )
    owner.inventory.append(item)
    owner.equipped_items.append(item)
    return item


# ── _ActionSpell base — action-cost spells with last-target tracking ──────────

class _ActionSpell(Feature):
    """
    Base for action-cost damaging/control spells.

    - Tracks the last enemy attacked via attack_resolved.
    - On TurnStarted (own turn): checks priority gate, consumes action + slot,
      calls self._cast(caster, target, slot_level).
    - Priority gate: spells only fire when no higher-slot spell could fire
      first; use MIN_SLOT_TO_DEFER so cheaper spells don't eat the action
      before the big ones get a chance.
    """
    SLOT_LEVEL:         int = 1
    MIN_SLOT_TO_DEFER:  int = 999   # if any slot >= this exists, defer to it
    IS_CANTRIP:         bool = False # True = no slot consumed, no defer check

    EVENT_MAP = {
        "TurnStarted":      "on_turn_started",
        "attack_resolved":  "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        target = self._last_target
        if not (target and target.is_alive()):
            return

        slots = getattr(creature, "spell_slots", None)

        if self.IS_CANTRIP:
            # Cantrip: only fire if no slots remain (prefer slotted spells)
            if slots and slots.has_slot(1):
                return
        else:
            if not (slots and slots.has_slot(self.SLOT_LEVEL)):
                return
            # Defer if a higher-tier spell is also loaded on this creature
            if slots.has_slot(self.MIN_SLOT_TO_DEFER):
                return

        if not creature.actions.use_action():
            return

        if self.IS_CANTRIP:
            self._cast(creature, target, 0)
        else:
            lvl = slots.spend_slot(self.SLOT_LEVEL)
            if lvl is None:
                creature.actions.actions += 1   # shouldn't happen, refund
                return
            self._cast(creature, target, lvl)

    def _cast(self, caster, target, slot_level: int):
        """Override in each spell subclass."""
        raise NotImplementedError


# ── Pseudo-weapon cantrips ────────────────────────────────────────────────────

class FireBolt(Feature):
    """Cantrip. Ranged spell attack, 1d10 fire (scales to 4d10 at lv17)."""
    name = "Fire Bolt"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        n = _cantrip_scale(owner)
        _make_spell_weapon(owner, "Fire Bolt", f"{n}d10", "fire")
        print(f"  {owner.name}: Fire Bolt ({n}d10 fire, 120ft)")


class RayOfFrost(Feature):
    """
    Cantrip. Ranged spell attack, 1d8 cold (scales to 4d8).
    On hit: target's speed reduced by 10ft until start of your next turn.
    """
    name = "Ray of Frost"
    EVENT_MAP = {"hit": "on_hit", "TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._slowed: dict = {}   # id(target) → (target, penalty)

    def attach(self, owner, bus):
        super().attach(owner, bus)
        n = _cantrip_scale(owner)
        _make_spell_weapon(owner, "Ray of Frost", f"{n}d8", "cold",
                           normal_range=60, long_range=60)
        print(f"  {owner.name}: Ray of Frost ({n}d8 cold, 60ft)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not (attack and attack.item and attack.item.name == "Ray of Frost"):
            return
        target = data.get("target")
        if target:
            target.speed = max(0, target.speed - 10)
            self._slowed[id(target)] = (target, 10)

    def on_turn_started(self, ctx):
        # Restore slowed creature at the start of OWNER's next turn
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        for key, (tgt, penalty) in list(self._slowed.items()):
            tgt.speed += penalty
        self._slowed.clear()


class ChillTouch(Feature):
    """Cantrip. Ranged spell attack, 1d8 necrotic (scales). Target can't regain HP."""
    name = "Chill Touch"
    EVENT_MAP = {"hit": "on_hit"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        n = _cantrip_scale(owner)
        _make_spell_weapon(owner, "Chill Touch", f"{n}d8", "necrotic")
        print(f"  {owner.name}: Chill Touch ({n}d8 necrotic, 120ft)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not (attack and attack.item and attack.item.name == "Chill Touch"):
            return
        target = data.get("target")
        if target:
            target.add_condition("no_healing")
            print(f"  {target.name}: Chill Touch — can't regain HP this round!")


class GuidingBolt(Feature):
    """
    1st-level spell attack. 4d6 radiant; next creature that attacks target
    before your next turn has advantage.
    """
    name = "Guiding Bolt"
    EVENT_MAP = {"hit": "on_hit", "attack": "on_attack", "TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._lit_target = None

    def attach(self, owner, bus):
        super().attach(owner, bus)
        _make_spell_weapon(owner, "Guiding Bolt", "4d6", "radiant")
        print(f"  {owner.name}: Guiding Bolt (4d6 radiant, 120ft)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not (attack and attack.item and attack.item.name == "Guiding Bolt"):
            return
        target = data.get("target")
        if target:
            self._lit_target = target
            print(f"  {target.name}: lit up by Guiding Bolt (next attacker has advantage!)")

    def on_attack(self, data):
        if not self._lit_target:
            return
        attacker = data.get("attacker")
        if attacker is self.owner:
            return   # not triggered by the caster themselves
        target = data.get("target")
        if target is self._lit_target:
            data.get("attack").advantage = True
            self._lit_target = None

    def on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._lit_target = None   # expires on caster's next turn


class InflictWounds(Feature):
    """1st-level melee spell attack. 3d10 necrotic (+ 1d10/upcast)."""
    name = "Inflict Wounds"
    EVENT_MAP = {"hit": "on_hit"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        _make_spell_weapon(owner, "Inflict Wounds", "3d10", "necrotic",
                           attack_type="melee", normal_range=5, long_range=5)
        print(f"  {owner.name}: Inflict Wounds (3d10 necrotic, melee)")

    def on_hit(self, data):
        """Spend a slot on hit to get the slot-scaled damage."""
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not (attack and attack.item and attack.item.name == "Inflict Wounds"):
            return
        slots = getattr(self.owner, "spell_slots", None)
        if slots and slots.has_slot(1):
            lvl = slots.spend_slot(1)
            extra = lvl - 1   # +1d10 per slot above 1st
            for _ in range(extra):
                attack.extra_dice.append((1, 10))


# ── Save-based cantrips ───────────────────────────────────────────────────────

class SacredFlame(_ActionSpell):
    """Cantrip. DEX save, 1d8 radiant (to 4d8 at lv17). Ignores cover."""
    name       = "Sacred Flame"
    IS_CANTRIP = True

    def _cast(self, caster, target, _slot):
        n   = _cantrip_scale(caster)
        dmg = sum(random.randint(1, 8) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=_spell_dc(caster),
            on_save=DamageOnSave.NONE,
            damage=dmg, damage_type="radiant",
        )
        print(f"  {caster.name}: Sacred Flame! ({n}d8 radiant, DC {_spell_dc(caster)})")


class TollTheDead(_ActionSpell):
    """Cantrip. WIS save, 1d8 necrotic (1d12 if target is missing HP)."""
    name       = "Toll the Dead"
    IS_CANTRIP = True

    def _cast(self, caster, target, _slot):
        n    = _cantrip_scale(caster)
        die  = 12 if target.hp < target.max_hp else 8
        dmg  = sum(random.randint(1, die) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Wis", dc=_spell_dc(caster),
            on_save=DamageOnSave.NONE,
            damage=dmg, damage_type="necrotic",
        )
        print(f"  {caster.name}: Toll the Dead! ({n}d{die} necrotic, DC {_spell_dc(caster)})")


class PoisonSpray(_ActionSpell):
    """Cantrip. CON save, 1d12 poison (to 4d12 at lv17). 10ft range."""
    name       = "Poison Spray"
    IS_CANTRIP = True

    def _cast(self, caster, target, _slot):
        n   = _cantrip_scale(caster)
        dmg = sum(random.randint(1, 12) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Con", dc=_spell_dc(caster),
            on_save=DamageOnSave.NONE,
            damage=dmg, damage_type="poison",
        )
        print(f"  {caster.name}: Poison Spray! ({n}d12 poison, DC {_spell_dc(caster)})")


# ── Healing ───────────────────────────────────────────────────────────────────

class HealingWord(Feature):
    """
    1st-level. Bonus action. Heal self for 1d4 + spell ability mod.
    AI casts when owner HP < 35%.
    """
    name = "Healing Word"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if creature.hp / max(creature.max_hp, 1) >= 0.35:
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(1)):
            return
        if not creature.actions.use_bonus_action():
            return
        lvl = slots.spend_slot(1)
        ab  = _spell_ability(creature)
        mod = creature.statblock.mods.get(ab, 0)
        heal = random.randint(1, 4) + max(0, mod)
        for _ in range(lvl - 1):
            heal += random.randint(1, 4)
        creature.heal(heal)
        print(f"  {creature.name}: Healing Word — +{heal} HP ({creature.hp}/{creature.max_hp})")


class CureWounds(_ActionSpell):
    """1st-level action. Heal self for 1d8 + spell ability mod when < 25% HP."""
    name       = "Cure Wounds"
    SLOT_LEVEL = 1

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if creature.hp / max(creature.max_hp, 1) >= 0.25:
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(1)):
            return
        if not creature.actions.use_action():
            return
        lvl = slots.spend_slot(1)
        ab  = _spell_ability(creature)
        mod = creature.statblock.mods.get(ab, 0)
        heal = sum(random.randint(1, 8) for _ in range(lvl)) + max(0, mod)
        creature.heal(heal)
        print(f"  {creature.name}: Cure Wounds — +{heal} HP ({creature.hp}/{creature.max_hp})")

    def _cast(self, caster, target, slot_level):
        pass   # healing handled in on_turn_started override


# ── Mobility ──────────────────────────────────────────────────────────────────

class MistyStep(Feature):
    """
    2nd-level. Bonus action. Teleport 30ft.
    AI uses when an enemy is adjacent (to escape melee).
    """
    name = "Misty Step"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        # Only step away when threatened in melee
        if not getattr(creature, "_in_melee", False):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(2)):
            return
        if not creature.actions.use_bonus_action():
            return
        slots.spend_slot(2)
        print(f"  {creature.name}: Misty Step! (teleports 30ft away)")
        # Actual position change handled by battle_map; flag for AI to note


# ── Action damage spells: 1st level ──────────────────────────────────────────

class MagicMissile(_ActionSpell):
    """
    1st-level. Auto-hit. 3 darts × 1d4+1 force (+ 1 dart/upcast slot).
    Defers to 3rd-level slots if available.
    """
    name              = "Magic Missile"
    SLOT_LEVEL        = 1
    MIN_SLOT_TO_DEFER = 3

    def _cast(self, caster, target, slot_level):
        n_darts = 3 + (slot_level - 1)
        total   = sum(random.randint(1, 4) + 1 for _ in range(n_darts))
        target.take_damage(total, damage_type="force")
        print(f"  {caster.name}: Magic Missile! ({n_darts} darts, {total} force — auto-hit)")


class BurningHands(_ActionSpell):
    """1st-level. DEX save, 3d6 fire (+ 1d6/upcast). Cone — single target in sim."""
    name              = "Burning Hands"
    SLOT_LEVEL        = 1
    MIN_SLOT_TO_DEFER = 3

    def _cast(self, caster, target, slot_level):
        n   = 3 + (slot_level - 1)
        dmg = sum(random.randint(1, 6) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="fire",
        )
        print(f"  {caster.name}: Burning Hands! ({n}d6 fire, DC {_spell_dc(caster)})")


class Thunderwave(_ActionSpell):
    """1st-level. STR save, 2d8 thunder (+ 1d8/upcast). AoE — primary target in sim."""
    name              = "Thunderwave"
    SLOT_LEVEL        = 1
    MIN_SLOT_TO_DEFER = 3

    def _cast(self, caster, target, slot_level):
        n   = 2 + (slot_level - 1)
        dmg = sum(random.randint(1, 8) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Str", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="thunder",
        )
        print(f"  {caster.name}: Thunderwave! ({n}d8 thunder, DC {_spell_dc(caster)})")


class ScorchingRay(_ActionSpell):
    """
    2nd-level. 3 rays, each a spell attack, 2d6 fire (+ 1 ray/upcast).
    Rolls each ray separately; missed rays deal no damage.
    """
    name              = "Scorching Ray"
    SLOT_LEVEL        = 2
    MIN_SLOT_TO_DEFER = 4

    def _cast(self, caster, target, slot_level):
        n_rays   = 3 + (slot_level - 2)
        sp_atk   = _spell_atk(caster)
        total    = 0
        hits     = 0
        for _ in range(n_rays):
            roll = random.randint(1, 20) + sp_atk
            if roll >= target.ac:
                dmg    = sum(random.randint(1, 6) for _ in range(2))
                target.take_damage(dmg, damage_type="fire")
                total += dmg
                hits  += 1
        print(f"  {caster.name}: Scorching Ray! ({hits}/{n_rays} rays hit, {total} fire)")


# ── Action damage spells: 3rd–5th level ──────────────────────────────────────

class Fireball(_ActionSpell):
    """3rd-level. DEX save, 8d6 fire (+ 1d6/upcast). AoE — primary target in sim."""
    name       = "Fireball"
    SLOT_LEVEL = 3

    def _cast(self, caster, target, slot_level):
        n   = 8 + (slot_level - 3)
        dmg = sum(random.randint(1, 6) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="fire",
        )
        print(f"  {caster.name}: Fireball! ({n}d6 fire, DC {_spell_dc(caster)})")


class LightningBolt(_ActionSpell):
    """3rd-level. DEX save, 8d6 lightning (+ 1d6/upcast). Line — primary target in sim."""
    name       = "Lightning Bolt"
    SLOT_LEVEL = 3

    def _cast(self, caster, target, slot_level):
        n   = 8 + (slot_level - 3)
        dmg = sum(random.randint(1, 6) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Dex", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="lightning",
        )
        print(f"  {caster.name}: Lightning Bolt! ({n}d6 lightning, DC {_spell_dc(caster)})")


class Blight(_ActionSpell):
    """4th-level. CON save, 8d8 necrotic. Single target (no upcast scaling here)."""
    name       = "Blight"
    SLOT_LEVEL = 4

    def _cast(self, caster, target, slot_level):
        dmg = sum(random.randint(1, 8) for _ in range(8))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Con", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="necrotic",
        )
        print(f"  {caster.name}: Blight! (8d8 necrotic, DC {_spell_dc(caster)})")


class ConeOfCold(_ActionSpell):
    """5th-level. CON save, 8d8 cold (+ 1d8/upcast). Cone — primary target in sim."""
    name       = "Cone of Cold"
    SLOT_LEVEL = 5

    def _cast(self, caster, target, slot_level):
        n   = 8 + (slot_level - 5)
        dmg = sum(random.randint(1, 8) for _ in range(n))
        SavingThrow.roll(
            caster=caster, target=target,
            ability="Con", dc=_spell_dc(caster),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="cold",
        )
        print(f"  {caster.name}: Cone of Cold! ({n}d8 cold, DC {_spell_dc(caster)})")


class FlameStrike(_ActionSpell):
    """5th-level. DEX save, 4d6 fire + 4d6 radiant (+ 1d6 each/upcast). AoE — single target."""
    name       = "Flame Strike"
    SLOT_LEVEL = 5

    def _cast(self, caster, target, slot_level):
        extra = slot_level - 5
        fire  = sum(random.randint(1, 6) for _ in range(4 + extra))
        rad   = sum(random.randint(1, 6) for _ in range(4 + extra))
        dc    = _spell_dc(caster)
        # Fire component
        SavingThrow.roll(caster=caster, target=target, ability="Dex", dc=dc,
                         on_save=DamageOnSave.HALF, damage=fire, damage_type="fire")
        # Radiant component (separate save for accurate half-damage)
        SavingThrow.roll(caster=caster, target=target, ability="Dex", dc=dc,
                         on_save=DamageOnSave.HALF, damage=rad,  damage_type="radiant")
        print(f"  {caster.name}: Flame Strike! ({fire} fire + {rad} radiant, DC {dc})")


# ── Defensive ─────────────────────────────────────────────────────────────────

class MirrorImage(Feature):
    """
    2nd-level. Bonus action. Creates 3 illusory duplicates.
    Each time an attack targets the caster, roll d20: on 6+, 11+, or 16+
    (depending on duplicates remaining) the duplicate is hit instead.
    """
    name = "Mirror Image"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":       "on_attack",
    }

    def __init__(self):
        super().__init__()
        self._duplicates = 0

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or self._duplicates > 0:
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(2)):
            return
        if not creature.actions.use_bonus_action():
            return
        slots.spend_slot(2)
        self._duplicates = 3
        print(f"  {creature.name}: Mirror Image! (3 duplicates)")

    def on_attack(self, data):
        if self._duplicates <= 0:
            return
        target = data.get("target")
        if target is not self.owner:
            return
        attack = data.get("attack")
        if not attack:
            return
        # Threshold: 3 dups → 6+, 2 dups → 8+, 1 dup → 11+
        thresholds = {3: 6, 2: 8, 1: 11}
        threshold = thresholds.get(self._duplicates, 11)
        roll = random.randint(1, 20)
        if roll >= threshold:
            attack.result["hit"] = False
            self._duplicates -= 1
            print(f"  {self.owner.name}: Mirror Image absorbs the hit! "
                  f"({self._duplicates} duplicates left)")


# ── Concentration control ─────────────────────────────────────────────────────

class HoldPerson(Feature):
    """
    2nd-level. Concentration. WIS save or paralyzed; target repeats save each turn.
    Paralyzed: attacker has advantage; melee attacks auto-crit (simplified: adv only).
    """
    name = "Hold Person"
    SLOT_LEVEL = 2
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
        "attack":          "on_attack",
        "saving_throw":    "on_saving_throw",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._held        = None
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        if creature is self._held and self._active:
            # Held creature repeats save at start of its turn
            result = SavingThrow.roll(
                caster=self.owner, target=creature,
                ability="Wis", dc=_spell_dc(self.owner),
                on_save=DamageOnSave.NONE,
            )
            if result.success:
                creature.remove_condition("paralyzed")
                self._held   = None
                self._active = False
                self.owner.break_concentration()
                print(f"  {creature.name}: breaks free from Hold Person!")
            return

        if creature is not self.owner:
            return

        # Own turn: cast if possible
        if self._active or getattr(creature, "concentration", None):
            return
        target = self._last_target
        if not (target and target.is_alive()):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(self.SLOT_LEVEL)):
            return
        if not creature.actions.use_action():
            return
        lvl = slots.spend_slot(self.SLOT_LEVEL)
        dc  = _spell_dc(creature)
        result = SavingThrow.roll(
            caster=creature, target=target,
            ability="Wis", dc=dc,
            on_save=DamageOnSave.NONE,
            condition_on_fail="paralyzed",
        )
        if not result.success:
            self._active = True
            self._held   = target
            creature.start_concentration("Hold Person", feature=self)
            print(f"  {creature.name}: Hold Person on {target.name}!")
        else:
            print(f"  {creature.name}: Hold Person — {target.name} resisted!")

    def on_attack(self, data):
        """Advantage on attack rolls against paralyzed target."""
        if not self._active or self._held is None:
            return
        if data.get("target") is self._held:
            attack = data.get("attack")
            if attack:
                attack.advantage = True

    def on_saving_throw(self, ctx):
        """Paralyzed creatures automatically fail STR and DEX saves."""
        if not self._active or self._held is None:
            return
        if ctx.get("target") is self._held and ctx.get("ability") in ("Str", "Dex"):
            ctx["bonus"] = ctx.get("bonus", 0) - 100   # effectively auto-fail

    def on_concentration_broken(self):
        if self._held and self._held.is_alive():
            self._held.remove_condition("paralyzed")
        self._active = False
        self._held   = None
        print(f"  {self.owner.name}: Hold Person ends")


class HoldMonster(HoldPerson):
    """
    5th-level. Same as Hold Person but affects any creature type.
    """
    name       = "Hold Monster"
    SLOT_LEVEL = 5

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        # Repeat-save check for held creature (same as HoldPerson)
        if creature is self._held and self._active:
            result = SavingThrow.roll(
                caster=self.owner, target=creature,
                ability="Wis", dc=_spell_dc(self.owner),
                on_save=DamageOnSave.NONE,
            )
            if result.success:
                creature.remove_condition("paralyzed")
                self._held   = None
                self._active = False
                self.owner.break_concentration()
                print(f"  {creature.name}: breaks free from Hold Monster!")
            return
        if creature is not self.owner:
            return
        if self._active or getattr(creature, "concentration", None):
            return
        target = self._last_target
        if not (target and target.is_alive()):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(self.SLOT_LEVEL)):
            return
        if not creature.actions.use_action():
            return
        slots.spend_slot(self.SLOT_LEVEL)
        dc = _spell_dc(creature)
        result = SavingThrow.roll(
            caster=creature, target=target,
            ability="Wis", dc=dc,
            on_save=DamageOnSave.NONE,
            condition_on_fail="paralyzed",
        )
        if not result.success:
            self._active = True
            self._held   = target
            creature.start_concentration("Hold Monster", feature=self)
            print(f"  {creature.name}: Hold Monster on {target.name}!")
        else:
            print(f"  {creature.name}: Hold Monster — {target.name} resisted!")

    def on_concentration_broken(self):
        if self._held and self._held.is_alive():
            self._held.remove_condition("paralyzed")
        self._active = False
        self._held   = None
        print(f"  {self.owner.name}: Hold Monster ends")


class Slow(Feature):
    """
    3rd-level. Concentration. WIS save or:
    speed halved, -2 AC/DEX saves, no reactions, can only cast OR move OR attack.
    AI: inflicts at start of combat; target repeats save each turn.
    Simplified: halve speed, -2 AC, add 'slowed' condition; target saves each turn.
    """
    name = "Slow"
    SLOT_LEVEL = 3
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._slowed_tgts: list = []
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        # Slowed creatures repeat save; also handle -2 AC via condition
        if creature in self._slowed_tgts and self._active and creature is not self.owner:
            result = SavingThrow.roll(
                caster=self.owner, target=creature,
                ability="Wis", dc=_spell_dc(self.owner),
                on_save=DamageOnSave.NONE,
            )
            if result.success:
                self._apply_slow(creature, reverse=True)
                self._slowed_tgts.remove(creature)
                if not self._slowed_tgts:
                    self.owner.break_concentration()
                print(f"  {creature.name}: shakes off Slow!")
            return

        if creature is not self.owner:
            return
        if self._active or getattr(creature, "concentration", None):
            return
        target = self._last_target
        if not (target and target.is_alive()):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(self.SLOT_LEVEL)):
            return
        if not creature.actions.use_action():
            return
        slots.spend_slot(self.SLOT_LEVEL)
        dc = _spell_dc(creature)
        result = SavingThrow.roll(
            caster=creature, target=target,
            ability="Wis", dc=dc,
            on_save=DamageOnSave.NONE,
        )
        if not result.success:
            self._apply_slow(target)
            self._slowed_tgts.append(target)
            self._active = True
            creature.start_concentration("Slow", feature=self)
            print(f"  {creature.name}: Slow! — {target.name} halved speed, -2 AC")
        else:
            print(f"  {creature.name}: Slow — {target.name} resisted!")

    def _apply_slow(self, target, reverse=False):
        delta = 2 if reverse else -2
        target.apply_misc_ac(delta)
        target.speed = max(0, target.speed + (target.speed if reverse else -target.speed // 2))
        if not reverse:
            target.add_condition("slowed")
        else:
            target.remove_condition("slowed")

    def on_concentration_broken(self):
        for t in list(self._slowed_tgts):
            if t.is_alive():
                self._apply_slow(t, reverse=True)
        self._slowed_tgts.clear()
        self._active = False
        print(f"  {self.owner.name}: Slow ends")


class Banishment(Feature):
    """
    4th-level. Concentration. CHA save or target is banished (incapacitated)
    for duration. If concentration holds for 1 minute, creature is gone permanently.
    Simplified: banished = incapacitated condition while concentration holds.
    """
    name = "Banishment"
    SLOT_LEVEL = 4
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._banished    = None
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is self._banished and self._active:
            result = SavingThrow.roll(
                caster=self.owner, target=creature,
                ability="Cha", dc=_spell_dc(self.owner),
                on_save=DamageOnSave.NONE,
            )
            if result.success:
                creature.remove_condition("incapacitated")
                self._banished = None
                self._active   = False
                self.owner.break_concentration()
                print(f"  {creature.name}: returns from banishment!")
            return
        if creature is not self.owner:
            return
        if self._active or getattr(creature, "concentration", None):
            return
        target = self._last_target
        if not (target and target.is_alive()):
            return
        slots = getattr(creature, "spell_slots", None)
        if not (slots and slots.has_slot(self.SLOT_LEVEL)):
            return
        if not creature.actions.use_action():
            return
        slots.spend_slot(self.SLOT_LEVEL)
        result = SavingThrow.roll(
            caster=creature, target=target,
            ability="Cha", dc=_spell_dc(creature),
            on_save=DamageOnSave.NONE,
            condition_on_fail="incapacitated",
        )
        if not result.success:
            self._active   = True
            self._banished = target
            creature.start_concentration("Banishment", feature=self)
            print(f"  {creature.name}: Banishment — {target.name} banished!")
        else:
            print(f"  {creature.name}: Banishment — {target.name} resisted!")

    def on_concentration_broken(self):
        if self._banished and self._banished.is_alive():
            self._banished.remove_condition("incapacitated")
        self._active   = False
        self._banished = None
        print(f"  {self.owner.name}: Banishment ends")


# ── Concentration AoE ─────────────────────────────────────────────────────────

class SpiritGuardians(Feature):
    """
    3rd-level. Concentration. 15ft aura around caster.
    When a hostile creature starts its turn within range: 3d8 radiant or necrotic
    (WIS save halves). +1d8/upcast slot above 3rd.
    """
    name = "Spirit Guardians"
    SLOT_LEVEL = 3
    RADIUS_SQ  = 3   # 15ft = 3 squares (Chebyshev)
    EVENT_MAP  = {
        "TurnStarted": "on_turn_started",
    }

    def __init__(self):
        super().__init__()
        self._active     = False
        self._slot_level = 3

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        if creature is self.owner:
            # Activate on first turn if not concentrating
            if self._active or getattr(creature, "concentration", None):
                return
            slots = getattr(creature, "spell_slots", None)
            if not (slots and slots.has_slot(self.SLOT_LEVEL)):
                return
            if not creature.actions.use_action():
                return
            lvl = slots.spend_slot(self.SLOT_LEVEL)
            self._active     = True
            self._slot_level = lvl
            creature.start_concentration("Spirit Guardians", feature=self)
            n = 3 + (lvl - 3)
            print(f"  {creature.name}: Spirit Guardians! ({n}d8 radiant aura, 15ft)")
            return

        # Hostile creature starts turn — check range
        if not self._active or not self.owner.is_alive():
            return
        if creature.team == self.owner.team:
            return

        own_pos = getattr(self.owner, "pos", None)
        tgt_pos = getattr(creature, "pos", None)
        if own_pos and tgt_pos:
            dist = max(abs(own_pos[0] - tgt_pos[0]), abs(own_pos[1] - tgt_pos[1]))
            if dist > self.RADIUS_SQ:
                return

        n   = 3 + (self._slot_level - 3)
        dmg = sum(random.randint(1, 8) for _ in range(n))
        SavingThrow.roll(
            caster=self.owner, target=creature,
            ability="Wis", dc=_spell_dc(self.owner),
            on_save=DamageOnSave.HALF,
            damage=dmg, damage_type="radiant",
        )
        print(f"  {creature.name}: Spirit Guardians — {dmg} radiant!")

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: Spirit Guardians fades")


class MoonbeamSpell(Feature):
    """
    2nd-level. Concentration. 5ft-radius cylinder deals 2d10 radiant per turn.
    CON save halves. +1d10/upcast. Move beam as bonus action.
    Simplified: damages target from _last_target tracking on their turn.
    """
    name = "Moonbeam"
    SLOT_LEVEL = 2
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._slot_level  = 2
        self._beam_target = None
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")

        if creature is self.owner:
            if not self._active:
                slots = getattr(creature, "spell_slots", None)
                if not (slots and slots.has_slot(self.SLOT_LEVEL)):
                    return
                if getattr(creature, "concentration", None):
                    return
                if not creature.actions.use_action():
                    return
                lvl = slots.spend_slot(self.SLOT_LEVEL)
                self._active      = True
                self._slot_level  = lvl
                self._beam_target = self._last_target
                creature.start_concentration("Moonbeam", feature=self)
                n = 2 + (lvl - 2)
                print(f"  {creature.name}: Moonbeam! ({n}d10 radiant/turn)")
            else:
                # Move beam to new target as bonus action
                if self._last_target and self._last_target.is_alive():
                    if creature.actions.use_bonus_action():
                        self._beam_target = self._last_target
            return

        if creature is self._beam_target and self._active and creature.is_alive():
            n   = 2 + (self._slot_level - 2)
            dmg = sum(random.randint(1, 10) for _ in range(n))
            SavingThrow.roll(
                caster=self.owner, target=creature,
                ability="Con", dc=_spell_dc(self.owner),
                on_save=DamageOnSave.HALF,
                damage=dmg, damage_type="radiant",
            )
            print(f"  {creature.name}: caught in Moonbeam — {dmg} radiant!")

    def on_concentration_broken(self):
        self._active     = False
        self._beam_target = None
        print(f"  {self.owner.name}: Moonbeam fades")


# ── Bonus-action attack ───────────────────────────────────────────────────────

class SpiritualWeapon(Feature):
    """
    2nd-level. NOT concentration. Bonus action to summon; bonus action to attack
    each subsequent turn. 1d8 force + spell ability (+ 1d8 per 2 slot levels above 2nd).
    """
    name = "Spiritual Weapon"
    EVENT_MAP = {
        "TurnStarted":     "on_turn_started",
        "attack_resolved": "on_attack_resolved",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._slot_level  = 2
        self._last_target = None

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        t = data.get("target")
        if t and t.is_alive():
            self._last_target = t

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return

        if not self._active:
            slots = getattr(creature, "spell_slots", None)
            if not (slots and slots.has_slot(2)):
                return
            if not creature.actions.use_bonus_action():
                return
            lvl = slots.spend_slot(2)
            self._active     = True
            self._slot_level = lvl
            n = 1 + (lvl - 2) // 2
            print(f"  {creature.name}: Spiritual Weapon! ({n}d8 force, bonus action)")
            return

        # Attack with the weapon as bonus action
        target = self._last_target
        if not (target and target.is_alive()):
            return
        if not creature.actions.use_bonus_action():
            return

        sp_atk = _spell_atk(creature)
        ab     = _spell_ability(creature)
        mod    = creature.statblock.mods.get(ab, 0)
        n      = 1 + (self._slot_level - 2) // 2
        roll   = random.randint(1, 20) + sp_atk
        if roll >= target.ac:
            dmg = sum(random.randint(1, 8) for _ in range(n)) + mod
            target.take_damage(dmg, damage_type="force")
            print(f"  {creature.name}: Spiritual Weapon hits {target.name} — {dmg} force!")
        else:
            print(f"  {creature.name}: Spiritual Weapon misses {target.name}")
