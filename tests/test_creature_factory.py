"""
Tests for CreatureFactory's multiattack wiring (utils/creatureFactory.py):
  - a monster template's "multiattack" count becomes extra_attacks on the
    creature's ActionTracker, reusing the same mechanism PCs get from the
    Extra Attack feature
  - defaults to no multiattack (extra_attacks=0) when the field is absent,
    for backward compatibility with any template that doesn't specify it
"""
from core.events import EventBus
from utils.creatureFactory import CreatureFactory


def make_template(name="TestMonster", multiattack=None):
    template = {
        "name": name,
        "hp": 20,
        "ac": 13,
        "stats": {"Str": 12, "Dex": 12, "Con": 12, "Int": 10, "Wis": 10, "Cha": 10},
        "attacks": [{"name": "Claw", "attack_type": "melee", "attack_bonus": 3,
                     "damage_die": 6, "damage_mod": 1}],
    }
    if multiattack is not None:
        template["multiattack"] = multiattack
    return template


class TestMultiattackWiring:
    def test_defaults_to_no_multiattack_when_field_absent(self):
        factory = CreatureFactory()
        creature = factory.create(make_template(), EventBus())
        assert creature.actions.extra_attacks == 0
        assert creature.actions.remaining_extra_attacks == 0

    def test_multiattack_1_means_no_extra_attacks(self):
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=1), EventBus())
        assert creature.actions.extra_attacks == 0

    def test_multiattack_2_grants_one_extra_attack(self):
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=2), EventBus())
        assert creature.actions.extra_attacks == 1
        assert creature.actions.remaining_extra_attacks == 1

    def test_multiattack_3_grants_two_extra_attacks(self):
        """Matches a dragon's 'makes three attacks'."""
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=3), EventBus())
        assert creature.actions.extra_attacks == 2
        assert creature.actions.remaining_extra_attacks == 2

    def test_extra_attacks_survive_a_turn_reset(self):
        """The pool must still be there on later turns, not just turn 1."""
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=3), EventBus())
        creature.actions.remaining_extra_attacks = 0   # simulate having spent them
        creature.start_turn()
        assert creature.actions.remaining_extra_attacks == 2

    def test_use_extra_attack_can_be_called_exactly_multiattack_minus_one_times(self):
        """Exercises the actual consumption loop CombatManager._do_attack_action
        uses, end to end, for a multiattack monster."""
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=3), EventBus())
        fired = 0
        while creature.actions.use_extra_attack():
            fired += 1
        assert fired == 2

    def test_unrelated_templates_are_unaffected(self):
        """A totally ordinary 1-attack monster still behaves exactly as before."""
        factory = CreatureFactory()
        creature = factory.create(make_template(multiattack=1), EventBus())
        assert creature.actions.use_extra_attack() is False
