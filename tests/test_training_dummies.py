"""
Tests for the training-dummy monster entries (data/monsters/monsters.py):
stationary, attack-less, very-high-HP targets used for isolating a single
character's damage output from party/counter-damage noise (TheDM's
dummy-tester page). Not real SRD monsters -- pure test fixtures.
"""
import io
import contextlib

import pytest

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from data.monsters.monsters import MONSTER_REGISTRY
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


DUMMY_KEYS_AND_ACS = [
    ("TRAINING_DUMMY_AC12", 12),
    ("TRAINING_DUMMY_AC15", 15),
    ("TRAINING_DUMMY_AC18", 18),
    ("TRAINING_DUMMY_AC21", 21),
]


class TestRegistryEntries:
    @pytest.mark.parametrize("key,ac", DUMMY_KEYS_AND_ACS)
    def test_registered_with_expected_ac(self, key, ac):
        assert key in MONSTER_REGISTRY
        assert MONSTER_REGISTRY[key]["ac"] == ac

    @pytest.mark.parametrize("key,ac", DUMMY_KEYS_AND_ACS)
    def test_has_no_attacks(self, key, ac):
        assert MONSTER_REGISTRY[key]["attacks"] == []

    @pytest.mark.parametrize("key,ac", DUMMY_KEYS_AND_ACS)
    def test_has_high_hp(self, key, ac):
        assert MONSTER_REGISTRY[key]["hp"] >= 500


class TestFactoryConstruction:
    def test_builds_without_crashing(self):
        factory = CreatureFactory()
        event = EventBus()
        dummy = factory.create(MONSTER_REGISTRY["TRAINING_DUMMY_AC15"], event)
        assert dummy.ac == 15
        assert dummy.hp == 500
        assert dummy.actions.extra_attacks == 0


SCENARIO = {
    "name": "Dummy tester",
    "max_rounds": 6,
    "map": {"width": 10, "height": 8, "walls": [], "difficult_terrain": []},
    "positions": {"Hero": [1, 3], "monsters": [[3, 3]]},
    "players": [
        {
            "name": "Hero",
            "classes": [["Fighter", 5]],
            "subclasses": {},
            "stats": {"Str": 16, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
            "choices": [],
            "items": ["Longsword"],
            "equipped": ["Longsword"],
            "features": [],
        },
    ],
    "monsters": [{"type": "TRAINING_DUMMY_AC15", "count": 1}],
}


def run_scenario():
    event = EventBus()
    factory = CreatureFactory()
    loader = ScenarioLoader(factory, event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(SCENARIO)
        battle_map = build_map(SCENARIO)
        place_creatures(SCENARIO, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        cm = CombatManager(event, initiative, battle_map, max_rounds=SCENARIO["max_rounds"])
        cm.run()
    return players, monsters


class TestDummyBehaviorInCombat:
    def test_dummy_never_acts_and_survives(self):
        players, monsters = run_scenario()
        dummy = monsters[0]
        hero = players[0]
        # Full 6-round window at 500 HP -- a single level-5 Fighter cannot
        # possibly kill it, and since it never attacks, the hero takes no
        # damage either.
        assert dummy.is_alive()
        assert dummy.hp < dummy.max_hp   # the hero did land some damage
        assert hero.hp == hero.max_hp    # dummy never landed a hit (it never attacks)

    def test_runs_full_max_rounds_since_dummy_never_dies_from_incidental_damage(self):
        players, monsters = run_scenario()
        # A handful of hits from one level-5 Fighter over 6 rounds should
        # be nowhere near 500 HP -- confirms the HP buffer is generous
        # enough for this to be a real "sustained damage" test window.
        assert monsters[0].hp > 400
