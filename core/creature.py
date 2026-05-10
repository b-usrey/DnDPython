import itertools
import random

from core.actionTracker import ActionTracker
from core.statBlock import StatBlock
from core.attack import WeaponAttack
from core.item import Item
from data.features.base import Feature


class Creature:
    """
    Base class for every combatant in an encounter.

    Responsibilities:
      - Identity (name, ID, team)
      - Stats and derived modifiers (via StatBlock)
      - HP tracking: current, max, temp — including take_damage() and heal()
      - Conditions (as a plain set of strings for now)
      - Inventory and equipment slots
      - Initiative rolling
      - Action economy (via ActionTracker)
      - Feature registration and event attachment
      - Performing attacks (declare + resolve damage onto target)

    Not responsible for:
      - Turn/round orchestration (InitiativeManager)
      - Encounter loop (CombatManager)
      - Class features / spell slots (PlayerCharacter subclass)
    """

    _id_counter = itertools.count(1)

    def __init__(self, name, hp, ac, stats, event_manager, proficiency=2):
        # ── Identity ──────────────────────────────────────────────────────
        self.ID = next(Creature._id_counter)
        self.name = name
        self.team = "red"

        # ── Stats ─────────────────────────────────────────────────────────
        self.statblock = StatBlock(stats, proficiency)
        self.proficiency = proficiency

        # ── Hit points ────────────────────────────────────────────────────
        self._max_hp = hp
        self._current_hp = hp
        self._temp_hp = 0

        # ── AC — split into three independent components ──────────────────
        # _armour_ac : base AC from body armour (or flat template value for monsters)
        # _shield_ac : shield bonus (can change mid-combat)
        # _misc_ac   : rings, spells, features (accumulates additively)
        # self.ac is always kept in sync via compute_ac()
        self._armour_ac: int = ac
        self._shield_ac: int = 0
        self._misc_ac:   int = 0
        self.ac: int         = ac

        # ── Conditions (strings e.g. "prone", "poisoned") ─────────────────
        self.conditions = set()

        # ── Inventory & equipment ─────────────────────────────────────────
        self.inventory = []
        self.equipped_items = []
        self.equipped_slots = {
            "armor": None,
            "hand1": None,
            "hand2": None,
            "Ring": [],
            "Boots": None,
            "Cloak": None,
            "Bracers": None,
        }

        # ── Combat ────────────────────────────────────────────────────────
        self.actions = ActionTracker()
        self.initiative_mod = 0
        self.initiative_advantage = False
        self.initiative_roll = None
        self.concentration  = None   # name of active concentration effect
        self._conc_feature  = None   # Feature to notify if concentration breaks
        self.speed = 30

        # ── Features & events ────────────────────────────────────────────
        self.features = []
        self.event_manager = event_manager
        self.event_manager.subscribe("damage", self._on_damage_event)
        self.event_manager.subscribe("attack", self._on_attack_event)

    # ── HP properties ─────────────────────────────────────────────────────

    @property
    def hp(self):
        return self._current_hp

    @hp.setter
    def hp(self, value):
        """Direct assignment kept for legacy compatibility — prefer take_damage/heal."""
        self._current_hp = max(0, value)

    @property
    def max_hp(self):
        return self._max_hp

    def is_alive(self):
        return self._current_hp > 0

    # ── AC helpers ────────────────────────────────────────────────────────

    def compute_ac(self) -> None:
        """Recompute self.ac from the three stored components."""
        self.ac = self._armour_ac + self._shield_ac + self._misc_ac

    def apply_misc_ac(self, delta: int) -> None:
        """
        Add delta to the miscellaneous AC pool and recompute.
        Called by features: Ring of Protection (+1), Shield spell (+5), etc.
        Use a negative delta to remove a bonus when the effect ends.
        """
        self._misc_ac += delta
        self.compute_ac()

    def apply_shield(self, bonus: int) -> None:
        """
        Set the shield AC bonus and recompute.
        Pass 0 to remove (e.g. shield dropped or Shield spell expired).
        """
        self._shield_ac = bonus
        self.compute_ac()

    def take_damage(self, amount, damage_type=None):
        """
        Apply damage to this creature.

        Temp HP absorbs first, then current HP. Broadcasts
        'creature_downed' if HP reaches 0.

        If the creature is concentrating on a spell or feature, triggers
        a CON saving throw (DC = max(10, damage // 2)). On failure,
        concentration is broken.

        Returns actual damage dealt.
        """
        if amount <= 0:
            return 0

        # Temp HP absorbs first
        absorbed  = min(self._temp_hp, amount)
        self._temp_hp -= absorbed
        remaining = amount - absorbed

        was_alive = self._current_hp > 0
        self._current_hp = max(0, self._current_hp - remaining)

        if was_alive and self._current_hp == 0:
            self._on_downed()
        elif remaining > 0 and self._current_hp > 0 and self.concentration:
            # Concentration check — only if damage actually reached HP
            self._concentration_check(remaining)

        return amount

    def _concentration_check(self, damage: int) -> None:
        """
        Roll a CON save to maintain concentration after taking damage.
        DC = max(10, damage // 2).  Called automatically by take_damage.
        """
        from core.saving_throw import SavingThrow, DamageOnSave
        dc = max(10, damage // 2)
        print(f"  {self.name} concentration check (DC {dc}) — "
              f"concentrating on {self.concentration}")
        result = SavingThrow.roll(
            caster      = self,
            target      = self,
            ability     = "Con",
            dc          = dc,
            on_save     = DamageOnSave.NONE,
        )
        if not result.success:
            print(f"  {self.name} loses concentration on {self.concentration}!")
            self.break_concentration()

    # ── Concentration management ──────────────────────────────────────────

    def start_concentration(self, name: str, feature=None) -> None:
        """
        Begin concentrating on an effect.

        If already concentrating on something else, that effect is broken
        first (a creature can only concentrate on one thing at a time).

        Args:
            name:    display name of the effect, e.g. "Favored Foe"
            feature: optional Feature instance that will receive
                     on_concentration_broken() if concentration drops
        """
        if self.concentration and self.concentration != name:
            self.break_concentration()
        self.concentration  = name
        self._conc_feature  = feature

    def break_concentration(self) -> None:
        """
        Drop concentration, notifying the feature if one was registered.
        Safe to call even when not concentrating.
        """
        if not self.concentration:
            return
        feat = getattr(self, "_conc_feature", None)
        if feat and hasattr(feat, "on_concentration_broken"):
            feat.on_concentration_broken()
        self.concentration = None
        self._conc_feature = None

    def heal(self, amount):
        """Restore HP up to max. Returns amount actually healed."""
        if amount <= 0:
            return 0
        before = self._current_hp
        self._current_hp = min(self._max_hp, self._current_hp + amount)
        healed = self._current_hp - before
        if healed > 0:
            self.conditions.discard("unconscious")
        return healed

    def add_temp_hp(self, amount):
        """Temp HP doesn't stack — take the higher value (PHB p.198)."""
        self._temp_hp = max(self._temp_hp, amount)

    def _on_downed(self):
        """
        Called when HP reaches 0. Base behaviour: add unconscious condition
        and broadcast 'creature_downed'. PlayerCharacter overrides this
        to start death saving throws instead.
        """
        self.conditions.add("unconscious")
        self.event_manager.broadcast("creature_downed", {"creature": self})
        print(f"{self.name} has been downed!")

    # ── Damage event listener ─────────────────────────────────────────────

    def _on_attack_event(self, data):
        """
        Apply advantage/disadvantage from invisible conditions.
        Invisible attacker → advantage. Invisible target → disadvantage.
        Both cancel out per 5e rules (handled in roll_to_hit).
        """
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attack:
            return
        if attacker is self and self.has_condition("invisible"):
            attack.advantage = True
        if target is self and self.has_condition("invisible"):
            attack.disadvantage = True
        # Dodge action: attacks against a dodging creature have disadvantage
        # (PHB p.192). The condition is removed at the start of the
        # dodging creature's next turn via start_turn().
        if target is self and self.has_condition("dodging"):
            attack.disadvantage = True
        # Prone: attacker has disadvantage; melee vs prone = advantage,
        # ranged vs prone = disadvantage (PHB p.292)
        if attacker is self and self.has_condition("prone"):
            attack.disadvantage = True
        if target is self and self.has_condition("prone"):
            if getattr(attack, "range", False):
                attack.disadvantage = True
            else:
                attack.advantage = True
        # Restrained: attacker has disadvantage, attacks against target
        # have advantage (PHB p.292)
        if attacker is self and self.has_condition("restrained"):
            attack.disadvantage = True
        if target is self and self.has_condition("restrained"):
            attack.advantage = True

    def _on_damage_event(self, data):
        """
        Subscribed to the 'damage' event. Applies resolved damage from an
        Attack to this creature if we are the target.
        """
        if data.get("target") is not self:
            return
        attack = data.get("attack")
        if attack is None:
            return
        damage = attack.result.get("damage")
        if damage is None:
            damage = attack.roll_damage()
        if damage and damage > 0:
            print(f"{self.name} takes {damage} damage!")
            self.take_damage(damage)
            print(f"  ({self._current_hp}/{self._max_hp} HP remaining)")

    # ── Conditions ────────────────────────────────────────────────────────

    def add_condition(self, condition):
        self.conditions.add(condition.lower())

    def remove_condition(self, condition):
        self.conditions.discard(condition.lower())

    def has_condition(self, condition):
        return condition.lower() in self.conditions

    # ── Inventory & equipment ─────────────────────────────────────────────

    def get_item(self, item_name):
        for item in self.inventory:
            if item.name.lower() == item_name.lower():
                return item
        return None

    def add_item(self, item):
        self.inventory.append(item)

    def _get_equipped_by_name(self, item_name):
        for item in self.equipped_items:
            if item.name == item_name:
                return item
        print(f"Couldn't find '{item_name}' in equipped items")
        return None

    def equip_item(self, item_name):
        item = next(
            (i for i in self.inventory if i.name.lower() == item_name.lower()), None
        )
        if not item:
            print(f"{self.name} doesn't have '{item_name}' in inventory")
            return

        if item.item_type in ("weapon", "shield"):
            is_two_handed = hasattr(item, "properties") and "two-handed" in item.properties
            if is_two_handed:
                if not self.equipped_slots["hand1"] and not self.equipped_slots["hand2"]:
                    self.equipped_slots["hand1"] = item.name
                    self.equipped_slots["hand2"] = item.name
                    self.equipped_items.append(item)
                else:
                    print(f"Can't equip {item.name}: need two free hands")
            else:
                if not self.equipped_slots["hand1"]:
                    self.equipped_slots["hand1"] = item.name
                    self.equipped_items.append(item)
                elif not self.equipped_slots["hand2"]:
                    self.equipped_slots["hand2"] = item.name
                    self.equipped_items.append(item)
                else:
                    print(f"Can't equip {item.name}: no free hand")

        elif item.item_type == "armor":
            if not self.equipped_slots["armor"]:
                self.equipped_slots["armor"] = item.name
                self.equipped_items.append(item)
            else:
                print(f"Can't equip {item.name}: already wearing armor")

        elif item.item_type == "trinket":
            slot = getattr(item, "item_slot", None)
            if slot and not self.equipped_slots.get(slot):
                self.equipped_slots[slot] = item.name
                self.equipped_items.append(item)

        # Attach any feature the item grants
        if hasattr(item, "feature"):
            self._add_feature_by_name(item.name)

    # ── Features ──────────────────────────────────────────────────────────

    def _add_feature_by_name(self, name):
        if name in Feature.REGISTRY:
            feature_class = Feature.REGISTRY[name]
            feature = feature_class()
            self.features.append(feature)
            feature.attach(self, self.event_manager)
        else:
            print(f"[warn] Feature '{name}' not found in registry")

    # ── Initiative ────────────────────────────────────────────────────────

    def roll_initiative(self):
        roll1 = random.randint(1, 20) + self.statblock.mod("Dex") + self.initiative_mod
        if self.initiative_advantage:
            roll2 = random.randint(1, 20) + self.statblock.mod("Dex") + self.initiative_mod
            self.initiative_roll = max(roll1, roll2)
        else:
            self.initiative_roll = roll1
        return self.initiative_roll

    # ── Turn lifecycle ────────────────────────────────────────────────────

    def start_turn(self):
        self.actions.reset()
        # Dodge effect expires at the start of the creature's next turn
        self.remove_condition("dodging")

    # ── Attacks ───────────────────────────────────────────────────────────

    def perform_attack(self, target, item=None):
        """
        Declare and resolve an attack against target.
        Damage is applied to target.hp via the 'damage' event.
        """
        if item is not None and not isinstance(item, Item):
            item = self._get_equipped_by_name(item)

        attack = WeaponAttack(self, target, "1d8", item=item)
        attack.declare_attack()
        return attack

    # ── Dunder helpers ────────────────────────────────────────────────────

    def __repr__(self):
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"hp={self._current_hp}/{self._max_hp} ac={self.ac}>"
        )

    def __str__(self):
        conds = ", ".join(self.conditions) if self.conditions else "none"
        return (
            f"{self.name}  HP: {self._current_hp}/{self._max_hp}"
            f"  (temp: {self._temp_hp})  AC: {self.ac}  Conditions: {conds}"
        )