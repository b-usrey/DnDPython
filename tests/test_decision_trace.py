"""
Tests for TacticalAI's decision tracing (core/tactical_ai.py) and the
"decision" records CombatLogger writes from it.

The point of the trace is to record the options that were *rejected*
alongside the one that won -- "why did the goblin shoot instead of
charge" is only answerable if the losing scores survive. These tests
cover that the candidate tables are populated, that tracing stays off
unless asked for, and -- most importantly -- that turning it on cannot
change what the AI actually decides.
"""
import io
import contextlib
import random

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from core.ml_strategy import Strategy, StrategySelector
from data.monsters.monsters import MONSTER_REGISTRY
from utils.combat_logger import CombatLogger
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


SCENARIO = {
    "name": "Decision trace test",
    "max_rounds": 5,
    "map": {"width": 14, "height": 10, "walls": [], "difficult_terrain": []},
    "positions": {"Hero": [2, 5], "monsters": [[9, 4], [9, 6]]},
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
    # weapon_role "all" gives each goblin both a Scimitar and a Shortbow, so
    # the weapon stage has a real choice to make and to report on.
    "monsters": [{"type": "GOBLIN", "count": 2, "weapon_role": "all"}],
}


def make_combat():
    event   = EventBus()
    factory = CreatureFactory()
    loader  = ScenarioLoader(factory, event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(SCENARIO)
        for m in monsters:
            m._attack_templates = MONSTER_REGISTRY[m.name.split("#")[0].upper()]["attacks"]
        battle_map = build_map(SCENARIO)
        place_creatures(SCENARIO, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        cm = CombatManager(event, initiative, battle_map, mode=CombatMode.AUTO)
    hero = next(p for p in players if p.name == "Hero")
    return cm, event, hero, monsters


def plan(cm, creature):
    with contextlib.redirect_stdout(io.StringIO()):
        return cm.ai.plan_turn(creature, cm.battle_map, memory=creature.team_memory)


class _FixedStrategySelector(StrategySelector):
    def __init__(self, strategy):
        super().__init__()
        self._strategy = strategy

    def select(self, obs):
        self.tactic_counts[self._strategy] += 1
        return self._strategy


class _ScoringSelector(_FixedStrategySelector):
    """A selector that can score every option, like the DQN does."""
    def q_values(self, obs):
        return {s.name: 0.5 for s in Strategy}


# ---------------------------------------------------------------------------
# Off by default
# ---------------------------------------------------------------------------

class TestTracingIsOptIn:
    def test_no_decision_records_by_default(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        assert cm.ai.trace_enabled is False

        plan(cm, monsters[0])

        assert [r for r in logger.records if r["type"] == "decision"] == []

    def test_decision_record_written_when_enabled(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True

        plan(cm, monsters[0])

        decisions = [r for r in logger.records if r["type"] == "decision"]
        assert len(decisions) == 1
        assert decisions[0]["creature"] == monsters[0].name
        assert decisions[0]["team"] == monsters[0].team


# ---------------------------------------------------------------------------
# Candidate tables
# ---------------------------------------------------------------------------

class TestCandidateTables:
    def test_weapon_stage_reports_rejected_options(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True

        decision = plan(cm, monsters[0])
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        candidates = rec["weapon"]["candidates"]
        # The goblin carries both a melee and a ranged option, so the losing
        # one must appear next to the winner -- that comparison is the whole
        # reason the trace exists.
        assert len(candidates) >= 2
        assert rec["weapon"]["chosen"] in [c["name"] for c in candidates]
        assert any(c["is_ranged"] for c in candidates)
        assert any(not c["is_ranged"] for c in candidates)
        for c in candidates:
            assert 0.0 <= c["p_hit"] <= 1.0
            assert c["score"] >= 0.0
            assert isinstance(c["in_range"], bool)

    def test_target_stage_lists_every_enemy(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True

        plan(cm, hero)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        names = [c["name"] for c in rec["target"]["candidates"]]
        assert sorted(names) == sorted(m.name for m in monsters)
        assert rec["target"]["chosen"] in names
        for c in rec["target"]["candidates"]:
            assert c["distance_ft"] is not None
            assert "effective_danger" in c   # memory was supplied

    def test_movement_stage_records_distance_change(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True

        plan(cm, hero)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        movement = rec["movement"]
        assert movement["action"] in {"approach", "withdraw", "hold", "dash",
                                      "dodge", "retreat", "disengage"}
        # Hero starts at [2,5] with a melee weapon and goblins across the
        # map, so he must be closing the gap.
        assert movement["distance_after"] <= movement["distance_before"]

    def test_disengage_records_its_trigger(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True
        # Traced on a goblin rather than the hero: _should_disengage only
        # fires when a living ally remains, and the hero fights alone here.
        wounded = monsters[0]
        wounded.hp = wounded.max_hp * 0.1

        decision = plan(cm, wounded)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        assert decision.reason == "disengaging — low HP"
        assert rec["movement"]["action"] == "disengage"
        assert rec["movement"]["hp_pct"] < rec["movement"]["threshold_pct"]


# ---------------------------------------------------------------------------
# Strategy stage
# ---------------------------------------------------------------------------

class TestStrategyStage:
    def test_reports_rule_based_when_no_selector(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True

        plan(cm, hero)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        assert rec["strategy"]["source"] == "rule_based"
        assert rec["strategy"]["chosen"] is None

    def test_captures_q_values_when_selector_exposes_them(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True
        cm.ai.strategy_selector = _ScoringSelector(Strategy.KITE)
        cm.ai.trained_team = hero.team

        plan(cm, hero)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        assert rec["strategy"]["chosen"] == "KITE"
        assert set(rec["strategy"]["q_values"]) == {s.name for s in Strategy}
        # 15 features, matching TeamMemory.get_state_vector -- note the
        # DQN checkpoints on disk were trained when this was 12 wide and
        # select() silently truncates via obs[:n_obs], so they are stale.
        assert len(rec["strategy"]["obs"]) == 15

    def test_q_values_absent_when_selector_cannot_score(self):
        cm, event, hero, monsters = make_combat()
        logger = CombatLogger(event, cm.initiative)
        cm.ai.trace_enabled = True
        cm.ai.strategy_selector = _FixedStrategySelector(Strategy.AGGRESSIVE)
        cm.ai.trained_team = hero.team

        plan(cm, hero)
        rec = [r for r in logger.records if r["type"] == "decision"][0]

        assert rec["strategy"]["chosen"] == "AGGRESSIVE"
        assert rec["strategy"]["q_values"] is None


# ---------------------------------------------------------------------------
# The safety property: observing must not perturb
# ---------------------------------------------------------------------------

class TestTracingDoesNotChangeDecisions:
    def _decisions_for_seed(self, seed, trace_enabled):
        random.seed(seed)
        cm, event, hero, monsters = make_combat()
        cm.ai.trace_enabled = trace_enabled
        out = []
        for creature in [hero] + list(monsters):
            d = plan(cm, creature)
            out.append((
                d.target.name if d.target else None,
                d.weapon.name if d.weapon else None,
                d.reason,
                tuple(d.path),
                d.use_dash,
                d.use_dodge,
            ))
        return out

    def test_same_decisions_with_and_without_tracing(self):
        for seed in (1, 7, 99):
            assert (self._decisions_for_seed(seed, False)
                    == self._decisions_for_seed(seed, True)), f"diverged on seed {seed}"
