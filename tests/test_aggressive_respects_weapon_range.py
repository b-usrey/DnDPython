"""
Regression test for AGGRESSIVE strategy's movement choice in
core/tactical_ai.py's plan_turn().

Bug: AGGRESSIVE used to unconditionally call _melee_move(), even when
_pick_weapon() had already chosen a ranged weapon -- forcing a ranged
attacker to close to melee range it didn't need to give up. This is a
real reason a selector-driven policy that leans on AGGRESSIVE (as ours
does) could underperform the plain "no selector" default, which already
branches on weapon.is_ranged. Fixed to mirror that same branch.

Builds a real minimal combat (ScenarioLoader + BattleMap + CombatManager)
rather than mocking plan_turn's many collaborators individually, matching
tests/test_disengage_safety_net.py's approach.
"""
import io
import contextlib

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from core.ml_strategy import Strategy, StrategySelector
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


def _make_scenario(hero_items, hero_equipped):
    return {
        "name": "AGGRESSIVE weapon-range test",
        "max_rounds": 5,
        "map": {"width": 20, "height": 10, "walls": [], "difficult_terrain": []},
        "positions": {
            "Hero":  [2, 5],
            "Buddy": [3, 5],
            "monsters": [[15, 5]],   # far away -- melee vs ranged movement clearly differ
        },
        "players": [
            {
                "name": "Hero",
                "classes": [["Fighter", 5]],
                "subclasses": {},
                "stats": {"Str": 16, "Dex": 16, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
                "choices": [],
                "items": hero_items,
                "equipped": hero_equipped,
                "features": [],
            },
            {
                "name": "Buddy",
                "classes": [["Fighter", 5]],
                "subclasses": {},
                "stats": {"Str": 16, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
                "choices": [],
                "items": ["Longsword"],
                "equipped": ["Longsword"],
                "features": [],
            },
        ],
        "monsters": [{"type": "GOBLIN", "count": 1, "weapon_role": "melee"}],
    }


class _FixedStrategySelector(StrategySelector):
    def __init__(self, strategy):
        super().__init__()
        self._strategy = strategy

    def select(self, obs):
        self.tactic_counts[self._strategy] += 1
        return self._strategy


def make_combat(hero_items, hero_equipped):
    scenario = _make_scenario(hero_items, hero_equipped)
    event   = EventBus()
    factory = CreatureFactory()
    loader  = ScenarioLoader(factory, event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(scenario)
        battle_map = build_map(scenario)
        place_creatures(scenario, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        cm = CombatManager(event, initiative, battle_map, mode=CombatMode.AUTO)
    hero = next(p for p in players if p.name == "Hero")
    return cm, hero


class TestAggressiveRespectsWeaponRange:
    def test_ranged_weapon_uses_ranged_move(self, monkeypatch):
        cm, hero = make_combat(["Longbow"], ["Longbow"])
        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team

        calls = []
        orig_ranged = type(cm.ai)._ranged_move
        orig_melee  = type(cm.ai)._melee_move
        monkeypatch.setattr(type(cm.ai), "_ranged_move",
                             lambda self, *a, **k: (calls.append("ranged"), orig_ranged(self, *a, **k))[1])
        monkeypatch.setattr(type(cm.ai), "_melee_move",
                             lambda self, *a, **k: (calls.append("melee"), orig_melee(self, *a, **k))[1])

        cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert "ranged" in calls
        assert "melee" not in calls

    def test_melee_weapon_uses_melee_move(self, monkeypatch):
        cm, hero = make_combat(["Longsword"], ["Longsword"])
        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team

        calls = []
        orig_ranged = type(cm.ai)._ranged_move
        orig_melee  = type(cm.ai)._melee_move
        monkeypatch.setattr(type(cm.ai), "_ranged_move",
                             lambda self, *a, **k: (calls.append("ranged"), orig_ranged(self, *a, **k))[1])
        monkeypatch.setattr(type(cm.ai), "_melee_move",
                             lambda self, *a, **k: (calls.append("melee"), orig_melee(self, *a, **k))[1])

        cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert "melee" in calls
        assert "ranged" not in calls
