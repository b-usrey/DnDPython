"""
Tests for DQNStrategySelector's step-wise learning with potential-based
reward shaping (core/selectors/dqn_selector.py):
  - state_value() reads from the target network, not the online network
  - learn_from_episode() calls update() with real next-state transitions
    and marks only the final step done
  - the shaped-reward formula matches a hand-computed potential difference
  - the real (non-mocked) pipeline runs end-to-end without crashing
"""
import pytest
import torch

from core.ml_strategy import Strategy
from core.selectors.dqn_selector import DQNStrategySelector


def make_obs(val: float) -> list:
    """A distinguishable 12-feature obs vector, all features equal to val."""
    return [val] * 12


class TestStateValue:
    def test_reads_from_target_not_online_network(self):
        sel = DQNStrategySelector(n_obs=12)
        obs = make_obs(0.5)

        # Diverge the online network from the target network -- state_value
        # should reflect the (unmoved) target, not the online net.
        with torch.no_grad():
            for p in sel._online.parameters():
                p.add_(1000.0)

        v_target = sel.state_value(obs)
        with torch.no_grad():
            t = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)
            v_online = float(sel._online(t).max(dim=1).values.item())

        assert v_target != pytest.approx(v_online)


class TestLearnFromEpisodeMechanics:
    def test_calls_update_with_real_next_obs_not_same_obs(self, monkeypatch):
        sel = DQNStrategySelector(n_obs=12)
        monkeypatch.setattr(sel, "state_value", lambda obs: 0.0)
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
        (o, a, r, next_o), kw = calls[2]
        assert o == obs3 and next_o == obs3
        assert kw["done"] is True

    def test_empty_trajectory_is_a_noop(self):
        sel = DQNStrategySelector(n_obs=12)
        sel.learn_from_episode([], outcome=1.0)   # must not raise


class TestShapedRewardFormula:
    def test_shaping_matches_hand_computed_potential_difference(self, monkeypatch):
        sel = DQNStrategySelector(n_obs=12, gamma=0.9)
        obs_a, obs_b, obs_c = make_obs(0.1), make_obs(0.5), make_obs(0.9)
        values = {tuple(obs_a): 1.0, tuple(obs_b): 4.0, tuple(obs_c): 2.0}
        monkeypatch.setattr(sel, "state_value", lambda obs: values[tuple(obs)])

        captured_rewards = []
        monkeypatch.setattr(
            sel, "update",
            lambda obs, action, reward, next_obs, done: captured_rewards.append(reward),
        )

        trajectory = [
            (obs_a, Strategy.AGGRESSIVE),
            (obs_b, Strategy.KITE),
            (obs_c, Strategy.RETREAT),
        ]
        sel.learn_from_episode(trajectory, outcome=0.0)

        assert captured_rewards[0] == pytest.approx(0.9 * 4.0 - 1.0)   # a -> b
        assert captured_rewards[1] == pytest.approx(0.9 * 2.0 - 4.0)   # b -> c
        assert captured_rewards[2] == pytest.approx(0.0 - 2.0)         # c (terminal), outcome=0.0

    def test_only_the_final_step_carries_the_terminal_outcome(self, monkeypatch):
        sel = DQNStrategySelector(n_obs=12)
        monkeypatch.setattr(sel, "state_value", lambda obs: 0.0)
        captured_rewards = []
        monkeypatch.setattr(
            sel, "update",
            lambda obs, action, reward, next_obs, done: captured_rewards.append(reward),
        )
        obs1, obs2 = make_obs(0.1), make_obs(0.9)
        sel.learn_from_episode(
            [(obs1, Strategy.AGGRESSIVE), (obs2, Strategy.KITE)], outcome=1.0,
        )
        assert captured_rewards[0] == pytest.approx(0.0)
        assert captured_rewards[1] == pytest.approx(1.0)


class TestLearnFromEpisodeIntegration:
    def test_real_pipeline_runs_without_crashing_and_fills_buffer(self):
        """No mocking -- exercises the real target network forward passes
        and a real _train_step() gradient update."""
        sel = DQNStrategySelector(n_obs=12, batch_size=2, buffer_size=100)
        trajectory = [
            (make_obs(0.1), Strategy.AGGRESSIVE),
            (make_obs(0.5), Strategy.KITE),
            (make_obs(0.9), Strategy.RETREAT),
        ]
        sel.learn_from_episode(trajectory, outcome=1.0)
        assert len(sel._buffer) == 3
