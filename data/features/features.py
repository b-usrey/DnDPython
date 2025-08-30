from core.attack import WeaponAttack
from core.events import EventBus
from pdb import set_trace as S
class Feature:
    REGISTRY = {}
    EVENT_MAP = {}  # event_name -> handler method name

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        Feature.REGISTRY[getattr(cls, "name", cls.__name__)] = cls

    def __init__(self, owner=None, name=None):
        self.name = name or self.__class__.__name__
        self.owner = owner
        self.bus = None
        self._subscriptions = []  # track (event, handler) for unsubscribe

    def attach(self, owner, bus):
        """Attach to a creature and subscribe to events."""
        self.owner = owner
        self.bus = bus
        self.subscribe(bus)

    def detach(self):
        """Remove all subscriptions."""
        if self.bus:
            self.unsubscribe(self.bus)
        self.owner = None
        self.bus = None

    def subscribe(self, bus):
        """Subscribe each handler in EVENT_MAP by passing the bound method."""
        for event, handler_name in self.EVENT_MAP.items():
            handler = getattr(self, handler_name, None)
            if handler:
                bus.subscribe(event, handler)       # pass method, not self
                self._subscriptions.append((event, handler))

    def unsubscribe(self, bus):
        """Unsubscribe all stored handlers."""
        for event, handler in self._subscriptions:
            bus.unsubscribe(event, handler)
        self._subscriptions.clear()

class Sharpshooter(Feature):
    name = "Sharpshooter"
    EVENT_MAP = {"attack": "on_attack","damage":"on_damage"}
    def on_attack(self, context):
        attack = context['attack']
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
            attack.tags.add("sharpshooter")

class Archery(Feature):
    name = "Archery"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, context):
        attack = context['attack']
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod += 2
            attack.tags.add("archery")
            


class DreadAmbusher(Feature):
    name = "Dread Ambusher"
    EVENT_MAP = {"turn_start": "on_turn_start", "attack": "on_attack", "damage": "on_damage"}

    def __init__(self):
        super().__init__()
        self.first_turn_active = True
        self.extra_attack_used = False

    def on_turn_start(self, ctx):
        creature, turn = ctx["creature"], ctx["turn_number"]
        if turn == 1:
            print(f"{creature.name} gains +10 movement from Dread Ambusher!")
            creature.speed += 10
            self.first_turn_active, self.extra_attack_used = True, False
        else:
            self.first_turn_active = False

    def on_attack(self, attack):
        attack = attack['attack']
        if self.first_turn_active and not self.extra_attack_used:
            attack.tags.add("dread_ambusher_bonus")
            self.extra_attack_used = True

    def on_damage(self, attack):
        if "dread_ambusher_bonus" in getattr(attack, "tags", []):
            if attack.result.get("hit", False):
                print("Dread Ambusher adds +1d8 damage!")
                attack.extra_damage_die.append((1, 8))


class FavoredFoe(Feature):
    EVENT_MAP = {
        "attack_roll": "on_attack_roll"
    }

    def on_attack_roll(self, context):
        if context["attacker"] == self.owner:
            context["bonus"] += 2
            print(f"{self.owner} applies Favored Foe! Bonus is now {context['bonus']}")



class BracersOfArchery(Feature):
    name = "Bracers Of Archery"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def on_attack_resolved(self, data):
        if data["attacker"] == self.owner and data.get("weapon") == "ranged":
            data["damage"] += 2
            print(f"{self.owner.name}'s Bracers add +2 damage!")

