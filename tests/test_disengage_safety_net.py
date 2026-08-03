"""
Regression tests for the disengage-vs-strategy-selector interaction in
core/tactical_ai.py's plan_turn().

Bug: attaching any strategy selector (even a bad/undertrained one) used to
silently disable TacticalAI's rule-based low-HP disengage safety net
(_should_disengage) -- that path only ran when strategy was None. A
selector-controlled creature would only retreat if the policy itself
happened to pick RETREAT at exactly the right moment, so a policy that
rarely picks RETREAT would walk into death that "no selector at all"
would have automatically avoided.

Fix: the disengage check now runs unconditionally before consulting the
active strategy, and is skipped only when the strategy is already
RETREAT (since that reaches the same outcome through its own branch).

These tests build a real minimal combat (ScenarioLoader + BattleMap +
CombatManager) rather than mocking TacticalAI's many collaborators
(battle_map, TeamMemory, weapon profiles, etc.) individually.
"""
import io
import contextlib

import pytest

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from core.ml_strategy import Strategy, StrategySelector
from data.monsters.monsters import MONSTER_REGISTRY
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


SCENARIO = {
    "name": "Disengage safety net test",
    "max_rounds": 5,
    "map": {"width": 12, "height": 10, "walls": [], "difficult_terrain": []},
    "positions": {
        "Hero":  [2, 5],
        "Buddy": [3, 5],
        "monsters": [[8, 4], [8, 6]],
    },
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
    "monsters": [{"type": "GOBLIN", "count": 2, "weapon_role": "melee"}],
}


class _FixedStrategySelector(StrategySelector):
    """Always returns the same Strategy, regardless of state."""
    def __init__(self, strategy):
        super().__init__()
        self._strategy = strategy

    def select(self, obs):
        self.tactic_counts[self._strategy] += 1
        return self._strategy


def make_combat():
    event   = EventBus()
    factory = CreatureFactory()
    loader  = ScenarioLoader(factory, event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(SCENARIO)
        # ScenarioLoader doesn't wire monster attack templates -- main.py's
        # main() does that separately. Replicate the minimum needed so
        # monster TacticalAI calls find a weapon (_get_weapon_profiles).
        for m in monsters:
            m._attack_templates = MONSTER_REGISTRY[m.name.split("#")[0].upper()]["attacks"]
        battle_map = build_map(SCENARIO)
        place_creatures(SCENARIO, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        cm = CombatManager(event, initiative, battle_map, mode=CombatMode.AUTO)
    hero = next(p for p in players if p.name == "Hero")
    return cm, hero, monsters


class TestDisengageSafetyNet:
    def test_fires_despite_aggressive_selector_when_hp_low(self):
        cm, hero, _monsters = make_combat()
        hero.hp = hero.max_hp * 0.1   # well below the 25% threshold

        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team

        decision = cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert decision.reason == "disengaging — low HP"

    def test_fires_despite_protect_selector_when_hp_low(self):
        cm, hero, _monsters = make_combat()
        hero.hp = hero.max_hp * 0.1

        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.PROTECT)
        cm.ai.trained_team = hero.team

        decision = cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert decision.reason == "disengaging — low HP"

    def test_does_not_fire_when_hp_is_healthy(self):
        cm, hero, _monsters = make_combat()
        assert hero.hp == hero.max_hp   # untouched, well above threshold

        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team

        decision = cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert decision.reason != "disengaging — low HP"

    def test_retreat_strategy_takes_its_own_branch_not_the_duplicate(self):
        cm, hero, _monsters = make_combat()
        hero.hp = hero.max_hp * 0.1

        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.RETREAT)
        cm.ai.trained_team = hero.team

        decision = cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        # Reaches the same real-world outcome (retreating) via the
        # strategy's own RETREAT branch, not the safety-net duplicate.
        assert decision.reason == "strategy: RETREAT"

    def test_no_selector_still_disengages_as_before(self):
        cm, hero, _monsters = make_combat()
        hero.hp = hero.max_hp * 0.1
        cm.ai.strategy_selector = None
        cm.ai.trained_team = None

        decision = cm.ai.plan_turn(hero, cm.battle_map, memory=hero.team_memory)

        assert decision.reason == "disengaging — low HP"

    def test_selector_only_gated_to_trained_team_still_unaffected_for_others(self):
        """A selector scoped to 'blue' shouldn't change how the disengage
        safety net behaves for a 'red' creature it doesn't control."""
        cm, hero, monsters = make_combat()
        goblin = next(c for c in monsters if c.name.startswith("Goblin"))
        goblin.hp = goblin.max_hp * 0.1

        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team   # scoped to blue only, not the goblin's team

        decision = cm.ai.plan_turn(goblin, cm.battle_map, memory=goblin.team_memory)

        assert decision.reason == "disengaging — low HP"
