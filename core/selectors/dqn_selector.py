from __future__ import annotations

import collections
import os
import random
from typing import NamedTuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from core.ml_strategy import Strategy, N_STRATEGIES, StrategySelector

N_OBS = 12  # full 12-feature obs vector


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

class _QNet(nn.Module):
    def __init__(self, n_obs: int, hidden: tuple[int, ...], n_actions: int):
        super().__init__()
        layers: list[nn.Module] = []
        in_dim = n_obs
        for h in hidden:
            layers += [nn.Linear(in_dim, h), nn.ReLU()]
            in_dim = h
        layers.append(nn.Linear(in_dim, n_actions))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------

class _Transition(NamedTuple):
    obs:      list[float]
    action:   int
    reward:   float
    next_obs: list[float]
    done:     bool


class _ReplayBuffer:
    def __init__(self, capacity: int):
        self._buf: collections.deque[_Transition] = collections.deque(maxlen=capacity)

    def push(self, obs, action: int, reward: float, next_obs, done: bool):
        self._buf.append(_Transition(list(obs), action, reward, list(next_obs), done))

    def sample(self, batch_size: int) -> list[_Transition]:
        return random.sample(self._buf, batch_size)

    def __len__(self) -> int:
        return len(self._buf)


# ---------------------------------------------------------------------------
# DQN selector
# ---------------------------------------------------------------------------

class DQNStrategySelector(StrategySelector):
    """
    Deep Q-Network selector.

    Uses a small PyTorch MLP with:
      - Experience replay buffer
      - Target network (hard-updated every target_update_freq episodes)
      - Adam optimizer
      - Epsilon-greedy exploration

    Default architecture: 12 → 64 → 32 → 5 (one output per Strategy).

    Hyperparameters:
        hidden              layer sizes             (64, 32)
        lr                  Adam learning rate      1e-3
        gamma               discount factor         0.99
        eps                 initial exploration     1.0
        eps_min             minimum exploration     0.05
        eps_decay           per-episode decay       0.995
        buffer_size         replay buffer capacity  10_000
        batch_size          minibatch size          64
        target_update_freq  hard-copy period (eps)  100
    """

    def __init__(
        self,
        n_obs:              int         = N_OBS,
        hidden:             tuple       = (64, 32),
        lr:                 float       = 1e-3,
        gamma:              float       = 0.99,
        eps:                float       = 1.0,
        eps_min:            float       = 0.05,
        eps_decay:          float       = 0.995,
        buffer_size:        int         = 10_000,
        batch_size:         int         = 64,
        target_update_freq: int         = 100,
    ):
        super().__init__()
        self.n_obs              = n_obs
        self.gamma              = gamma
        self.eps                = eps
        self.eps_min            = eps_min
        self.eps_decay          = eps_decay
        self.batch_size         = batch_size
        self.target_update_freq = target_update_freq
        self._episodes          = 0

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self._online = _QNet(n_obs, hidden, N_STRATEGIES).to(self._device)
        self._target = _QNet(n_obs, hidden, N_STRATEGIES).to(self._device)
        self._target.load_state_dict(self._online.state_dict())
        self._target.eval()

        self._opt    = optim.Adam(self._online.parameters(), lr=lr)
        self._loss   = nn.MSELoss()
        self._buffer = _ReplayBuffer(buffer_size)

    # -- Inference -----------------------------------------------------------

    def select(self, obs: list[float]) -> Strategy:
        if random.random() < self.eps:
            result = random.choice(list(Strategy))
        else:
            with torch.no_grad():
                t      = torch.tensor(obs[:self.n_obs], dtype=torch.float32,
                                      device=self._device).unsqueeze(0)
                result = Strategy(int(self._online(t).argmax(dim=1).item()))
        self.tactic_counts[result] += 1
        return result

    # -- Learning ------------------------------------------------------------

    def update(self, obs, action: Strategy, reward: float, next_obs, done: bool):
        """Push one transition to the buffer and run a training step if ready."""
        self._buffer.push(obs, action.value, reward, next_obs, done)
        if len(self._buffer) >= self.batch_size:
            self._train_step()

    def _train_step(self):
        batch = self._buffer.sample(self.batch_size)

        obs_t      = torch.tensor([t.obs      for t in batch], dtype=torch.float32, device=self._device)
        next_obs_t = torch.tensor([t.next_obs for t in batch], dtype=torch.float32, device=self._device)
        action_t   = torch.tensor([t.action   for t in batch], dtype=torch.long,    device=self._device)
        reward_t   = torch.tensor([t.reward   for t in batch], dtype=torch.float32, device=self._device)
        done_t     = torch.tensor([float(t.done) for t in batch], dtype=torch.float32, device=self._device)

        # Q(s, a) from online network
        q_pred = self._online(obs_t).gather(1, action_t.unsqueeze(1)).squeeze(1)

        # r + γ * max_a' Q_target(s', a') * (1 − done)
        with torch.no_grad():
            next_q  = self._target(next_obs_t).max(dim=1).values
            targets = reward_t + self.gamma * next_q * (1.0 - done_t)

        loss = self._loss(q_pred, targets)
        self._opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self._online.parameters(), max_norm=10.0)
        self._opt.step()

    def decay_epsilon(self):
        self.eps = max(self.eps_min, self.eps * self.eps_decay)
        self._episodes += 1
        if self._episodes % self.target_update_freq == 0:
            self._target.load_state_dict(self._online.state_dict())

    # -- Persistence ---------------------------------------------------------

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save({
            "online":       self._online.state_dict(),
            "target":       self._target.state_dict(),
            "eps":          self.eps,
            "n_obs":        self.n_obs,
            "hidden_sizes": [m.out_features for m in self._online.net
                             if isinstance(m, nn.Linear)][:-1],
        }, path)
        print(f"  [DQN] weights saved → {path}  (ε={self.eps:.3f})")

    def load(self, path: str):
        ckpt = torch.load(path, map_location=self._device, weights_only=True)
        n_obs  = ckpt.get("n_obs", self.n_obs)
        hidden = tuple(ckpt.get("hidden_sizes", [64, 32]))
        self.n_obs   = n_obs
        self._online = _QNet(n_obs, hidden, N_STRATEGIES).to(self._device)
        self._target = _QNet(n_obs, hidden, N_STRATEGIES).to(self._device)
        self._online.load_state_dict(ckpt["online"])
        self._target.load_state_dict(ckpt["target"])
        self._online.eval()
        self._target.eval()
        self.eps = ckpt.get("eps", self.eps_min)
        print(f"  [DQN] weights loaded ← {path}  (ε={self.eps:.3f})")
