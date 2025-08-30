from core.attack import WeaponAttack
from core.events import EventBus
from pdb import set_trace as S
'''
attack
damage
attack_resolved
turn_start
turn_end
bonus_action
reaction
movement
condition_applied
condition_removed
spell_cast
healing
'''

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




