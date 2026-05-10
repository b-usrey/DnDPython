from __future__ import annotations

import os
import random

import numpy as np

from core.ml_strategy import Strategy, N_STRATEGIES, StrategySelector


class ObsDiscretiser:
    """Bin a continuous obs vector into a single integer state index."""

    def __init__(self, n_features: int = 9, n_bins: int = 3):
        self.n_features = n_features
        self.n_bins     = n_bins
        self.n_states   = n_bins ** n_features

    def discretise(self, obs: list[float]) -> int:
        idx = 0; radix = 1
        for val in obs[:self.n_features]:
            b    = int(max(0.0, min(1.0 - 1e-9, float(val))) * self.n_bins)
            idx += b * radix
            radix *= self.n_bins
        return idx


class RLStrategySelector(StrategySelector):
    """
    Q(s,a) table updated via TD(0):
        Q(s,a) += α * (r + γ * max Q(s') − Q(s,a))

    Hyperparameters:
        alpha       learning rate          0.20
        gamma       discount factor        0.95
        eps         initial exploration    1.0
        eps_min     minimum exploration    0.05
        eps_decay   per-episode decay      0.999
        n_bins      state bins/feature     3  (3^9 = 19,683 states)
    """

    def __init__(self, n_features=9, n_bins=3,
                 alpha=0.20, gamma=0.95,
                 eps=1.0, eps_min=0.05, eps_decay=0.999):
        super().__init__()
        self.disc      = ObsDiscretiser(n_features, n_bins)
        self.alpha     = alpha
        self.gamma     = gamma
        self.eps       = eps
        self.eps_min   = eps_min
        self.eps_decay = eps_decay
        self.Q = np.zeros((self.disc.n_states, N_STRATEGIES), dtype=np.float32)

    def select(self, obs: list[float]) -> Strategy:
        s = self.disc.discretise(obs)
        if random.random() < self.eps:
            result = random.choice(list(Strategy))
        else:
            result = Strategy(int(np.argmax(self.Q[s])))
        self.tactic_counts[result] += 1
        return result

    def update(self, obs, action: Strategy, reward: float, next_obs, done: bool):
        s  = self.disc.discretise(obs)
        s_ = self.disc.discretise(next_obs)
        a  = action.value
        td_target = reward + (0.0 if done else self.gamma * float(np.max(self.Q[s_])))
        self.Q[s, a] += self.alpha * (td_target - self.Q[s, a])

    def decay_epsilon(self):
        self.eps = max(self.eps_min, self.eps * self.eps_decay)

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.save(path, self.Q)
        print(f"  [RL] Q-table saved → {path}  (ε={self.eps:.3f})")

    def load(self, path: str):
        self.Q = np.load(path)
        print(f"  [RL] Q-table loaded ← {path}")


# ---------------------------------------------------------------------------
# Module-level worker (must be top-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _rl_train_worker(args):
    """Run a complete independent RL training run and return the final Q-table."""
    import io, contextlib
    from core.ml_strategy import CombatEnv
    scenario_data, team, n_episodes, n_bins, alpha, gamma, \
        eps, eps_min, eps_decay, worker_id, progress_queue, report_every = args

    env = CombatEnv(scenario_data=scenario_data, trained_team=team, silent=True)
    sel = RLStrategySelector(n_bins=n_bins, alpha=alpha, gamma=gamma,
                             eps=eps, eps_min=eps_min, eps_decay=eps_decay)
    trajectory = []

    def _instrumented_select(obs):
        action = RLStrategySelector.select(sel, obs)
        trajectory.append((list(obs), action))
        return action

    sel.select = _instrumented_select

    ep_rewards  = []
    ep_wins     = []
    ep_epsilons = []

    with contextlib.redirect_stdout(io.StringIO()):
        for ep in range(n_episodes):
            trajectory.clear()
            shaped = env.run_episode(selector=sel)
            G      = env._outcome_reward()
            won    = env._outcome_won()
            for obs, action in reversed(trajectory):
                sel.update(obs, action, G, obs, done=True)
                G *= sel.gamma
            sel.decay_epsilon()
            ep_rewards.append(shaped)
            ep_wins.append(int(won))
            ep_epsilons.append(round(sel.eps, 4))
            if progress_queue is not None and (ep + 1) % report_every == 0:
                progress_queue.put((worker_id, ep + 1))

    if progress_queue is not None:
        progress_queue.put((worker_id, n_episodes))
    return sel.Q, ep_rewards, ep_wins, ep_epsilons
