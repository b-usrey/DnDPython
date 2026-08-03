"""
Tests for HeuristicStrategySelector (core/selectors/heuristic_selector.py):
the hand-crafted teacher policy used for DQN imitation-learning pretraining.
"""
from core.ml_strategy import Strategy
from core.selectors.heuristic_selector import HeuristicStrategySelector


def make_obs(own_hp=1.0, size_adv=0.5, ally_pressure=0.0, top_threat=0.0):
    """A 9-feature-minimum obs vector with only the fields the heuristic reads set."""
    return [own_hp, 1.0, 1.0, size_adv, 0.0, 0.0, 0.0, ally_pressure, top_threat]


class TestHeuristicSelector:
    def test_retreats_when_hurt_and_outnumbered(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.1, size_adv=0.2)
        assert sel.select(obs) == Strategy.RETREAT

    def test_does_not_retreat_when_hurt_but_not_outnumbered(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.1, size_adv=0.8)
        assert sel.select(obs) != Strategy.RETREAT

    def test_does_not_retreat_when_outnumbered_but_healthy(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.9, size_adv=0.2)
        assert sel.select(obs) != Strategy.RETREAT

    def test_protects_when_ally_under_pressure_and_not_critical(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.8, size_adv=0.8, ally_pressure=1.0)
        assert sel.select(obs) == Strategy.PROTECT

    def test_focus_fires_a_standout_threat(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.8, size_adv=0.8, ally_pressure=0.0, top_threat=0.9)
        assert sel.select(obs) == Strategy.FOCUS_FIRE

    def test_defaults_to_aggressive(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.8, size_adv=0.8, ally_pressure=0.0, top_threat=0.0)
        assert sel.select(obs) == Strategy.AGGRESSIVE

    def test_retreat_takes_priority_over_protect(self):
        """A creature that's both hurt+outnumbered AND has a pressured ally
        should save itself first -- it can't help anyone dead."""
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.1, size_adv=0.2, ally_pressure=1.0)
        assert sel.select(obs) == Strategy.RETREAT

    def test_protect_takes_priority_over_focus_fire(self):
        sel = HeuristicStrategySelector()
        obs = make_obs(own_hp=0.8, size_adv=0.8, ally_pressure=1.0, top_threat=0.9)
        assert sel.select(obs) == Strategy.PROTECT

    def test_tactic_counts_tracked(self):
        sel = HeuristicStrategySelector()
        sel.select(make_obs(own_hp=0.8, size_adv=0.8))
        assert sel.tactic_counts[Strategy.AGGRESSIVE] == 1
