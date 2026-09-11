"""
Tests for HeuristicStrategySelector (core/selectors/heuristic_selector.py):
the hand-crafted teacher policy used for DQN imitation-learning pretraining.

The thresholds were retuned against four-PC party scenarios. The old policy
fired FOCUS_FIRE whenever the scariest enemy was dangerous, which in a party
fight is nearly every turn; it scored 15% where the default planner scores
50%. FOCUS_FIRE now keys off the focus target's own HP ("finish them off"),
PROTECT additionally requires the pressured ally to be in real danger, and
everything else falls through to AGGRESSIVE.
"""
from core.ml_strategy import Strategy
from core.selectors.heuristic_selector import HeuristicStrategySelector


def make_obs(own_hp=1.0, size_adv=0.5, ally_pressure=0.0, top_threat=0.0,
             focus_hp=0.0, pressured_ally_hp=0.0):
    """A full 15-feature obs vector with only the fields under test set."""
    return [
        own_hp,             # 0  own HP ratio
        1.0,                # 1  team HP ratio
        1.0,                # 2  enemy HP ratio
        size_adv,           # 3  team size advantage
        1.0,                # 4  nearest enemy distance
        0.0,                # 5  in melee
        0.0,                # 6  round fraction
        ally_pressure,      # 7  any ally under pressure
        top_threat,         # 8  top enemy threat
        0.0,                # 9  melee crowding
        focus_hp,           # 10 focus-target HP ratio
        pressured_ally_hp,  # 11 most-pressured ally HP ratio
        0.0,                # 12 has a ranged option
        0.5,                # 13 relative tankiness
        1.0,                # 14 spell resources
    ]


class TestHeuristicSelector:
    def test_retreats_when_hurt_and_outnumbered(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(own_hp=0.1, size_adv=0.2)) == Strategy.RETREAT

    def test_does_not_retreat_when_hurt_but_not_outnumbered(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(own_hp=0.1, size_adv=0.8)) != Strategy.RETREAT

    def test_does_not_retreat_when_outnumbered_but_healthy(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(own_hp=0.9, size_adv=0.2)) != Strategy.RETREAT

    def test_protects_a_badly_hurt_ally_when_healthy(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.9, size_adv=0.8, ally_pressure=1.0,
                       pressured_ally_hp=0.15)
        assert sel.select(obs) == Strategy.PROTECT

    def test_does_not_protect_a_healthy_ally(self):
        """Pressure alone is not an emergency -- this fired on most turns and
        was the single biggest drag on the old teacher's win rate."""
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.9, size_adv=0.8, ally_pressure=1.0,
                       pressured_ally_hp=0.9)
        assert sel.select(obs) == Strategy.AGGRESSIVE

    def test_does_not_protect_when_too_hurt_to_help(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.4, size_adv=0.8, ally_pressure=1.0,
                       pressured_ally_hp=0.15)
        assert sel.select(obs) != Strategy.PROTECT

    def test_focus_fires_to_finish_a_nearly_dead_target(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(focus_hp=0.1)) == Strategy.FOCUS_FIRE

    def test_does_not_focus_fire_a_healthy_target(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(focus_hp=0.8)) == Strategy.AGGRESSIVE

    def test_high_threat_alone_no_longer_triggers_focus_fire(self):
        """The old rule keyed off feature 8 and fired on ~70% of party turns."""
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.8, size_adv=0.8, top_threat=0.9, focus_hp=0.8)
        assert sel.select(obs) == Strategy.AGGRESSIVE

    def test_defaults_to_aggressive(self):
        sel = HeuristicStrategySelector()
        assert sel.select(make_obs(own_hp=0.8, size_adv=0.8)) == Strategy.AGGRESSIVE

    def test_retreat_takes_priority_over_protect(self):
        """A creature that is both hurt and outnumbered while an ally is under
        pressure should save itself first -- it cannot help anyone dead."""
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.1, size_adv=0.2, ally_pressure=1.0,
                       pressured_ally_hp=0.1)
        assert sel.select(obs) == Strategy.RETREAT

    def test_protect_takes_priority_over_focus_fire(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.9, size_adv=0.8, ally_pressure=1.0,
                       pressured_ally_hp=0.15, focus_hp=0.1)
        assert sel.select(obs) == Strategy.PROTECT

    def test_short_observation_vectors_are_tolerated(self):
        """The 9-wide Q-table layout has no feature 10/11 to read."""
        sel = HeuristicStrategySelector()
        assert sel.select([0.9, 1.0, 1.0, 0.8, 1.0, 0.0, 0.0, 0.0, 0.0]) \
            == Strategy.AGGRESSIVE

    def test_tactic_counts_tracked(self):
        sel = HeuristicStrategySelector()
        sel.select(make_obs(own_hp=0.8, size_adv=0.8))
        assert sel.tactic_counts[Strategy.AGGRESSIVE] == 1
