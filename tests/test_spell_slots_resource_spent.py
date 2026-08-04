"""
Tests for Spellcasting.spend_slot()'s resource_spent broadcast
(data/features/spell_slots.py) -- part of the Tier-2 resource-tracking
instrumentation (see also Ki/Rage). Since spend_slot() is the single
shared choke point every spell-casting feature calls through, this one
hook instruments every spell in the engine for free.
"""
from types import SimpleNamespace

from core.events import EventBus
from data.features.spell_slots import Spellcasting


def make_caster():
    owner = SimpleNamespace(name="Lyra", event_manager=EventBus())
    slots = Spellcasting()
    slots.owner = owner
    slots._slots = {1: 4, 2: 3, 3: 2}
    return owner, slots


class TestSpendSlotResourceSpent:
    def test_broadcasts_on_successful_spend(self):
        owner, slots = make_caster()
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        lvl = slots.spend_slot(min_level=1)

        assert lvl == 1
        assert len(spent) == 1
        assert spent[0]["resource"] == "spell_slot_1"
        assert spent[0]["remaining"] == 3
        assert spent[0]["creature"] is owner

    def test_spends_lowest_available_slot_meeting_the_minimum(self):
        owner, slots = make_caster()
        slots._slots = {1: 0, 2: 3, 3: 2}
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        lvl = slots.spend_slot(min_level=1)

        assert lvl == 2
        assert spent[0]["resource"] == "spell_slot_2"
        assert spent[0]["remaining"] == 2

    def test_no_broadcast_when_no_slot_available(self):
        owner, slots = make_caster()
        slots._slots = {1: 0, 2: 0, 3: 0}
        spent = []
        owner.event_manager.subscribe("resource_spent", lambda data: spent.append(data))

        lvl = slots.spend_slot(min_level=1)

        assert lvl is None
        assert spent == []

    def test_no_crash_when_owner_not_yet_attached(self):
        slots = Spellcasting()
        slots.owner = None
        slots._slots = {1: 4}
        assert slots.spend_slot(min_level=1) == 1
