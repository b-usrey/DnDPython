"""
core/ml_strategy.py

ML strategy layer for the D&D 5e encounter framework.

Architecture
------------
                    ┌─────────────────┐
                    │   CombatEnv     │  ← reset() / step() interface
                    │  (episode mgr)  │     like a gym environment
                    └────────┬────────┘
                             │ builds fresh combat each episode
                    ┌────────▼────────┐
                    │  CombatManager  │
                    │  + TacticalAI   │
                    └────────┬────────┘
                             │ per-turn obs vector (10 features)
                    ┌────────▼────────┐
                    │StrategySelector │  ← select(obs) → Strategy
                    │  RL or Evo      │     update(obs,a,r,s',done)
                    └─────────────────┘

Strategies
----------
  AGGRESSIVE  — always close to melee, never disengage
  KITE        — maintain ranged distance, back off when adjacent
  RETREAT     — move away from highest threat, attack only if safe

Selectors
---------
  RLStrategySelector     Q-table, ε-greedy, TD(0) updates
  EvolutionarySelector   weight matrix, scored by win-rate, mutated per gen

Training entry points
---------------------
  StrategyTrainer.train_rl(n_episodes)        → rewards per episode
  StrategyTrainer.train_evolutionary(n_gens)  → best win-rate per gen

Quick start
-----------
    from core.ml_strategy import (
        CombatEnv, RLStrategySelector, EvolutionarySelector, StrategyTrainer
    )
    import json

    scenario = json.load(open("scenarios/brendiir_vs_goblins.json"))

    # RL — train goblins to fight better
    env      = CombatEnv(scenario_data=scenario, trained_team="red")
    selector = RLStrategySelector()
    trainer  = StrategyTrainer(env, selector)
    rewards  = trainer.train_rl(n_episodes=500, verbose=True)
    selector.save("saves/goblin_rl.npy")

    # Evolutionary
    evo_sel = EvolutionarySelector()
    trainer2 = StrategyTrainer(env, evo_sel)
    trainer2.train_evolutionary(n_gens=20, combats_per_ind=10)
    evo_sel.save("saves/goblin_evo.npy")
"""

from __future__ import annotations

import enum
import io
import contextlib
import json
import os
import random
from typing import Callable

import numpy as np


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

class Strategy(enum.Enum):
    AGGRESSIVE  = 0
    KITE        = 1
    RETREAT     = 2
    FOCUS_FIRE  = 3   # charge the lowest-HP enemy regardless of distance
    PROTECT     = 4   # move to support the most-pressured ally

N_STRATEGIES = len(Strategy)


# ---------------------------------------------------------------------------
# StrategySelector base
# ---------------------------------------------------------------------------

class StrategySelector:
    def select(self, obs: list[float]) -> Strategy:
        raise NotImplementedError

    def update(self, obs, action, reward, next_obs, done):
        pass

    def save(self, path: str):
        raise NotImplementedError

    def load(self, path: str):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Observation discretiser (for Q-table)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# RL selector — Q-table with ε-greedy
# ---------------------------------------------------------------------------

class RLStrategySelector(StrategySelector):
    """
    Q(s,a) table updated via TD(0):
        Q(s,a) += α * (r + γ * max Q(s') − Q(s,a))

    Hyperparameters (all settable in __init__):
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
            return random.choice(list(Strategy))
        return Strategy(int(np.argmax(self.Q[s])))

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
# Evolutionary selector — weight matrix
# ---------------------------------------------------------------------------

class EvolutionarySelector(StrategySelector):
    """
    Each individual is a weight matrix W (n_features × N_STRATEGIES).
    Action = argmax(W @ obs).

    Training: score each individual by win-rate over N combats,
    keep the top elite_frac, fill the rest with mutated copies.

    Hyperparameters:
        pop_size        population size       20
        elite_frac      fraction kept         0.2
        mutation_scale  weight noise std      0.1
    """

    def __init__(self, n_features=9, pop_size=20,
                 elite_frac=0.2, mutation_scale=0.1):
        self.n_obs   = n_features
        self.pop_sz  = pop_size
        self.elite_n = max(1, int(pop_size * elite_frac))
        self.mut_std = mutation_scale
        self.W       = np.random.randn(n_features, N_STRATEGIES).astype(np.float32)
        self._pop    = [
            np.random.randn(n_features, N_STRATEGIES).astype(np.float32)
            for _ in range(pop_size)
        ]

    def select(self, obs: list[float]) -> Strategy:
        o = np.array(obs[:self.n_obs], dtype=np.float32)
        scores = o @ self.W   # (n_features,) @ (n_features, N_STRATEGIES) → (N_STRATEGIES,)
        return Strategy(int(np.argmax(scores)))

    def evolve_generation(self, fitness_scores: list[float]):
        ranked = sorted(zip(fitness_scores, self._pop),
                        key=lambda x: x[0], reverse=True)
        elite = [w.copy() for _, w in ranked[:self.elite_n]]
        new_pop = list(elite)
        while len(new_pop) < self.pop_sz:
            parent = random.choice(elite)
            child  = parent + np.random.randn(*parent.shape).astype(np.float32) * self.mut_std
            new_pop.append(child)
        self._pop = new_pop
        self.W    = elite[0]
        best = ranked[0][0]
        mean = float(np.mean([f for f, _ in ranked[:self.elite_n]]))
        print(f"  [Evo] best win-rate={best:.2%}  elite mean={mean:.2%}")

    def get_individual(self, idx: int) -> np.ndarray:
        return self._pop[idx]

    def deploy_individual(self, idx: int):
        self.W = self._pop[idx].copy()

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.save(path, self.W)
        print(f"  [Evo] weights saved → {path}")

    def load(self, path: str):
        self.W = np.load(path)
        print(f"  [Evo] weights loaded ← {path}")


# ---------------------------------------------------------------------------
# CombatEnv — episode factory
# ---------------------------------------------------------------------------

class CombatEnv:
    """
    Wraps the combat simulation into a clean reset/step interface.

    Each call to reset() tears down all shared state and builds a
    completely fresh combat from the scenario JSON so episodes are
    fully independent — no event bus leakage, no creature state carryover.

    Args:
        scenario_data:  parsed scenario dict (or path to JSON file)
        trained_team:   which team the selector controls ("red" / "blue")
        silent:         suppress all print output during training
    """

    WIN_REWARD   =  1.0
    LOSS_REWARD  = -1.0
    STEP_REWARD  = -0.01   # small penalty per turn encourages efficiency
    KILL_REWARD  =  0.3    # bonus per enemy downed
    DAMAGE_SCALE =  0.005  # reward per HP of damage dealt

    def __init__(
        self,
        scenario_data,
        trained_team: str = "red",
        silent: bool = True,
    ):
        if isinstance(scenario_data, str):
            with open(scenario_data) as f:
                scenario_data = json.load(f)
        self.scenario_data = scenario_data
        self.trained_team  = trained_team
        self.silent        = silent

        # Set after reset()
        self.cm        = None
        self.memories  = None
        self._prev_enemy_hp: dict = {}
        self._done     = False

    def reset(self):
        """
        Build a fresh combat. Returns the initial obs vector for the
        first creature of the trained team in initiative order, or
        a zero vector if none are present.
        """
        # Import here to avoid circular imports at module load time
        from core.events import EventBus
        from core.battle_map import BattleMap
        from core.tile import Tile
        from core.combat_manager import CombatManager, CombatMode
        from core.InitiativeManager import InitiativeManager
        from utils.creatureFactory import CreatureFactory
        from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures
        from core.team_memory import TeamMemory
        from data.monsters.monsters import MONSTER_REGISTRY

        event   = EventBus()
        factory = CreatureFactory()
        loader  = ScenarioLoader(factory, event)

        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf) if self.silent else contextlib.nullcontext()

        with ctx:
            players, monsters = loader.load(self.scenario_data)
            for m in monsters:
                mtype = next(
                    (t.get("type","").upper()
                     for t in self.scenario_data.get("monsters",[])
                     if MONSTER_REGISTRY.get(t.get("type","").upper())),
                    None
                )
                if mtype and mtype in MONSTER_REGISTRY:
                    m._attack_templates = MONSTER_REGISTRY[mtype].get("attacks", [])

            battle_map = build_map(self.scenario_data)

            place_creatures(
                self.scenario_data, players, monsters, battle_map
            )

            initiative = InitiativeManager(players + monsters, event)
            self.cm    = CombatManager(
                event, initiative, battle_map, mode=CombatMode.AUTO
            )
            self.memories = TeamMemory.create_for_all_teams(battle_map, event)

            initiative.roll_initiative()
            event.broadcast("CombatStarted", {"round": initiative.round})

        # Snapshot enemy HP for reward shaping
        self._prev_enemy_hp = {
            id(c): c.hp
            for _, c in self.cm.initiative.initiative_order
            if c.team != self.trained_team
        }
        self._done = False

        return self._get_obs_for_next_trained_creature()

    def run_episode(self, selector: "StrategySelector | None" = None) -> float:
        """
        Run one full episode, optionally with a strategy selector attached.

        The selector is wired to the AI for all creatures of the trained team.
        Reward = win/loss + kill bonuses + damage-scaled shaping.
        Returns total episode reward.
        """
        self.reset()

        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf) if self.silent else contextlib.nullcontext()

        if selector is not None:
            self.cm.ai.strategy_selector = selector

        with ctx:
            self.cm.run()

        if selector is not None:
            self.cm.ai.strategy_selector = None

        self._done = True

        # Determine the true binary outcome first (not influenced by shaping).
        # This is stored on self so train_rl() can read it via _outcome_won()
        # without relying on whether the shaped reward happens to be positive.
        survivors = [
            c for _, c in self.cm.initiative.initiative_order
            if c.is_alive()
        ]
        won = any(c.team == self.trained_team for c in survivors)
        reward = self.WIN_REWARD if won else self.LOSS_REWARD

        # Shape reward: kill count + damage dealt.
        # NOTE: this shaped value is returned for logging/monitoring only.
        # Q-table updates in train_rl() use the binary outcome, not this.
        for _, c in self.cm.initiative.initiative_order:
            if c.team == self.trained_team:
                continue
            hp_lost = c.max_hp - c.hp
            reward += hp_lost * self.DAMAGE_SCALE
            if not c.is_alive():
                reward += self.KILL_REWARD

        return reward

    def step(self, action: Strategy):
        """
        Gym-style interface: apply action for the next trained-team creature,
        run opponents until the next trained creature's turn or end of combat.

        Returns (obs, reward, done, info).
        """
        if self._done:
            raise RuntimeError("Call reset() before step() after episode ends.")

        reward = self.STEP_REWARD

        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf) if self.silent else contextlib.nullcontext()

        with ctx:
            order = self.cm.initiative.initiative_order
            # Find the next creature whose turn it is
            if not order:
                self._done = True
                return self._get_obs_for_next_trained_creature(), reward, True, {}

            _, creature = order[0]

            if creature.team == self.trained_team and creature.is_alive():
                self.cm.ai.current_strategy = action
                self.cm.ai.trained_team = self.trained_team
                self.cm._run_turn(creature)
                self.cm.ai.current_strategy = None
                self.cm.ai.trained_team = None
                reward += self._damage_reward()

            # Rotate and run opponents until next trained creature or end
            self.cm.initiative.advance_turn()
            while self.cm._combat_continues():
                if not self.cm.initiative.initiative_order:
                    break
                _, next_c = self.cm.initiative.initiative_order[0]
                if next_c.team == self.trained_team and next_c.is_alive():
                    break
                self.cm._run_turn(next_c)
                self.cm.initiative.advance_turn()

        done = not self.cm._combat_continues()
        self._done = done

        if done:
            survivors = [c for _, c in self.cm.initiative.initiative_order
                         if c.is_alive()]
            won = any(c.team == self.trained_team for c in survivors)
            reward += self.WIN_REWARD if won else self.LOSS_REWARD

        obs  = self._get_obs_for_next_trained_creature()
        info = {"round": self.cm.initiative.round}
        return obs, reward, done, info

    # -- helpers -----------------------------------------------------------

    def _outcome_won(self) -> bool:
        """Return True if the trained team won the last episode."""
        return any(
            c.is_alive()
            for _, c in self.cm.initiative.initiative_order
            if c.team == self.trained_team
        )

    def _damage_reward(self) -> float:
        """Reward proportional to HP damage dealt to enemies since last call."""
        reward = 0.0
        for _, c in self.cm.initiative.initiative_order:
            if c.team == self.trained_team:
                continue
            prev  = self._prev_enemy_hp.get(id(c), c.hp)
            delta = prev - c.hp
            if delta > 0:
                reward += delta * self.DAMAGE_SCALE
                if not c.is_alive():
                    reward += self.KILL_REWARD
            self._prev_enemy_hp[id(c)] = c.hp
        return reward

    def _get_obs_for_next_trained_creature(self) -> list[float]:
        """Get obs vector for the next creature of the trained team in order."""
        for _, c in self.cm.initiative.initiative_order:
            if c.team == self.trained_team and c.is_alive():
                memory  = self.memories.get(self.trained_team)
                enemies = self.cm.battle_map.enemies_of(c)
                allies  = [
                    x for _, x in self.cm.initiative.initiative_order
                    if x.team == self.trained_team and x is not c and x.is_alive()
                ]
                if memory:
                    return memory.get_state_vector(c, enemies, allies)
                break
        return [0.0] * 9


# ---------------------------------------------------------------------------
# TrainingLog — convergence tracking and export
# ---------------------------------------------------------------------------

class TrainingLog:
    """
    Records per-episode or per-generation training stats.
    Supports CSV export, JSON export, and matplotlib convergence plots.

    Usage inside StrategyTrainer is automatic when log= is passed:
        log = TrainingLog(name="goblin_rl")
        trainer.train_rl(n_episodes=500, log=log)
        log.plot()
        log.save_csv("saves/goblin_rl_log.csv")
    """

    def __init__(self, name: str = "training", trained_team: str = "?"):
        self.name         = name
        self.trained_team = trained_team
        self.episodes: list[dict] = []
        self._start_ts = None

    def start(self):
        import time
        self._start_ts = time.time()

    def record(self, **kwargs):
        """
        Record one data point. Common keys:
            episode, reward, win, epsilon,      (RL)
            generation, best_fitness, mean_fitness  (Evo)
        Any extra keyword arguments are stored too.
        """
        import time
        entry = dict(kwargs)
        if self._start_ts is not None:
            entry.setdefault("elapsed_s", round(time.time() - self._start_ts, 1))
        self.episodes.append(entry)

    # ── Export ────────────────────────────────────────────────────────

    def save_csv(self, path: str) -> None:
        import csv, os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not self.episodes:
            return
        fields = list(self.episodes[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.episodes)
        print(f"  [Log] CSV saved → {path}  ({len(self.episodes)} rows)")

    def save_json(self, path: str) -> None:
        import json, os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"name": self.name, "entries": self.episodes}, f, indent=2)
        print(f"  [Log] JSON saved → {path}")

    @classmethod
    def load_json(cls, path: str) -> "TrainingLog":
        import json
        with open(path) as f:
            data = json.load(f)
        log = cls(name=data.get("name", path))
        log.episodes = data.get("entries", [])
        return log

    # ── Plotting ──────────────────────────────────────────────────────

    def plot(
        self,
        smoothing: int = 20,
        save_path: str | None = None,
        show: bool = True,
    ) -> None:
        """
        Plot convergence curves.  For RL logs: reward and win rate over
        episodes.  For evolutionary logs: best and mean fitness per gen.

        smoothing: rolling-average window (set to 1 to disable)
        save_path: if given, saves the figure to this path
        show:      call plt.show() — set False when running headless
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("  [Log] matplotlib not available — skipping plot")
            return

        if not self.episodes:
            print("  [Log] nothing to plot yet")
            return

        # Determine which kind of log we have
        is_rl  = "reward"      in self.episodes[0]
        is_evo = "generation"  in self.episodes[0]

        fig, axes = plt.subplots(
            1, 2 if is_rl else 1,
            figsize=(12 if is_rl else 6, 4),
            tight_layout=True,
        )
        if is_rl:
            ax_r, ax_w = axes
        else:
            ax_r = axes if not hasattr(axes, "__len__") else axes[0]

        def smooth(vals, w):
            if w <= 1 or len(vals) < w:
                return vals
            return [
                sum(vals[max(0, i-w+1):i+1]) / min(i+1, w)
                for i in range(len(vals))
            ]

        fig.suptitle(f"{self.name} — convergence", fontweight="bold")

        if is_rl:
            rewards = [e["reward"] for e in self.episodes]
            eps     = [e.get("epsilon", None) for e in self.episodes]
            x       = list(range(1, len(rewards) + 1))

            ax_r.plot(x, rewards, alpha=0.25, color="steelblue", linewidth=0.8)
            ax_r.plot(x, smooth(rewards, smoothing), color="steelblue",
                      linewidth=2, label=f"reward (smooth {smoothing})")
            if any(e is not None for e in eps):
                ax_eps = ax_r.twinx()
                ax_eps.plot(x, eps, color="orange", linewidth=1,
                            linestyle="--", alpha=0.7, label="ε")
                ax_eps.set_ylabel("epsilon", color="orange")
            ax_r.set_xlabel("Episode")
            ax_r.set_ylabel("Reward")
            ax_r.set_title("Reward over episodes")
            ax_r.legend(loc="lower right")

            wins = [e.get("win", 0) for e in self.episodes]
            win_rate = smooth(wins, smoothing)
            ax_w.plot(x, win_rate, color="seagreen", linewidth=2)
            ax_w.set_ylim(0, 1)
            ax_w.set_xlabel("Episode")
            ax_w.set_ylabel("Win rate (trained team)")
            ax_w.set_title(f"Win rate — trained team (smooth {smoothing})")
            ax_w.axhline(0.5, color="gray", linestyle="--", linewidth=0.8)

        elif is_evo:
            bests = [e["best_fitness"] for e in self.episodes]
            means = [e.get("mean_fitness", None) for e in self.episodes]
            gens  = [e["generation"] for e in self.episodes]
            ax_r.plot(gens, bests, color="steelblue", linewidth=2,
                      marker="o", markersize=4, label="best")
            if any(m is not None for m in means):
                ax_r.plot(gens, means, color="steelblue", linewidth=1,
                          linestyle="--", alpha=0.6, label="mean elite")
            ax_r.set_ylim(0, 1)
            ax_r.set_xlabel("Generation")
            ax_r.set_ylabel("Win rate (trained team)")
            ax_r.set_title("Evolutionary fitness — trained team win rate")
            ax_r.legend()

        if save_path:
            fig.savefig(save_path, dpi=120)
            print(f"  [Log] plot saved → {save_path}")
        if show:
            plt.show()
        else:
            plt.close(fig)

    def summary(self) -> str:
        """Return a one-line text summary of the log."""
        if not self.episodes:
            return f"{self.name}: no data"
        last = self.episodes[-1]
        n    = len(self.episodes)
        team = f"team={self.trained_team}"
        if "reward" in last:
            recent = self.episodes[-min(50, n):]
            wr = sum(e.get("win", 0) for e in recent) / len(recent)
            return (f"{self.name} ({team}): {n} episodes  "
                    f"avg_reward={np.mean([e['reward'] for e in recent]):.3f}  "
                    f"team_win_rate={wr:.0%}  "
                    f"ε={last.get('epsilon', '?'):.3f}")
        if "generation" in last:
            return (f"{self.name} ({team}): {n} generations  "
                    f"best_team_win_rate={last['best_fitness']:.2%}")
        return f"{self.name}: {n} entries"


# ---------------------------------------------------------------------------
# StrategyTrainer
# ---------------------------------------------------------------------------

class StrategyTrainer:
    """
    Drives RL or evolutionary training loops using a CombatEnv.

    Args:
        env:      a CombatEnv instance
        selector: an RLStrategySelector or EvolutionarySelector
    """

    def __init__(self, env: CombatEnv, selector: StrategySelector):
        self.env      = env
        self.selector = selector

    # -- RL training -------------------------------------------------------

    def train_rl(
        self,
        n_episodes:  int  = 500,
        verbose:     bool = True,
        print_every: int  = 50,
        log: "TrainingLog | None" = None,
    ) -> list[float]:
        """
        RL training via episode-level Monte Carlo Q updates.

        Pass log=TrainingLog("run_name") to record per-episode stats.
        Returns list of per-episode total rewards.
        """
        assert isinstance(self.selector, RLStrategySelector), \
            "train_rl requires an RLStrategySelector"

        if log is not None:
            log.start()

        episode_rewards = []
        trajectory: list[tuple] = []

        _orig_select = self.selector.select
        def _instrumented_select(obs):
            action = _orig_select(obs)
            trajectory.append((list(obs), action))
            return action
        self.selector.select = _instrumented_select

        for ep in range(n_episodes):
            trajectory.clear()
            total = self.env.run_episode(selector=self.selector)
            episode_rewards.append(total)

            # Use the real combat outcome, not "shaped reward > 0".
            # Damage shaping can push a losing episode's reward positive,
            # which would teach the Q-table that losing while dealing damage
            # is as good as winning.
            won = self.env._outcome_won()

            # Q-updates use the binary win/loss signal only.
            # The shaped 'total' is kept for logging so convergence plots
            # still show the full reward curve, but it does not influence
            # what the Q-table learns.
            G = self.env.WIN_REWARD if won else self.env.LOSS_REWARD
            for obs, action in reversed(trajectory):
                self.selector.update(obs, action, G, obs, done=True)
                G *= self.selector.gamma

            self.selector.decay_epsilon()

            if log is not None:
                log.record(
                    episode=ep + 1,
                    reward=total,
                    win=int(won),
                    epsilon=round(self.selector.eps, 4),
                )

            if verbose and (ep + 1) % print_every == 0:
                recent   = episode_rewards[-print_every:]
                win_rate = sum(1 for r in recent if r > 0) / len(recent)
                print(
                    f"  [RL] ep {ep+1}/{n_episodes}  "
                    f"avg_reward={np.mean(recent):.3f}  "
                    f"team_win_rate={win_rate:.0%}  "
                    f"ε={self.selector.eps:.3f}"
                )

        self.selector.select = _orig_select
        if log is not None:
            print(f"\n  {log.summary()}")
        return episode_rewards

    # -- Evolutionary training ---------------------------------------------

    def train_evolutionary(
        self,
        n_gens:          int  = 20,
        combats_per_ind: int  = 10,
        verbose:         bool = True,
        log: "TrainingLog | None" = None,
    ) -> list[float]:
        """
        Evolutionary training. Each individual is a weight matrix scored
        by win-rate over combats_per_ind episodes. Elite individuals are
        kept and mutated to form the next generation.

        Pass log=TrainingLog("run_name") to record per-generation stats.
        Returns best win-rate per generation.
        """
        assert isinstance(self.selector, EvolutionarySelector), \
            "train_evolutionary requires an EvolutionarySelector"

        if log is not None:
            log.start()

        best_per_gen = []

        for gen in range(n_gens):
            fitness = []

            for idx in range(self.selector.pop_sz):
                self.selector.deploy_individual(idx)
                wins = 0
                for _ in range(combats_per_ind):
                    reward = self.env.run_episode(selector=self.selector)
                    if reward > 0:
                        wins += 1
                fitness.append(wins / combats_per_ind)

            best      = max(fitness)
            mean_elite = float(np.mean(sorted(fitness)[-self.selector.elite_n:]))
            best_per_gen.append(best)
            self.selector.evolve_generation(fitness)

            if log is not None:
                log.record(
                    generation=gen + 1,
                    best_fitness=best,
                    mean_fitness=float(np.mean(fitness)),
                    mean_elite=mean_elite,
                )

            if verbose:
                print(
                    f"  [Evo] gen {gen+1}/{n_gens}  "
                    f"best={best:.2%}  "
                    f"mean={np.mean(fitness):.2%}"
                )

        if log is not None:
            print(f"\n  {log.summary()}")
        return best_per_gen