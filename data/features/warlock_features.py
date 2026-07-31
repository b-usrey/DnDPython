"""
data/features/warlock_features.py

Warlock class features — combat-relevant through level 20.

Base warlock
  lv1   Eldritch Blast       (ranged spell attack: 1d10 force, +1 beam at lv5/10/17;
                              represented as equipped weapon item with scaling base dice)
  lv1   Pact Magic           (short-rest spell slots: 1-4 slots, all 5th-level)
  lv2   Agonizing Blast      (invocation: add CHA mod to each Eldritch Blast beam)
  lv2   Repelling Blast      (invocation: push target 10ft on hit)

Warlock spells (tracked as features)
  Hex                        (concentration: +1d6 necrotic to attacks vs target;
                              bonus action to place, lasts 1 hour / until target drops)

Fiend subclass
  lv1   Dark One's Blessing  (gain temp HP = CHA mod + warlock level on kill)
  lv6   Dark One's Own Luck  (add d10 to one ability check or save per rest)
  lv10  Fiendish Resilience  (choose resistance to one damage type per rest)

Great Old One subclass
  lv6   Entropic Ward        (reaction: impose disadvantage on attack, regain slot on miss)
  lv10  Thought Shield       (resistance to psychic damage, telepathic reflection)
"""
import random
from data.features.base import Feature
from core.item import Item


# ---------------------------------------------------------------------------
# Level 1 — Eldritch Blast (weapon representation)
# ---------------------------------------------------------------------------

class EldritchBlast(Feature):
    """
    Ranged spell attack dealing 1d10 force damage per beam.
    Beams: 1 at lv1-4, 2 at lv5-9, 3 at lv10-16, 4 at lv17+.

    Represented as an equipped weapon Item so TacticalAI can see and use it.
    The Item has ability="Cha" so Attack.__init__ computes prof+CHA as to-hit.
    Extra beams are added as extra_dice on hit.
    """
    name = "Eldritch Blast"
    EVENT_MAP = {"hit": "on_hit"}

    def __init__(self):
        super().__init__()
        self._extra_beams = 0   # beams beyond the first (each adds 1d10)

    def attach(self, owner, bus):
        super().attach(owner, bus)
        warlock_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Warlock"), 1
        )
        self._extra_beams = (
            3 if warlock_lvl >= 17 else
            2 if warlock_lvl >= 10 else
            1 if warlock_lvl >= 5  else
            0
        )
        total_beams = self._extra_beams + 1

        # Create and equip the Eldritch Blast pseudo-weapon
        eb_item = Item(
            name         = "Eldritch Blast",
            type         = "weapon",
            damage_die   = "1d10",
            damageType   = "force",
            ability      = "Cha",
            weapon_type  = "simple",
            attack_type  = "range",
            attack_bonus = 0,
            damage_bonus = 0,
            normal_range = 120,
            long_range   = 120,
            properties   = [],
        )
        owner.inventory.append(eb_item)
        owner.equipped_items.append(eb_item)
        owner.equipped_slots["hand1"] = eb_item.name

        print(f"  {owner.name}: Eldritch Blast ({total_beams} beam(s), "
              f"1d10 force each, 120ft range)")

    def on_hit(self, data):
        if data.get("attacker") is not self.owner or self._extra_beams == 0:
            return
        attack = data.get("attack")
        if not attack:
            return
        item = getattr(attack, "item", None)
        if not item or getattr(item, "name", "") != "Eldritch Blast":
            return
        # Add extra beam dice
        for _ in range(self._extra_beams):
            attack.extra_dice.append((1, 10))


# ---------------------------------------------------------------------------
# Level 1 — Pact Magic (slot tracker)
# ---------------------------------------------------------------------------

class PactMagic(Feature):
    """
    Short-rest spell slots (all at the highest level unlocked).
    Used by Hex and other slot-consuming features.
    """
    name = "Pact Magic"

    def __init__(self):
        super().__init__()
        self.slots_remaining = 0
        self.max_slots       = 0

    def attach(self, owner, bus):
        super().attach(owner, bus)
        warlock_lvl = next(
            (lvl for cls, lvl in getattr(owner, "classes", []) if cls == "Warlock"), 1
        )
        self.max_slots = (
            4 if warlock_lvl >= 17 else
            3 if warlock_lvl >= 11 else
            2 if warlock_lvl >= 2  else
            1
        )
        # Pact slot level (all slots are the same level)
        self.slot_level = (
            5 if warlock_lvl >= 9 else
            4 if warlock_lvl >= 7 else
            3 if warlock_lvl >= 5 else
            2 if warlock_lvl >= 3 else
            1
        )
        self.slots_remaining = self.max_slots
        # Expose the same interface as Spellcasting so spells can use owner.spell_slots
        cha_mod = owner.statblock.mods.get("Cha", 0)
        pb = 2 + (warlock_lvl - 1) // 4
        self.spell_attack = pb + cha_mod
        self.spell_dc     = 8 + pb + cha_mod
        owner.spell_slots = self
        print(f"  {owner.name}: Pact Magic ({self.slots_remaining}×{self.slot_level}th-level slots, "
              f"DC {self.spell_dc})")

    def use_slot(self) -> bool:
        if self.slots_remaining > 0:
            self.slots_remaining -= 1
            return True
        return False

    # ── Shared spell-slot interface (compatible with Spellcasting) ───────────

    def has_slot(self, min_level: int = 1) -> bool:
        return self.slots_remaining > 0 and self.slot_level >= min_level

    def spend_slot(self, min_level: int = 1) -> int | None:
        if self.has_slot(min_level):
            self.slots_remaining -= 1
            return self.slot_level
        return None

    def remaining(self) -> dict:
        return {self.slot_level: self.slots_remaining} if self.slots_remaining > 0 else {}


# ---------------------------------------------------------------------------
# Level 2 — Agonizing Blast (invocation)
# ---------------------------------------------------------------------------

class AgonizingBlast(Feature):
    """
    Eldritch Invocation: add CHA modifier to each Eldritch Blast beam's damage.
    Hooks Phase 2 "hit" after EldritchBlast's on_hit has added extra dice,
    then adds CHA mod to damage_mod (applies once per attack, covers all beams).
    """
    name = "Agonizing Blast"
    EVENT_MAP = {"hit": "on_hit"}

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack:
            return
        item = getattr(attack, "item", None)
        if not item or getattr(item, "name", "") != "Eldritch Blast":
            return
        cha_mod = self.owner.statblock.mods.get("Cha", 0)
        if cha_mod <= 0:
            return
        # Each beam (base + extra) gets CHA mod added
        total_beams = 1 + len([d for d in attack.extra_dice if d[1] == 10])
        attack.damage_mod += cha_mod * total_beams
        print(f"  {self.owner.name}: Agonizing Blast +{cha_mod * total_beams} damage")


# ---------------------------------------------------------------------------
# Level 2 — Repelling Blast (invocation)
# ---------------------------------------------------------------------------

class RepellingBlast(Feature):
    """
    Eldritch Invocation: when you hit a creature with Eldritch Blast, you
    can push it up to 10ft away. (Logged; movement not updated in battle_map
    here since we don't have a map reference in features.)
    """
    name = "Repelling Blast"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def on_attack_resolved(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if not attack or not attack.result.get("hit"):
            return
        item = getattr(attack, "item", None)
        if not item or getattr(item, "name", "") != "Eldritch Blast":
            return
        target = data.get("target")
        if target:
            print(f"  {self.owner.name}: Repelling Blast — "
                  f"{target.name} pushed 10ft away!")


# ---------------------------------------------------------------------------
# Hex (warlock concentration spell — typically accessed via Pact Magic)
# ---------------------------------------------------------------------------

class Hex(Feature):
    """
    Concentration spell (bonus action to place):
      - Target takes +1d6 necrotic damage on each hit.
      - If target drops, can move hex to new target as bonus action (next turn).
    AI places Hex at start of first turn; re-places if target drops.
    """
    name = "Hex"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "hit":         "on_hit",
    }

    def __init__(self):
        super().__init__()
        self._hex_target = None
        self._active     = False

    def _place_hex(self, target):
        pact = next((f for f in self.owner.features if isinstance(f, PactMagic)), None)
        if pact is None or not pact.use_slot():
            return False
        if not self.owner.actions.use_bonus_action():
            pact.slots_remaining += 1  # refund
            return False
        self._hex_target = target
        self._active     = True
        self.owner.start_concentration("Hex", feature=self)
        print(f"  {self.owner.name}: Hex placed on {target.name}!")
        return True

    def on_concentration_broken(self):
        self._active     = False
        self._hex_target = None
        print(f"  {self.owner.name}: Hex ends")

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if not self._active and self.owner.concentration is None:
            # Find an enemy to hex — reuse any hack we can
            # We don't have battle_map, so we'll place it on first attack's target
            pass   # Hex is placed reactively in on_hit when no target exists

    def on_hit(self, data):
        if data.get("attacker") is not self.owner:
            return
        target = data.get("target")
        attack = data.get("attack")
        if not attack:
            return

        # Auto-place Hex on first target if not active
        if not self._active and self.owner.concentration is None:
            self._place_hex(target)

        # Re-place if hex target is down and a new target appears
        if self._active and self._hex_target and not self._hex_target.is_alive():
            self.owner.break_concentration()
            self._place_hex(target)

        if self._active and target is self._hex_target:
            attack.extra_dice.append((1, 6))


# ---------------------------------------------------------------------------
# Fiend lv1 — Dark One's Blessing
# ---------------------------------------------------------------------------

class DarkOnesBlessing(Feature):
    """
    When you reduce a hostile creature to 0 HP, gain temp HP =
    CHA modifier + warlock level.
    """
    name = "Dark One's Blessing"
    EVENT_MAP = {"creature_downed": "on_downed"}

    def on_downed(self, data):
        victim = data.get("creature")
        if victim is None or victim.team == self.owner.team:
            return
        # Check the last attacker — crude check via recent attack context
        cha_mod     = self.owner.statblock.mods.get("Cha", 0)
        warlock_lvl = next(
            (lvl for cls, lvl in getattr(self.owner, "classes", []) if cls == "Warlock"), 1
        )
        temp = cha_mod + warlock_lvl
        if temp > 0:
            self.owner.add_temp_hp(temp)
            print(f"  {self.owner.name}: Dark One's Blessing — +{temp} temp HP!")


# ---------------------------------------------------------------------------
# Fiend lv6 — Dark One's Own Luck
# ---------------------------------------------------------------------------

class DarkOnesOwnLuck(Feature):
    """
    Once per rest: add a d10 to one ability check or saving throw.
    Hooks "saving_throw" and adds d10 to the bonus once.
    """
    name = "Dark One's Own Luck"
    EVENT_MAP = {"saving_throw": "on_saving_throw"}

    def __init__(self):
        super().__init__()
        self._available = True

    def on_saving_throw(self, ctx):
        if ctx.get("target") is not self.owner:
            return
        if not self._available:
            return
        roll = random.randint(1, 10)
        ctx["bonus"] = ctx.get("bonus", 0) + roll
        self._available = False
        print(f"  {self.owner.name}: Dark One's Own Luck +{roll}!")


# ---------------------------------------------------------------------------
# Fiend lv10 — Fiendish Resilience
# ---------------------------------------------------------------------------

class FiendishResilience(Feature):
    """
    Choose one damage type after a short or long rest.
    Gain resistance to that type. Default: fire.
    """
    name = "Fiendish Resilience"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        self._chosen = "fire"
        owner.resistances.add(self._chosen)
        print(f"  {owner.name}: Fiendish Resilience — resistance to {self._chosen}")


# ---------------------------------------------------------------------------
# Great Old One lv6 — Entropic Ward
# ---------------------------------------------------------------------------

class EntropicWard(Feature):
    """
    Reaction: when attacked, impose disadvantage on the roll.
    If the attack misses, regain one Pact Magic spell slot next turn.
    """
    name = "Entropic Ward"
    EVENT_MAP = {"attack": "on_attack"}

    def __init__(self):
        super().__init__()
        self._ward_used = False
        self._grant_slot_next_turn = False

    def attach(self, owner, bus):
        super().attach(owner, bus)
        bus.subscribe("TurnStarted", self._on_turn_started)
        self._subscriptions.append(("TurnStarted", self._on_turn_started))

    def _on_turn_started(self, ctx):
        if ctx.get("creature") is self.owner:
            self._ward_used = False
            if self._grant_slot_next_turn:
                self._grant_slot_next_turn = False
                pact = next((f for f in self.owner.features
                             if isinstance(f, PactMagic)), None)
                if pact and pact.slots_remaining < pact.max_slots:
                    pact.slots_remaining += 1
                    print(f"  {self.owner.name}: Entropic Ward — regained 1 Pact slot!")

    def on_attack(self, data):
        target = data.get("target")
        attack = data.get("attack")
        if target is not self.owner or not attack:
            return
        if self._ward_used:
            return
        if not self._owner_can_react():
            return
        if not self.owner.actions.use_reaction():
            return
        self._ward_used = True
        attack.disadvantage = True
        print(f"  {self.owner.name}: Entropic Ward — disadvantage on incoming attack!")

        # Register callback to check if it misses
        original_result = attack.result
        # We check after resolution via attack_resolved
        self.bus.subscribe("attack_resolved", self._check_miss)
        self._subscriptions.append(("attack_resolved", self._check_miss))
        self._watching_attack = attack

    def _check_miss(self, data):
        attack = data.get("attack")
        if attack is not getattr(self, "_watching_attack", None):
            return
        self.bus.unsubscribe("attack_resolved", self._check_miss)
        try:
            self._subscriptions.remove(("attack_resolved", self._check_miss))
        except ValueError:
            pass
        if not attack.result.get("hit", True):
            self._grant_slot_next_turn = True


# ---------------------------------------------------------------------------
# Great Old One lv10 — Thought Shield
# ---------------------------------------------------------------------------

class ThoughtShield(Feature):
    """Resistance to psychic damage."""
    name = "Thought Shield"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.resistances.add("psychic")
        print(f"  {owner.name}: Thought Shield — resistance to psychic damage")


# ---------------------------------------------------------------------------
# Stubs for non-combat / unimplemented features
# ---------------------------------------------------------------------------

class OtherworldlyPatron(Feature):
    name = "Otherworldly Patron"

class PactBoon(Feature):
    name = "Pact Boon"

class MysticArcanum6(Feature):
    name = "Mystic Arcanum (6)"

class MysticArcanum7(Feature):
    name = "Mystic Arcanum (7)"

class MysticArcanum8(Feature):
    name = "Mystic Arcanum (8)"

class MysticArcanum9(Feature):
    name = "Mystic Arcanum (9)"

class EldrithcMaster(Feature):
    name = "Eldritch Master"

class AwakenedMind(Feature):
    name = "Awakened Mind"

class CreateThrall(Feature):
    name = "Create Thrall"

class HurlThroughHell(Feature):
    name = "Hurl Through Hell"

class EldrlichInvocation(Feature):
    """Generic stub — individual invocations are separate features."""
    name = "Eldritch Invocation"

class ArmorOfShadows(Feature):
    name = "Armor of Shadows"

class DevilsSight(Feature):
    name = "Devil's Sight"

class EldrichSight(Feature):
    name = "Eldritch Sight"

class FiendishVigor(Feature):
    name = "Fiendish Vigor"

class GazeOfTwoMinds(Feature):
    name = "Gaze of Two Minds"

class MaskOfManyFaces(Feature):
    name = "Mask of Many Faces"

class MistyVisions(Feature):
    name = "Misty Visions"

class ThiefOfFiveFates(Feature):
    name = "Thief of Five Fates"

class VoiceOfTheChainMaster(Feature):
    name = "Voice of the Chain Master"
