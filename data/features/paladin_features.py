"""
data/features/paladin_features.py

Paladin class features — combat-relevant through level 20.

Base paladin
  lv1   Lay on Hands          (healing pool = 5×level HP; heals self when low)
  lv2   Divine Smite          (spend spell slot after melee hit: +2d8 radiant, +1d8/slot above 1st)
  lv5   Extra Attack          (2 attacks per action)
  lv6   Aura of Protection    (CHA mod to saves for self and allies within 10ft)
  lv7   Aura of Courage       (you and allies within 10ft can't be frightened)
  lv11  Improved Divine Smite (+1d8 radiant on every melee hit, no slot required)

Oath of Devotion subclass
  lv3   Sacred Weapon         (bonus action: CHA mod to attack rolls for 1 min, concentration)
  lv20  Holy Nimbus           (sunlight aura dealing 10 radiant to nearby enemies each turn)

Oath of Vengeance subclass
  lv3   Vow of Enmity         (bonus action: advantage vs one creature until start of next turn)
  lv7   Relentless Avenger    (on OA hit: move up to half speed toward target without OA)
  lv15  Soul of Vengeance     (reaction: attack when Vow target attacks anyone)
"""
import random
from data.features.base import Feature


# ---------------------------------------------------------------------------
# Level 1 — Lay on Hands
# ---------------------------------------------------------------------------

class LayOnHands(Feature):
    """
    Healing pool = 5 × paladin level HP.
    AI: use as a bonus action when HP drops below 35%.
    """
    name = "Lay on Hands"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._pool = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        pal_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Paladin"), 1
        )
        self._pool = 5 * pal_lvl
        print(f"  {owner.name}: Lay on Hands pool = {self._pool} HP")

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner or self._pool <= 0:
            return
        hp_frac = creature.hp / max(creature.max_hp, 1)
        if hp_frac < 0.35 and creature.actions.use_bonus_action():
            heal = min(self._pool, creature.max_hp - creature.hp)
            creature.heal(heal)
            self._pool -= heal
            print(f"  {creature.name}: Lay on Hands — heals {heal} HP "
                  f"({creature.hp}/{creature.max_hp}, pool={self._pool})")


# ---------------------------------------------------------------------------
# Level 2 — Divine Smite
# ---------------------------------------------------------------------------

class DivineSmite(Feature):
    """
    When you hit a creature with a melee weapon attack, expend one spell slot
    to deal bonus radiant damage: 2d8 (1st level) + 1d8/slot above 1st.
    AI uses 1st-level slots (2d8) by default; upgrades on crits.

    Spell slots tracked as a simple counter: 2 at lv2-4, 3 at lv5-8, etc.
    """
    name = "Divine Smite"
    EVENT_MAP = {"hit": "on_hit"}

    def __init__(self):
        super().__init__()
        self._slots_remaining = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        pal_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Paladin"), 1
        )
        # Simplified: total usable smite slots
        if pal_lvl >= 17:
            self._slots_remaining = 7
        elif pal_lvl >= 13:
            self._slots_remaining = 6
        elif pal_lvl >= 9:
            self._slots_remaining = 5
        elif pal_lvl >= 5:
            self._slots_remaining = 4
        elif pal_lvl >= 3:
            self._slots_remaining = 3
        else:
            self._slots_remaining = 2
        print(f"  {owner.name}: Divine Smite ready ({self._slots_remaining} slots)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or getattr(attack, "range", False):
            return   # melee only

        # Prefer the shared PaladinSpellcasting pool when present
        slots = getattr(self.owner, "spell_slots", None)
        if slots is not None:
            if not slots.has_slot(1):
                return
            slots.spend_slot(1)
            slots_left = slots.remaining()
        else:
            if self._slots_remaining <= 0:
                return
            self._slots_remaining -= 1
            slots_left = self._slots_remaining

        n_dice = 3 if attack.critical else 2
        attack.extra_dice.extend([(1, 8)] * n_dice)
        attack.damage_type = "radiant"
        print(f"  {self.owner.name}: Divine Smite! ({n_dice}d8 radiant, "
              f"slots={slots_left})")


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
# Level 6 — Aura of Protection
# ---------------------------------------------------------------------------

class AuraOfProtection(Feature):
    """
    You and friendly creatures within 10ft add your CHA modifier (min 1) to
    all saving throws while you are conscious.
    Hooks the "saving_throw" event (broadcast on the shared bus) and applies
    the bonus to allies within range.
    """
    name = "Aura of Protection"
    EVENT_MAP = {"saving_throw": "on_saving_throw"}

    def __init__(self):
        super().__init__()
        self._radius = 2   # 10ft = 2 squares

    def attach(self, owner, bus):
        super().attach(owner, bus)
        cha_mod = owner.statblock.mods.get("Cha", 0)
        print(f"  {owner.name}: Aura of Protection "
              f"(+{max(1, cha_mod)} to saves within {self._radius * 5}ft)")

    def on_saving_throw(self, ctx):
        if not self.owner.is_alive():
            return
        target = ctx.get("target")
        if target is None:
            return
        # Apply to self and same-team allies
        if target.team != self.owner.team:
            return

        # Check distance (5ft per square, Chebyshev)
        if target is not self.owner:
            own_pos = getattr(self.owner, "pos", None)
            tgt_pos = getattr(target, "pos", None)
            if own_pos and tgt_pos:
                dist = max(abs(own_pos[0] - tgt_pos[0]),
                           abs(own_pos[1] - tgt_pos[1]))
                if dist > self._radius:
                    return

        cha_mod = self.owner.statblock.mods.get("Cha", 0)
        ctx["bonus"] = ctx.get("bonus", 0) + max(1, cha_mod)


# ---------------------------------------------------------------------------
# Level 7 — Aura of Courage
# ---------------------------------------------------------------------------

class AuraOfCourage(Feature):
    """
    You and friendly creatures within 10ft can't be frightened while you
    are conscious. Removes the 'frightened' condition if already present.
    """
    name = "Aura of Courage"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        if not self.owner.is_alive():
            return
        creature = ctx.get("creature")
        if creature is None:
            return
        if creature.team != self.owner.team:
            return
        if creature.has_condition("frightened"):
            own_pos = getattr(self.owner, "pos", None)
            tgt_pos = getattr(creature, "pos", None)
            if own_pos and tgt_pos:
                dist = max(abs(own_pos[0] - tgt_pos[0]),
                           abs(own_pos[1] - tgt_pos[1]))
                if dist <= 2:
                    creature.remove_condition("frightened")
                    print(f"  {creature.name}: Aura of Courage — frightened removed")


# ---------------------------------------------------------------------------
# Level 11 — Improved Divine Smite
# ---------------------------------------------------------------------------

class ImprovedDivineSmite(Feature):
    """
    Whenever you hit with a melee weapon attack, deal an extra 1d8 radiant
    damage. This bonus requires no spell slot.
    """
    name = "Improved Divine Smite"
    EVENT_MAP = {"hit": "on_hit"}

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or getattr(attack, "range", False):
            return
        attack.extra_dice.append((1, 8))


class ImprovedDivineSmiteStub(Feature):
    """Placeholder — Improved Divine Smite is added at lv11."""
    name = "Improved Divine Smite Stub"


# ---------------------------------------------------------------------------
# Non-combat stubs
# ---------------------------------------------------------------------------

class DivineHealth(Feature):
    name = "Divine Health"

class CleansingTouch(Feature):
    name = "Cleansing Touch"

class AuraImprovements(Feature):
    name = "Aura Improvements"

class SacredOathFeature20(Feature):
    name = "Sacred Oath Feature 20"


# ---------------------------------------------------------------------------
# Oath of Devotion lv3 — Sacred Weapon
# ---------------------------------------------------------------------------

class SacredWeapon(Feature):
    """
    Bonus action (concentration): add CHA mod to attack rolls for 1 minute.
    AI activates on first turn if CHA mod > 0.
    """
    name = "Sacred Weapon"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":      "on_attack",
    }

    def __init__(self):
        super().__init__()
        self._active      = False
        self._cha_mod     = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._cha_mod = owner.statblock.mods.get("Cha", 0)
        print(f"  {owner.name}: Sacred Weapon (+{self._cha_mod} to attacks)")

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if not self._active and self._cha_mod > 0:
            if creature.actions.use_bonus_action():
                self._active = True
                creature.start_concentration("Sacred Weapon", feature=self)
                print(f"  {creature.name}: Sacred Weapon active "
                      f"(+{self._cha_mod} to attack rolls)")

    def on_attack(self, data):
        if data.get("attacker") is not self.owner or not self._active:
            return
        attack = data.get("attack")
        if attack:
            attack.to_hit_mod += self._cha_mod

    def on_concentration_broken(self):
        self._active = False
        print(f"  {self.owner.name}: Sacred Weapon fades")


class AuraOfDevotion(Feature):
    name = "Aura of Devotion"

class PurityOfSpirit(Feature):
    name = "Purity of Spirit"


class HolyNimbus(Feature):
    """
    Oath of Devotion lv20: aura of sunlight — enemies that start their turn
    within 30ft take 10 radiant damage.
    """
    name = "Holy Nimbus"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is None or not self.owner.is_alive():
            return
        if creature is self.owner:
            return
        if creature.team == self.owner.team:
            return
        own_pos = getattr(self.owner, "pos", None)
        tgt_pos = getattr(creature, "pos", None)
        if own_pos and tgt_pos:
            dist = max(abs(own_pos[0] - tgt_pos[0]),
                       abs(own_pos[1] - tgt_pos[1]))
            if dist <= 6:   # 30ft = 6 squares
                print(f"  {creature.name}: Holy Nimbus — 10 radiant damage!")
                creature.take_damage(10, damage_type="radiant")


# ---------------------------------------------------------------------------
# Oath of Vengeance lv3 — Vow of Enmity
# ---------------------------------------------------------------------------

class VowOfEnmity(Feature):
    """
    Bonus action: advantage on all attack rolls against one creature until
    the start of your next turn.
    AI activates targeting the lowest-HP enemy.
    """
    name = "Vow of Enmity"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":      "on_attack",
    }

    def __init__(self):
        super().__init__()
        self._vow_target = None

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        self._vow_target = None   # expires each turn
        # Re-apply via bonus action if available (targets lowest-HP enemy)
        if creature.actions.use_bonus_action():
            # Find lowest-HP enemy via event bus context (no battle_map ref here)
            # We'll mark it when on_attack fires instead
            self._pending_vow = True
        else:
            self._pending_vow = False

    def on_attack(self, data):
        attacker = data.get("attacker")
        attack   = data.get("attack")
        target   = data.get("target")
        if attacker is not self.owner or not attack:
            return
        # Auto-set vow target to first attacked enemy this turn
        if getattr(self, "_pending_vow", False) and self._vow_target is None:
            self._vow_target = target
            self._pending_vow = False
            print(f"  {self.owner.name}: Vow of Enmity on {target.name}!")
        if target is self._vow_target:
            attack.advantage = True


# ---------------------------------------------------------------------------
# Oath of Vengeance lv7 — Relentless Avenger
# ---------------------------------------------------------------------------

class RelentlessAvenger(Feature):
    """
    When you hit with an opportunity attack, move up to half your speed
    without provoking OAs. (Flagged — not fully tracked in this sim.)
    """
    name = "Relentless Avenger"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        print(f"  {owner.name}: Relentless Avenger — free move on OA hit")


# ---------------------------------------------------------------------------
# Oath of Vengeance lv15 — Soul of Vengeance
# ---------------------------------------------------------------------------

class SoulOfVengeance(Feature):
    """
    Reaction: when the creature under your Vow of Enmity makes an attack,
    you can make a melee weapon attack against it.
    """
    name = "Soul of Vengeance"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attacker = data.get("attacker")
        if attacker is self.owner:
            return

        # Find our Vow target
        vow = next((f for f in self.owner.features if isinstance(f, VowOfEnmity)), None)
        if not vow or attacker is not vow._vow_target:
            return

        if not self._owner_can_react():
            return
        if not self.owner.actions.use_reaction():
            return

        weapons = [i for i in self.owner.equipped_items if i.item_type == "weapon"
                   and getattr(i, "attack_type", "melee") == "melee"]
        if not weapons:
            self.owner.actions.reactions += 1
            return

        weapon = weapons[0]
        print(f"  {self.owner.name}: Soul of Vengeance — attacks {attacker.name}!")
        from core.attack import WeaponAttack
        WeaponAttack(self.owner, attacker, weapon.damage_die, item=weapon).declare_attack()


class AvengerAngel(Feature):
    name = "Avenging Angel"


# ---------------------------------------------------------------------------
# Non-combat stubs
# ---------------------------------------------------------------------------

class DivineSense(Feature):
    """Lv1: detect celestials/fiends/undead within 60ft. Non-combat stub."""
    name = "Divine Sense"
