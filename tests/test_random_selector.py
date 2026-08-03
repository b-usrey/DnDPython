"""
Tests for RandomStrategySelector (core/ml_strategy.py) -- the genuinely-
random-per-turn baseline used by `main.py eval` alongside the "no
selector" baseline (see main.py's _random_turn_worker / _baseline_worker).
"""
from collections import Counter

from core.ml_strategy import RandomStrategySelector, Strategy


class TestRandomStrategySelector:
    def test_returns_a_strategy(self):
        sel = RandomStrategySelector()
        assert sel.select([0.0] * 15) in list(Strategy)

    def test_updates_tactic_counts(self):
        sel = RandomStrategySelector()
        chosen = sel.select([0.0] * 15)
        assert sel.tactic_counts[chosen] == 1
        assert sum(sel.tactic_counts.values()) == 1

    def test_covers_all_strategies_over_many_calls(self):
        sel = RandomStrategySelector()
        seen = Counter(sel.select([0.0] * 15) for _ in range(2000))
        assert set(seen) == set(Strategy)
        # Roughly uniform -- loose bound just to catch a badly broken RNG call.
        for count in seen.values():
            assert 2000 / len(Strategy) * 0.5 < count < 2000 / len(Strategy) * 1.5

    def test_ignores_observation_contents(self):
        """select() takes obs only to satisfy the StrategySelector interface --
        it must not branch on it (unlike a real trained selector)."""
        sel = RandomStrategySelector()
        import random
        random.seed(42)
        a = sel.select([0.0] * 15)
        random.seed(42)
        b = sel.select([999.0] * 15)
        assert a == b
