"""
Tests for RLStrategySelector's step-wise TD learning with potential-based
reward shaping (core/selectors/rl_selector.py):
  - state_value() == max_a Q(s,a)
  - learn_from_episode() calls update() with real next-state transitions
    (not the same obs repeated) and marks only the final step done
  - the shaped-reward formula: env_reward (0 except on the last step)
    plus gamma*V(next_obs) - V(obs), computed from the table's own
    current values as each step is replayed
"""
import numpy as np
import pytest

from core.ml_strategy import Strategy, N_STRATEGIES
from core.selectors.rl_selector import RLStrategySelector


def make_obs(val: float) -> list:
    """A distinguishable 9-feature obs vector, all features equal to val."""
    return [val] * 9


class TestStateValue:
    def test_returns_max_q_for_discretised_state(self):
        sel = RLStrategySelector(n_features=9, n_bins=3)
        obs = make_obs(0.5)
        s = sel.disc.discretise(obs)
        sel.Q[s] = [1.0, 5.0, 2.0, 0.0, -1.0]
        assert sel.state_value(obs) == 5.0

    def test_zero_on_a_fresh_table(self):
        sel = RLStrategySelector(n_features=9, n_bins=3)
        assert sel.state_value(make_obs(0.3)) == 0.0


class TestLearnFromEpisodeMechanics:
    def test_calls_update_with_real_next_obs_not_same_obs(self, monkeypatch):
        """The bug this replaces: the old code called update(obs, action, G,
        obs, done=True) -- next_obs was always the SAME obs, and done was
        always True, so no real state transition ever entered training."""
        sel = RLStrategySelector(n_features=9, n_bins=3)
        calls = []
        monkeypatch.setattr(sel, "update", lambda *a, **kw: calls.append((a, kw)))

        obs1, obs2, obs3 = make_obs(0.1), make_obs(0.5), make_obs(0.9)
        trajectory = [
            (obs1, Strategy.AGGRESSIVE),
            (obs2, Strategy.KITE),
            (obs3, Strategy.RETREAT),
        ]
        sel.learn_from_episode(trajectory, outcome=1.0)

        assert len(calls) == 3

        (o, a, r, next_o), kw = calls[0]
        assert o == obs1 and next_o == obs2 and next_o != o
        assert kw["done"] is False

        (o, a, r, next_o), kw = calls[1]
        assert o == obs2 and next_o == obs3 and next_o != o
        assert kw["done"] is False

        # Last step: no real "next" state exists, so next_obs falls back
        # to the terminal obs itself, and done=True correctly stops the
        # bootstrap term in update()'s own TD target.
        (o, a, r, next_o), kw = calls[2]
        assert o == obs3 and next_o == obs3
        assert kw["done"] is True

    def test_empty_trajectory_is_a_noop(self):
        sel = RLStrategySelector(n_features=9, n_bins=3)
        sel.learn_from_episode([], outcome=1.0)   # must not raise
        assert np.all(sel.Q == 0)

    def test_single_step_episode_behaves_like_plain_q_learning(self):
        """With one step, there's no intermediate state to shape toward --
        V(obs)=V(next_obs)=0 on a fresh table, so this should reduce to a
        plain Q-learning update toward the terminal outcome."""
        sel = RLStrategySelector(n_features=9, n_bins=3, alpha=0.5)
        obs = make_obs(0.5)
        sel.learn_from_episode([(obs, Strategy.AGGRESSIVE)], outcome=1.0)

        s = sel.disc.discretise(obs)
        assert sel.Q[s, Strategy.AGGRESSIVE.value] == pytest.approx(0.5)  # alpha * outcome


class TestShapedRewardFormula:
    def test_shaping_matches_hand_computed_potential_difference(self):
        """Pre-seed the Q-table with distinct state values, then confirm
        each step's shaped reward matches gamma*V(next) - V(current) by
        hand -- the defining formula of potential-based reward shaping."""
        sel = RLStrategySelector(n_features=9, n_bins=3, gamma=0.9)
        obs_a, obs_b, obs_c = make_obs(0.1), make_obs(0.5), make_obs(0.9)
        s_a, s_b, s_c = (sel.disc.discretise(o) for o in (obs_a, obs_b, obs_c))

        sel.Q[s_a] = [1.0, 0.0, 0.0, 0.0, 0.0]   # V(a) = 1.0
        sel.Q[s_b] = [0.0, 4.0, 0.0, 0.0, 0.0]   # V(b) = 4.0
        sel.Q[s_c] = [2.0, 0.0, 0.0, 0.0, 0.0]   # V(c) = 2.0

        captured_rewards = []
        real_update = sel.update
        def spy(obs, action, reward, next_obs, done):
            captured_rewards.append(reward)
            real_update(obs, action, reward, next_obs, done)
        sel.update = spy

        trajectory = [
            (obs_a, Strategy.AGGRESSIVE),
            (obs_b, Strategy.KITE),
            (obs_c, Strategy.RETREAT),
        ]
        # Each step in this trajectory visits a *different* state, so each
        # step's own update() call can't have altered the value another
        # step reads -- the hand-computed values below stay valid even
        # though update() is running for real, not mocked out.
        sel.learn_from_episode(trajectory, outcome=0.0)

        assert captured_rewards[0] == pytest.approx(0.9 * 4.0 - 1.0)   # a -> b
        assert captured_rewards[1] == pytest.approx(0.9 * 2.0 - 4.0)   # b -> c
        assert captured_rewards[2] == pytest.approx(0.0 - 2.0)         # c (terminal), outcome=0.0

    def test_only_the_final_step_carries_the_terminal_outcome(self):
        sel = RLStrategySelector(n_features=9, n_bins=3)
        obs1, obs2 = make_obs(0.1), make_obs(0.9)

        captured_rewards = []
        real_update = sel.update
        def spy(obs, action, reward, next_obs, done):
            captured_rewards.append(reward)
            real_update(obs, action, reward, next_obs, done)
        sel.update = spy

        sel.learn_from_episode(
            [(obs1, Strategy.AGGRESSIVE), (obs2, Strategy.KITE)], outcome=1.0,
        )
        # Fresh table -> V(obs1) = V(obs2) = 0 for both steps (obs1's
        # update doesn't touch obs2's row), so:
        assert captured_rewards[0] == pytest.approx(0.0)   # non-terminal: 0 + 0 - 0
        assert captured_rewards[1] == pytest.approx(1.0)   # terminal: outcome + 0 - 0

    def test_shaping_rewards_moving_toward_a_higher_valued_state(self):
        """The whole point: a transition into a state the table already
        considers more likely to win should itself score positively, even
        with zero terminal reward -- that's the dense signal this change
        is meant to add."""
        sel = RLStrategySelector(n_features=9, n_bins=3, gamma=1.0)
        obs_bad, obs_good = make_obs(0.2), make_obs(0.8)
        s_bad, s_good = sel.disc.discretise(obs_bad), sel.disc.discretise(obs_good)
        sel.Q[s_bad]  = [0.1] * N_STRATEGIES
        sel.Q[s_good] = [0.9] * N_STRATEGIES

        captured_rewards = []
        real_update = sel.update
        def spy(obs, action, reward, next_obs, done):
            captured_rewards.append(reward)
            real_update(obs, action, reward, next_obs, done)
        sel.update = spy

        sel.learn_from_episode(
            [(obs_bad, Strategy.AGGRESSIVE), (obs_good, Strategy.KITE)], outcome=0.0,
        )
        assert captured_rewards[0] > 0   # bad -> good state: positive shaped reward
