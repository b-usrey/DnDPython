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
    def __init__(self):
        self.tactic_counts = {s: 0 for s in Strategy}

    def select(self, obs: list[float]) -> Strategy:
        raise NotImplementedError

    def reset_tactic_counts(self):
        self.tactic_counts = {s: 0 for s in Strategy}

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
                 elite_frac=0.2, mutation_scale=0.1, crossover_rate=0.5):
        super().__init__()
        self.n_obs        = n_features
        self.pop_sz       = pop_size
        self.elite_n      = max(1, int(pop_size * elite_frac))
        self.mut_std      = mutation_scale
        self.crossover_rate = crossover_rate
        self.W            = np.random.randn(n_features, N_STRATEGIES).astype(np.float32)
        self._pop         = [
            np.random.randn(n_features, N_STRATEGIES).astype(np.float32)
            for _ in range(pop_size)
        ]

    def select(self, obs: list[float]) -> Strategy:
        o = np.array(obs[:self.n_obs], dtype=np.float32)
        scores = o @ self.W
        result = Strategy(int(np.argmax(scores)))
        self.tactic_counts[result] += 1
        return result

    def evolve_generation(self, fitness_scores: list[float]):
        ranked = sorted(zip(fitness_scores, self._pop),
                        key=lambda x: x[0], reverse=True)
        elite = [w.copy() for _, w in ranked[:self.elite_n]]
        new_pop = list(elite)
        while len(new_pop) < self.pop_sz:
            parent_a = random.choice(elite)
            if self.crossover_rate > 0.0 and len(elite) > 1 and random.random() < self.crossover_rate:
                parent_b = random.choice(elite)
                mask  = np.random.rand(*parent_a.shape) < 0.5
                child = np.where(mask, parent_a, parent_b).astype(np.float32)
            else:
                child = parent_a.copy()
            child = child + np.random.randn(*child.shape).astype(np.float32) * self.mut_std
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

    WIN_REWARD      =  1.0
    LOSS_REWARD     = -1.0
    TIMEOUT_REWARD  =  0.4   # base reward for lasting full max_rounds ("reinforcements")
    ATTRITION_SCALE =  0.5   # how much enemy attrition softens a loss
    STEP_REWARD     = -0.01  # small penalty per turn encourages efficiency
    KILL_REWARD     =  0.3   # bonus per enemy downed
    DAMAGE_SCALE    =  0.005 # reward per HP of damage dealt

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
            max_rounds = self.scenario_data.get("max_rounds", 100)
            self.cm    = CombatManager(
                event, initiative, battle_map, mode=CombatMode.AUTO,
                max_rounds=max_rounds,
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

        all_creatures = [c for _, c in self.cm.initiative.initiative_order]
        survivors     = [c for c in all_creatures if c.is_alive()]
        enemies       = [c for c in all_creatures if c.team != self.trained_team]

        won      = any(c.team == self.trained_team for c in survivors)
        timed_out = self.cm.timed_out

        # ── Fractional outcome reward ────────────────────────────────────
        # enemy_attrition: fraction of enemies killed [0, 1]
        enemies_killed   = sum(1 for c in enemies if not c.is_alive())
        enemy_attrition  = enemies_killed / len(enemies) if enemies else 0.0

        if won and not timed_out:
            # Clear victory — all enemies eliminated
            reward = self.WIN_REWARD
        elif timed_out:
            # Lasted to max_rounds ("reinforcements arrived")
            # Scale by surviving HP fraction so healthier survival = better reward
            trained_alive = [c for c in survivors if c.team == self.trained_team]
            hp_fraction   = (sum(c.hp for c in trained_alive) /
                             sum(c.max_hp for c in trained_alive)) if trained_alive else 0.0
            reward = self.TIMEOUT_REWARD * hp_fraction
        else:
            # Defeat — soften by how much attrition was dealt
            reward = self.LOSS_REWARD + self.ATTRITION_SCALE * enemy_attrition

        # ── Per-turn shaping: damage dealt + kills ───────────────────────
        # Returned for logging/convergence plots only.
        # train_rl() reads _outcome_reward() for Q-updates, not this value.
        for c in enemies:
            hp_lost = c.max_hp - c.hp
            reward += hp_lost * self.DAMAGE_SCALE
            if not c.is_alive():
                reward += self.KILL_REWARD

        self._won      = won and not timed_out
        self._timed_out = timed_out
        self._enemy_attrition = enemy_attrition
        return reward

    def _outcome_reward(self) -> float:
        """Fractional outcome reward without per-turn shaping — used for Q-updates."""
        all_creatures = [c for _, c in self.cm.initiative.initiative_order]
        survivors     = [c for c in all_creatures if c.is_alive()]
        enemies       = [c for c in all_creatures if c.team != self.trained_team]
        won           = any(c.team == self.trained_team for c in survivors)
        timed_out     = self.cm.timed_out
        enemies_killed = sum(1 for c in enemies if not c.is_alive())
        enemy_attrition = enemies_killed / len(enemies) if enemies else 0.0
        if won and not timed_out:
            return self.WIN_REWARD
        elif timed_out:
            trained_alive = [c for c in survivors if c.team == self.trained_team]
            hp_fraction   = (sum(c.hp for c in trained_alive) /
                             sum(c.max_hp for c in trained_alive)) if trained_alive else 0.0
            return self.TIMEOUT_REWARD * hp_fraction
        else:
            return self.LOSS_REWARD + self.ATTRITION_SCALE * enemy_attrition

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
        """Return True only on a clear victory (not a timeout survival)."""
        return getattr(self, "_won", False)

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

    @classmethod
    def load_csv(cls, path: str) -> "TrainingLog":
        import csv, os
        name = os.path.splitext(os.path.basename(path))[0]
        log = cls(name=name)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                entry = {}
                for k, v in row.items():
                    try:
                        entry[k] = int(v) if v == str(int(float(v))) else float(v)
                    except (ValueError, OverflowError):
                        entry[k] = v
                log.episodes.append(entry)
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
# Module-level worker functions (must be at top-level for multiprocessing)
# ---------------------------------------------------------------------------

def _rl_train_worker(args):
    """Run a complete independent RL training run and return the final Q-table."""
    import io, contextlib
    scenario_data, team, n_episodes, n_bins, alpha, gamma, \
        eps, eps_min, eps_decay, worker_id, progress_queue, report_every = args
    env = CombatEnv(scenario_data=scenario_data, trained_team=team, silent=True)
    sel = RLStrategySelector(n_bins=n_bins, alpha=alpha, gamma=gamma,
                             eps=eps, eps_min=eps_min, eps_decay=eps_decay)
    trajectory = []

    def _instrumented_select(obs):
        action = sel.__class__.select(sel, obs)
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
        progress_queue.put((worker_id, n_episodes))  # final
    return sel.Q, ep_rewards, ep_wins, ep_epsilons


def _evo_fitness_worker(args):
    """Evaluate one evolutionary individual and return its win-rate."""
    import io, contextlib
    scenario_data, W, team, combats_per_ind = args
    env = CombatEnv(scenario_data=scenario_data, trained_team=team, silent=True)
    sel = EvolutionarySelector()
    sel.W = np.array(W, dtype=np.float32)
    wins = 0
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(combats_per_ind):
            if env.run_episode(selector=sel) > 0:
                wins += 1
    return wins / combats_per_ind


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
        workers:     int  = 1,
    ) -> list[float]:
        """
        RL training via episode-level Monte Carlo Q updates.

        Pass log=TrainingLog("run_name") to record per-episode stats.
        Returns list of per-episode total rewards.
        """
        assert isinstance(self.selector, RLStrategySelector), \
            "train_rl requires an RLStrategySelector"

        if workers > 1:
            import multiprocessing
            import time
            from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED
            from concurrent.futures import wait as fut_wait

            chunk = n_episodes // workers
            remainder = n_episodes % workers
            chunks = [chunk + (1 if i < remainder else 0) for i in range(workers)]
            sel = self.selector
            report_every = max(50, chunks[0] // 40)

            # Manager().Queue() creates a proxy-backed queue that survives
            # pickle, unlike multiprocessing.Queue which asserts it must only
            # be shared via inheritance (fork), not via ProcessPoolExecutor.
            _mgr = multiprocessing.Manager()
            progress_queue = _mgr.Queue()

            tasks = [
                (self.env.scenario_data, self.env.trained_team,
                 c, sel.disc.n_bins, sel.alpha, sel.gamma,
                 sel.eps, sel.eps_min, sel.eps_decay,
                 i, progress_queue, report_every)
                for i, c in enumerate(chunks)
            ]
            print(f"  [RL] Parallel training: {workers} independent runs × "
                  f"~{chunks[0]} eps = {n_episodes} total")

            # worker_id → (Q, ep_rewards, ep_wins, ep_epsilons)
            worker_results  = {}
            future_to_wid   = {}
            worker_progress = [0] * workers
            t0 = time.perf_counter()

            if log is not None:
                log.start()

            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_rl_train_worker, t) for t in tasks]
                for i, f in enumerate(futures):
                    future_to_wid[id(f)] = i
                pending = set(futures)

                while pending:
                    done_now, pending = fut_wait(pending, timeout=0.3,
                                                 return_when=FIRST_COMPLETED)
                    for fut in done_now:
                        wid = future_to_wid[id(fut)]
                        worker_results[wid] = fut.result()

                    # Drain all queued progress reports
                    while True:
                        try:
                            wid, ep = progress_queue.get_nowait()
                            worker_progress[wid] = ep
                        except Exception:
                            break

                    elapsed = time.perf_counter() - t0
                    parts = [
                        f"W{i}:{worker_progress[i]/chunks[i]:5.1%}"
                        for i in range(workers)
                    ]
                    n_done = len(worker_results)
                    print(f"\r    {' | '.join(parts)}  "
                          f"[{n_done}/{workers} done]  {elapsed:.0f}s",
                          end="", flush=True)

            _mgr.shutdown()
            print()
            q_tables = [worker_results[i][0] for i in range(workers)]
            self.selector.Q   = np.mean(q_tables, axis=0).astype(np.float32)
            self.selector.eps = self.selector.eps_min
            print(f"  [RL] Averaged {workers} Q-tables → ε={self.selector.eps:.3f}")

            # Only log worker 0's episodes — a single honest convergence curve.
            # All workers start from the same hyperparams so W0 is representative.
            if log is not None:
                ep_r, ep_w, ep_e = worker_results[0][1:]
                for i, (r, w, e) in enumerate(zip(ep_r, ep_w, ep_e)):
                    log.record(episode=i + 1, reward=r, win=w, epsilon=e)
                print(f"\n  {log.summary()}")

            return worker_results[0][1]  # W0 rewards

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

            won = self.env._outcome_won()

            # Use fractional outcome reward for Q-updates so the table learns
            # that timeout-survival and high-attrition losses are better than
            # dying quickly, while still keeping clear wins as the top signal.
            G = self.env._outcome_reward()
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
        workers:         int  = 1,
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

        if workers > 1:
            import time
            from concurrent.futures import ProcessPoolExecutor, as_completed
            _pool = ProcessPoolExecutor(max_workers=workers)
        else:
            _pool = None

        for gen in range(n_gens):
            fitness = []

            if _pool is not None:
                pop_sz   = self.selector.pop_sz
                fut_map  = {
                    _pool.submit(_evo_fitness_worker,
                                 (self.env.scenario_data,
                                  self.selector.get_individual(idx).tolist(),
                                  self.env.trained_team, combats_per_ind)): idx
                    for idx in range(pop_sz)
                }
                fitness  = [0.0] * pop_sz
                done     = 0
                best_so_far = 0.0
                t0 = time.perf_counter()
                print(f"  [Evo] gen {gen+1}/{n_gens}")
                for fut in as_completed(fut_map):
                    fitness[fut_map[fut]] = fut.result()
                    best_so_far = max(best_so_far, fut.result())
                    done += 1
                    pct     = done / pop_sz
                    bar     = ("█" * int(pct * 25)).ljust(25)
                    elapsed = time.perf_counter() - t0
                    eta     = elapsed / done * (pop_sz - done) if done < pop_sz else 0
                    print(f"\r    [{bar}] {done}/{pop_sz} individuals  "
                          f"best so far: {best_so_far:.1%}  "
                          f"elapsed: {elapsed:.0f}s  eta: {eta:.0f}s",
                          end="", flush=True)
                print()
            else:
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

        if _pool is not None:
            _pool.shutdown(wait=False)
        if log is not None:
            print(f"\n  {log.summary()}")
        return best_per_gen