"""
Regression tests for three defects that made the DQN strategy policy blind
and its action space degenerate.

1. TeamMemory.get_state_vector compared a distance in FEET (what
   battle_map.distance_between returns) against thresholds written in
   SQUARES. `in_melee` and `melee_crowd` could therefore never leave 0.0,
   and `nearest_dist` saturated at two squares, so 15 ft and 120 ft looked
   identical to the policy.

2. CombatManager advances the round by incrementing initiative.round
   directly rather than going through InitiativeManager.end_turn(), so
   nothing ever broadcast "RoundStarted". TeamMemory.round stayed 1 for
   the whole fight and the `round_frac` feature was a constant.

3. Shields are declared in data/items.json with item_type "armor" and
   armor_type "shield". equip_item dispatched on item_type, so a shield
   claimed the *body armour* slot and blocked real armour -- no character
   could wear armour and carry a shield.
"""
import io
import contextlib

import importlib, pkgutil, data.features
for _m in pkgutil.iter_modules(data.features.__path__):
    if _m.name != "base":
        importlib.import_module(f"data.features.{_m.name}")

from core.events import EventBus
from core.team_memory import TeamMemory
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


def _obs(scenario, creature_name):
    """Load a scenario and return (creature, state_vector, memory, map)."""
    event   = EventBus()
    loader  = ScenarioLoader(CreatureFactory(), event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(scenario)
        battle_map = build_map(scenario)
        place_creatures(scenario, players, monsters, battle_map)
        memories = TeamMemory.create_for_all_teams(battle_map, event)
    everyone = players + monsters
    me = next(c for c in everyone if c.name == creature_name)
    enemies = [c for c in everyone if c.team != me.team]
    allies  = [c for c in everyone if c.team == me.team and c is not me]
    mem = memories[me.team]
    return me, mem.get_state_vector(me, enemies, allies), mem, battle_map


SCEN = {
    "name": "units probe",
    "max_rounds": 30,
    "map": {"width": 20, "height": 10},
    "players": [{
        "name": "Hero",
        "classes": [["Fighter", 5]],
        "subclasses": {"Fighter": "Champion"},
        "stats": {"Str": 16, "Dex": 14, "Con": 14, "Int": 8, "Wis": 12, "Cha": 10},
        "items": ["Longsword", "Chain Mail"],
        "equipped": ["Longsword", "Chain Mail"],
    }],
    "monsters": [{"type": "GOBLIN", "count": 2, "weapon_role": "melee"}],
}

IDX_NEAR_DIST = 4
IDX_IN_MELEE  = 5
IDX_ROUND     = 6
IDX_CROWD     = 9


# -- 1. feet vs squares ----------------------------------------------------

def test_in_melee_is_set_when_adjacent():
    scen = dict(SCEN, positions={"Hero": [5, 5], "monsters": [[6, 5], [15, 5]]})
    _, obs, _, _ = _obs(scen, "Hero")
    assert obs[IDX_IN_MELEE] == 1.0, "adjacent enemy must register as melee contact"


def test_in_melee_is_clear_when_far():
    scen = dict(SCEN, positions={"Hero": [1, 5], "monsters": [[15, 5], [16, 5]]})
    _, obs, _, _ = _obs(scen, "Hero")
    assert obs[IDX_IN_MELEE] == 0.0


def test_nearest_distance_scales_below_the_old_floor():
    """Adjacent is 5 ft of a 50 ft cap -> 0.1. The buggy version floored at 0.5."""
    scen = dict(SCEN, positions={"Hero": [5, 5], "monsters": [[6, 5], [15, 5]]})
    _, obs, _, _ = _obs(scen, "Hero")
    assert obs[IDX_NEAR_DIST] < 0.5
    assert abs(obs[IDX_NEAR_DIST] - 0.1) < 1e-6


def test_nearest_distance_distinguishes_mid_range_from_far():
    """15 ft and 45 ft must not both read as 1.0."""
    near = dict(SCEN, positions={"Hero": [5, 5], "monsters": [[8, 5], [19, 5]]})
    far  = dict(SCEN, positions={"Hero": [5, 5], "monsters": [[14, 5], [19, 5]]})
    _, obs_near, _, _ = _obs(near, "Hero")
    _, obs_far,  _, _ = _obs(far,  "Hero")
    assert obs_near[IDX_NEAR_DIST] < obs_far[IDX_NEAR_DIST]


def test_melee_crowding_counts_adjacent_enemies():
    scen = dict(SCEN, positions={"Hero": [5, 5], "monsters": [[6, 5], [5, 6]]})
    _, obs, _, _ = _obs(scen, "Hero")
    assert obs[IDX_CROWD] > 0.0, "two adjacent enemies must register as crowding"


# -- 2. the round counter reaches TeamMemory -------------------------------

def test_round_started_is_broadcast_and_tracked():
    from core.ml_strategy import CombatEnv
    seen = []
    original = TeamMemory._on_round_started

    def spy(self, data):
        seen.append(data.get("round"))
        return original(self, data)

    TeamMemory._on_round_started = spy
    try:
        env = CombatEnv(SCEN, trained_team="red", silent=True)
        with contextlib.redirect_stdout(io.StringIO()):
            env.run_episode(None)
    finally:
        TeamMemory._on_round_started = original

    assert seen, "RoundStarted was never broadcast"
    assert max(seen) >= 2, f"round never advanced past 1: {seen}"


# A fight that reliably lasts several rounds -- two goblins die too fast for
# the round counter to move at all.
LONG_SCEN = dict(SCEN, monsters=[{"type": "GHAST", "count": 4, "weapon_role": "melee"}])


def test_round_fraction_is_not_frozen():
    """The feature must move as the fight goes on, not sit at 1/max_rounds."""
    from core.ml_strategy import CombatEnv
    values = set()
    original = TeamMemory.get_state_vector

    def spy(self, creature, enemies, allies, max_rounds=30):
        v = original(self, creature, enemies, allies, max_rounds)
        values.add(round(v[IDX_ROUND], 4))
        return v

    # A selector must be attached, otherwise plan_turn never builds an
    # observation and the only sample is the one taken at reset().
    from core.ml_strategy import Strategy, StrategySelector

    class Fixed(StrategySelector):
        def select(self, obs):
            return Strategy.AGGRESSIVE

    TeamMemory.get_state_vector = spy
    try:
        env = CombatEnv(LONG_SCEN, trained_team="red", silent=True)
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(3):
                env.run_episode(Fixed())
    finally:
        TeamMemory.get_state_vector = original

    assert len(values) > 1, f"round_frac was constant at {values}"
    assert max(values) > 0.0333, "round_frac never rose above round 1"


# -- 3. a shield no longer eats the body-armour slot -----------------------

SHIELD_PC = {
    "name": "Cleric test",
    "max_rounds": 30,
    "map": {"width": 12, "height": 8},
    "players": [{
        "name": "Kesla",
        "classes": [["Cleric", 5]],
        "subclasses": {"Cleric": "War"},
        "stats": {"Str": 14, "Dex": 10, "Con": 14, "Int": 10, "Wis": 17, "Cha": 12},
        "items": ["Mace", "Shield", "Scale Mail"],
        "equipped": ["Mace", "Shield", "Scale Mail"],
    }],
    "monsters": [{"type": "GOBLIN", "count": 1}],
}


def _load_pc(scenario, name):
    event  = EventBus()
    loader = ScenarioLoader(CreatureFactory(), event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, _ = loader.load(scenario)
    return next(p for p in players if p.name == name)


def test_shield_and_body_armour_can_be_worn_together():
    pc = _load_pc(SHIELD_PC, "Kesla")
    worn = {i.name for i in pc.equipped_items}
    assert "Scale Mail" in worn, f"body armour was blocked: {worn}"
    assert "Shield" in worn, f"shield was not equipped: {worn}"


def test_shield_plus_scale_mail_gives_the_right_ac():
    """Scale Mail 14 + Dex 0 (capped) + Shield 2 = 16."""
    pc = _load_pc(SHIELD_PC, "Kesla")
    assert pc.ac == 16, f"expected AC 16, got {pc.ac}"


def test_shield_occupies_a_hand_not_the_armour_slot():
    pc = _load_pc(SHIELD_PC, "Kesla")
    assert pc.equipped_slots["armor"] == "Scale Mail"
    assert "Shield" in (pc.equipped_slots["hand1"], pc.equipped_slots["hand2"])
