"""
Tests for Rage's resource_spent broadcast (data/features/barbarian_features.py).

Part of the same Tier-2 resource-tracking instrumentation as Ki's Flurry
of Blows/Stunning Strike and Spellcasting.spend_slot() -- lets the
character analyzer build a per-character resource timeline (e.g. "Rage
ran out by round 4 in most fights") from the structured combat log.
"""
from types import SimpleNamespace

from core.actionTracker import ActionTracker
from core.events import EventBus
from data.features.barbarian_features import Rage


def make_owner(barb_level=3):
    owner = SimpleNamespace(
        name="Ragnar",
        classes=[("Barbarian", barb_level)],
        actions=ActionTracker(),
        resistances=set(),
        event_manager=EventBus(),
    )
    return owner


class TestRageResourceSpent:
    def test_broadcasts_on_entering_rage(self):
        owner = make_owner(barb_level=3)
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        rage = Rage()
        rage.attach(owner, EventBus())
        rage.on_turn_started({"creature": owner})

        assert len(spent) == 1
        assert spent[0]["resource"] == "rage"
        assert spent[0]["remaining"] == 2   # lv3 -> 3 uses, minus this one
        assert spent[0]["creature"] is owner

    def test_does_not_broadcast_when_already_raging(self):
        owner = make_owner(barb_level=3)
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        rage = Rage()
        rage.attach(owner, EventBus())
        rage.on_turn_started({"creature": owner})   # enters rage, 1 broadcast
        owner.actions.reset()
        rage.on_turn_started({"creature": owner})   # already raging -- no-op

        assert len(spent) == 1

    def test_does_not_broadcast_when_out_of_uses(self):
        owner = make_owner(barb_level=3)
        rage = Rage()
        rage.attach(owner, EventBus())
        rage._uses_remaining = 0
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        rage.on_turn_started({"creature": owner})

        assert spent == []
