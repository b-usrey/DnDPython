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

    # Ordinary creatures die outright at 0 HP (5e RAW for most monsters).
    # PlayerCharacter sets this True to fall unconscious and roll death
    # saving throws instead — see _start_dying()/roll_death_save().
    DEATH_SAVES = False

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

        # ── Death saving throws (only meaningful while DEATH_SAVES=True) ───
        self._dead                 = False
        self.death_save_successes  = 0
        self.death_save_failures   = 0

        # ── Damage resistances (set of damage type strings) ───────────────
        self.resistances: set = set()

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
        """
        True until the creature is truly dead. A creature at 0 HP with
        DEATH_SAVES=True (e.g. a downed PlayerCharacter) stays "alive" —
        unconscious and rolling death saves — until it dies or is healed.
        Ordinary creatures die the instant HP hits 0.
        """
        return not self._dead

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

    def take_damage(self, amount, damage_type=None, critical=False):
        """
        Apply damage to this creature.

        Temp HP absorbs first, then current HP. Broadcasts
        'creature_downed' if HP reaches 0.

        If the creature is concentrating on a spell or feature, triggers
        a CON saving throw (DC = max(10, damage // 2)). On failure,
        concentration is broken.

        If already dying (0 HP, DEATH_SAVES=True), damage doesn't reduce
        HP further — instead it's an automatic death save failure (two on
        a critical hit), or instant death if it's ≥ max HP in one hit.
        `critical` should be passed for weapon attacks; saving-throw
        damage never crits, so it defaults to False there.

        Returns actual damage dealt.
        """
        if amount <= 0:
            return 0

        if damage_type and damage_type.lower() in self.resistances:
            amount = max(1, amount // 2)

        if self.has_condition("dying"):
            self._damage_while_dying(amount, critical)
            return amount

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
        """
        Restore HP up to max. Returns amount actually healed.
        Healing a dying creature (even from 0 HP) wakes it up immediately
        and clears its death save progress. No-op on a truly dead creature
        — this sim has no resurrection magic.
        """
        if amount <= 0 or self._dead:
            return 0
        before = self._current_hp
        self._current_hp = min(self._max_hp, self._current_hp + amount)
        healed = self._current_hp - before
        if healed > 0:
            self.conditions.discard("unconscious")
            if self.has_condition("dying"):
                self.conditions.discard("dying")
                self.death_save_successes = 0
                self.death_save_failures  = 0
                print(f"  {self.name} is healed back to consciousness!")
        return healed

    def add_temp_hp(self, amount):
        """Temp HP doesn't stack — take the higher value (PHB p.198)."""
        self._temp_hp = max(self._temp_hp, amount)

    def _on_downed(self):
        """
        Called when HP reaches 0. Ordinary creatures die outright. Creatures
        with DEATH_SAVES=True (PlayerCharacter) fall unconscious and start
        rolling death saving throws instead.

        Either way, dropping to 0 HP always ends concentration — an
        unconscious or dead creature can't sustain it (unlike a failed
        concentration save from non-lethal damage, which only breaks it
        on a failure).
        """
        self.break_concentration()
        if self.DEATH_SAVES:
            self._start_dying()
            return
        self.conditions.add("unconscious")
        self.conditions.add("dead")
        self._dead = True
        self.event_manager.broadcast("creature_downed", {"creature": self})
        print(f"{self.name} has been downed!")

    # ── Death saving throws ─────────────────────────────────────────────────

    def _start_dying(self):
        """Enter the dying state: unconscious at 0 HP, rolling death saves."""
        self.conditions.add("unconscious")
        self.conditions.add("dying")
        self.death_save_successes = 0
        self.death_save_failures  = 0
        self.event_manager.broadcast("creature_downed", {"creature": self, "dying": True})
        print(f"  {self.name} drops to 0 HP and is dying!")

    def _damage_while_dying(self, amount: int, critical: bool) -> None:
        """
        5e RAW: any hit while at 0 HP is an automatic death save failure
        (two on a critical hit). Damage that would equal or exceed max HP
        in one hit kills outright, bypassing any remaining death saves.
        """
        if amount >= self._max_hp:
            print(f"  {self.name} suffers massive damage and dies instantly!")
            self._true_death()
            return
        fails = 2 if critical else 1
        print(f"  {self.name} is hit while dying — "
              f"{fails} automatic death save failure{'s' if fails > 1 else ''}!")
        self._register_death_save_failure(fails)

    def _register_death_save_failure(self, count: int = 1) -> None:
        self.death_save_failures += count
        if self.death_save_failures >= 3:
            self._true_death()

    def _true_death(self) -> None:
        self.conditions.discard("dying")
        self.conditions.discard("unconscious")
        self.conditions.add("dead")
        self._dead = True
        print(f"{self.name} has died.")
        self.event_manager.broadcast("creature_died", {"creature": self})

    def roll_death_save(self) -> None:
        """
        Roll a flat, unmodified d20 death saving throw (PHB p.197).
        Natural 20: regain 1 HP and wake up. Natural 1: two failures.
        10+: success. Below 10: failure. Three successes stabilises the
        creature (still unconscious, stops rolling). Three failures kills it.
        No-op if the creature isn't currently dying.
        """
        if not self.has_condition("dying"):
            return

        d20 = random.randint(1, 20)
        print(f"  {self.name} rolls a death saving throw: {d20}")

        if d20 == 20:
            self.death_save_successes = 0
            self.death_save_failures  = 0
            self.conditions.discard("dying")
            self.conditions.discard("unconscious")
            self._current_hp = 1
            print(f"  {self.name} rolls a natural 20 — regains 1 HP and wakes up!")
            self.event_manager.broadcast(
                "creature_stabilized", {"creature": self, "woke_up": True}
            )
            return

        if d20 == 1:
            self._register_death_save_failure(2)
        elif d20 >= 10:
            self.death_save_successes += 1
        else:
            self._register_death_save_failure(1)

        if not self.is_alive():
            return   # _true_death already fired and reported

        if self.death_save_successes >= 3:
            self.death_save_successes = 0
            self.death_save_failures  = 0
            self.conditions.discard("dying")
            print(f"  {self.name} is stable.")
            self.event_manager.broadcast(
                "creature_stabilized", {"creature": self, "woke_up": False}
            )
            return

        print(f"  {self.name}: {self.death_save_successes} successes, "
              f"{self.death_save_failures} failures")

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
        # Unconscious (including dying): attacks against it have advantage
        if target is self and self.has_condition("unconscious"):
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
            dmg_type = getattr(attack, "damage_type", None)
            print(f"{self.name} takes {damage} damage!")
            self.take_damage(
                damage, damage_type=dmg_type,
                critical=getattr(attack, "critical", False),
            )
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

    def _add_feature_by_name(self, name, homebrew_def=None):
        """
        Attach a feature by name. If homebrew_def is given, it's a
        validated homebrew definition (see data/features/homebrew.py) —
        used for a class JSON entry like {"name": "...", "homebrew": {...}}
        instead of a Feature.REGISTRY lookup. homebrew_def is expected to
        have already passed validate_homebrew_definition(); this re-checks
        defensively since a rejected definition should silently not attach
        rather than raise mid-character-build.
        """
        if homebrew_def is not None:
            from data.features.homebrew import HomebrewFeature, validate_homebrew_definition
            errors = validate_homebrew_definition(homebrew_def)
            if errors:
                print(f"[warn] Homebrew feature '{name}' rejected: {'; '.join(errors)}")
                return
            feature = HomebrewFeature(name, homebrew_def)
            self.features.append(feature)
            feature.attach(self, self.event_manager)
            return

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