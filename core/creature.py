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
        self.ac = ac

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
        self.concentration = None
        self.speed = 30

        # ── Features & events ────────────────────────────────────────────
        self.features = []
        self.event_manager = event_manager
        self.event_manager.subscribe("damage", self._on_damage_event)

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

    def take_damage(self, amount, damage_type=None):
        """
        Apply damage to this creature.

        Temp HP absorbs first, then current HP. Broadcasts
        'creature_downed' if HP reaches 0. Returns actual damage dealt.
        """
        if amount <= 0:
            return 0

        # Temp HP absorbs first
        absorbed = min(self._temp_hp, amount)
        self._temp_hp -= absorbed
        remaining = amount - absorbed

        self._current_hp = max(0, self._current_hp - remaining)

        if self._current_hp == 0:
            self._on_downed()

        return amount

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
            self.take_damage(damage)
            print(f"{self.name} takes {damage} damage! ({self._current_hp}/{self._max_hp} HP remaining)")

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
            print(f"⚠ Feature '{name}' not found in registry")

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