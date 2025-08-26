from core.attack import WeaponAttack
from pdb import set_trace as S
class Feature:
    """Base class for all character features with auto-registry and optional event subscription."""
    REGISTRY = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically register subclasses when defined."""
        super().__init_subclass__(**kwargs)
        # Register by class name (e.g. "Sharpshooter") 
        # and by the 'name' attribute if it exists
        if hasattr(cls, "name"):
            Feature.REGISTRY[cls.name] = cls
        Feature.REGISTRY[cls.__name__] = cls

    def __init__(self, name=None):
        self.name = name or self.__class__.__name__
        self.owner = None   # Creature this feature is attached to

    # ---------------------------
    # Attach/Detach to Creature
    # ---------------------------
    def attach(self, creature):
        """Attach to a creature and subscribe to events if needed."""
        self.owner = creature
        self.subscribe(creature.eventManager)

    def detach(self):
        """Detach from creature and unsubscribe from events."""
        if self.owner:
            self.unsubscribe(self.owner.eventManager)
            self.owner = None

    def subscribe(self, event_manager):
        """Override in subclasses to hook into creature events."""
        # Default: wire event manager back into legacy hook methods
        event_manager.subscribe("attack", self.on_attack)
        event_manager.subscribe("damage", self.on_damage)
        event_manager.subscribe("turn_start", self.on_turn_start)

    def unsubscribe(self, event_manager):
        """Unsubscribe from all events."""
        event_manager.unsubscribe("attack", self.on_attack)
        event_manager.unsubscribe("damage", self.on_damage)
        event_manager.unsubscribe("turn_start", self.on_turn_start)

    # ---------------------------
    # Legacy Hook API
    # ---------------------------
    def on_attack(self, attack):
        """Called when attack roll happens (default does nothing)."""
        pass

    def on_damage(self, attack):
        """Called when damage is calculated (default does nothing)."""
        pass

    def on_turn_start(self, context=None):
        """Called at the start of the character's turn (default does nothing)."""
        pass


class Sharpshooter(Feature):
    name = "Sharpshooter"

    def __init__(self):
        super().__init__(Sharpshooter.name)

    def on_attack(self, attack):
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
class Archery(Feature):
    name = "Archery"
    def __init__(self):
        super().__init__(Archery.name)
    def on_attack(self,attack):
        if isinstance(attack,WeaponAttack):
            attack.to_hit_mod += 2

class DreadAmbusher(Feature):
    name = "Dread Ambusher"
    def __init__(self):
        super().__init__(DreadAmbusher.name)
        self.first_turn_active = True
        self.extra_attack_used = False

    def on_turn_start(self, context):
        # context could include { "creature": Creature, "turn_number": int }
        creature = context.get("creature")
        turn_number = context.get("turn_number")

        if turn_number == 1:  # First turn only
            print(f"{creature.name} gains +10 movement from Dread Ambusher!")
            creature.speed += 10
            self.first_turn_active = True
            self.extra_attack_used = False
        else:
            self.first_turn_active = False

    def on_attack(self, attack):
        """
        Triggered whenever the creature makes an attack.
        Attack object could carry metadata like 'is_bonus_attack'.
        """
        if not isinstance(attack, WeaponAttack):
            return

        if self.first_turn_active and not self.extra_attack_used:
            # Flag this attack as the Dread Ambusher bonus attack
            #attack.tags.add("dread_ambusher_bonus")
            self.extra_attack_used = True

    def on_damage(self, attack):
        """
        Add 1d8 damage if the flagged bonus attack hits.
        """
        if "dread_ambusher_bonus" in getattr(attack, "tags", []):
            if attack.result.get("hit", False):
                print("Dread Ambusher adds +1d8 damage!")
                attack.extra_damage_die.append((1, 8))     
class FavoredFoe(Feature):
    name = "Favored Foe"

    def __init__(self, diceType="d6"):
        super().__init__(FavoredFoe.name)
        self.diceType = diceType
        self.used_this_turn = False
        self.marked_target = None

    def mark_target(self, target):
        self.marked_target = target

    def on_damage(self, attack):
        if (
            attack.target == self.marked_target
            and not self.used_this_turn
            and attack.result.get("hit", False)
        ):
            # Append tuple: (num dice, die size)
            attack.extra_damage_die.append((1, 6))
            self.used_this_turn = True

    def on_turn_start(self, context=None):
        self.used_this_turn = False

class BracersOfArchery(Feature):
    name = "Bracers Of Archery"

    def __init__(self):
        super().__init__(BracersOfArchery.name)

    def subscribe(self, event_manager):
        """
        Subscribe only to the events we care about.
        In this case, damage resolution for ranged attacks.
        """
        event_manager.subscribe("AttackResolved", self.notify)

    def unsubscribe(self, event_manager):
        event_manager.unsubscribe("AttackResolved", self.notify)

    def notify(self, data):
        """
        Called whenever an event we're subscribed to is broadcast.
        Expects data dict with keys:
          - 'attacker': Creature
          - 'target': Creature
          - 'weapon': str
          - 'damage': int
        """
        # Only apply bonus if this creature is attacking
        if data.get("attacker") != self.owner:
            return

        # Only for ranged weapon attacks
        if data.get("weapon") == "ranged":
            data["damage"] += 2
            print(f"{self.owner.name}'s Bracers of Archery add +2 damage!")
