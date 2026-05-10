"""
core/ml_strategy.py

Core ML strategy types for the D&D 5e encounter framework.

Layout
------
  core/ml_strategy.py          Strategy enum, StrategySelector base,
                                RewardConfig, CombatEnv, TrainingLog
  core/selectors/rl_selector.py  ObsDiscretiser, RLStrategySelector
  core/selectors/evo_selector.py EvolutionarySelector
  core/trainer.py              StrategyTrainer

Backward-compatible re-exports keep existing imports working:
    from core.ml_strategy import RLStrategySelector, EvolutionarySelector, ...
"""

from __future__ import annotations

import dataclasses
import enum
import io
import contextlib
import json
import os
import random

import numpy as np


# ---------------------------------------------------------------------------
# Strategy enum
# ---------------------------------------------------------------------------

class Strategy(enum.Enum):
    AGGRESSIVE  = 0
    KITE        = 1
    RETREAT     = 2
    FOCUS_FIRE  = 3
    PROTECT     = 4

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
# RewardConfig
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RewardConfig:
    """
    All reward scalars in one place. Loaded from the scenario JSON under
    the optional "rewards" key; omitted fields fall back to defaults.
    """
    win:             float =  1.0
    loss:            float = -1.0
    timeout:         float =  0.4
    attrition_scale: float =  0.5
    step:            float = -0.01
    kill:            float =  0.3
    damage_scale:    float =  0.005

    @classmethod
    def from_dict(cls, d: dict) -> "RewardConfig":
        valid = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: float(v) for k, v in d.items() if k in valid})


# ---------------------------------------------------------------------------
# CombatEnv — episode factory
# ---------------------------------------------------------------------------

class CombatEnv:
    """
    Wraps the combat simulation into a reset/step interface.

    Each call to reset() builds a completely fresh combat from the scenario
    JSON — no event bus leakage, no creature state carryover.

    Args:
        scenario_data:  parsed scenario dict, path, or list of dicts
                        (list → one picked at random each episode)
        trained_team:   which team the selector controls
        silent:         suppress print output during training
    """

    def __init__(
        self,
        scenario_data,
        trained_team: str = "red",
        silent: bool = True,
    ):
        if isinstance(scenario_data, str):
            with open(scenario_data) as f:
                scenario_data = json.load(f)
        if isinstance(scenario_data, dict):
            self._scenarios = [scenario_data]
        else:
            self._scenarios = list(scenario_data)

        self.scenario_data = self._scenarios[0]
        self.trained_team  = trained_team
        self.silent        = silent
        self.reward_cfg    = RewardConfig.from_dict(
            self.scenario_data.get("rewards", {})
        )

        self.cm        = None
        self.memories  = None
        self._prev_enemy_hp: dict = {}
        self._done     = False

    def reset(self):
        """
        Build a fresh combat. Picks a random scenario when multiple were
        supplied. Returns the initial obs vector for the trained team.
        """
        self.scenario_data = random.choice(self._scenarios)
        self.reward_cfg    = RewardConfig.from_dict(
            self.scenario_data.get("rewards", {})
        )

        from core.events import EventBus
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
            monster_idx = 0
            for tmpl in self.scenario_data.get("monsters", []):
                mtype   = tmpl.get("type", "").upper()
                count   = tmpl.get("count", 1)
                attacks = MONSTER_REGISTRY.get(mtype, {}).get("attacks", [])
                for _ in range(count):
                    if monster_idx >= len(monsters):
                        break
                    monsters[monster_idx]._attack_templates = attacks
                    monster_idx += 1

            battle_map = build_map(self.scenario_data)
            place_creatures(self.scenario_data, players, monsters, battle_map)

            initiative = InitiativeManager(players + monsters, event)
            max_rounds = self.scenario_data.get("max_rounds", 100)
            self.cm    = CombatManager(
                event, initiative, battle_map, mode=CombatMode.AUTO,
                max_rounds=max_rounds,
            )
            self.memories = TeamMemory.create_for_all_teams(battle_map, event)

            initiative.roll_initiative()
            event.broadcast("CombatStarted", {"round": initiative.round})

        self._prev_enemy_hp = {
            id(c): c.hp
            for _, c in self.cm.initiative.initiative_order
            if c.team != self.trained_team
        }
        self._done = False
        return self._get_obs_for_next_trained_creature()

    def run_episode(self, selector: "StrategySelector | None" = None) -> float:
        """Run one full episode. Returns total shaped reward."""
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

        won       = any(c.team == self.trained_team for c in survivors)
        timed_out = self.cm.timed_out

        enemies_killed  = sum(1 for c in enemies if not c.is_alive())
        enemy_attrition = enemies_killed / len(enemies) if enemies else 0.0

        rc = self.reward_cfg
        if won and not timed_out:
            reward = rc.win
        elif timed_out:
            trained_alive = [c for c in survivors if c.team == self.trained_team]
            hp_fraction   = (sum(c.hp for c in trained_alive) /
                             sum(c.max_hp for c in trained_alive)) if trained_alive else 0.0
            reward = rc.timeout * hp_fraction
        else:
            reward = rc.loss + rc.attrition_scale * enemy_attrition

        for c in enemies:
            hp_lost = c.max_hp - c.hp
            reward += hp_lost * rc.damage_scale
            if not c.is_alive():
                reward += rc.kill

        self._won             = won and not timed_out
        self._timed_out       = timed_out
        self._enemy_attrition = enemy_attrition
        return reward

    def _outcome_reward(self) -> float:
        """Outcome reward without per-turn shaping — used for Q-updates."""
        all_creatures = [c for _, c in self.cm.initiative.initiative_order]
        survivors     = [c for c in all_creatures if c.is_alive()]
        enemies       = [c for c in all_creatures if c.team != self.trained_team]
        won           = any(c.team == self.trained_team for c in survivors)
        timed_out     = self.cm.timed_out
        enemies_killed  = sum(1 for c in enemies if not c.is_alive())
        enemy_attrition = enemies_killed / len(enemies) if enemies else 0.0
        rc = self.reward_cfg
        if won and not timed_out:
            return rc.win
        elif timed_out:
            trained_alive = [c for c in survivors if c.team == self.trained_team]
            hp_fraction   = (sum(c.hp for c in trained_alive) /
                             sum(c.max_hp for c in trained_alive)) if trained_alive else 0.0
            return rc.timeout * hp_fraction
        else:
            return rc.loss + rc.attrition_scale * enemy_attrition

    def step(self, action: Strategy):
        """
        Gym-style interface: apply action for the next trained-team creature,
        run opponents until the next trained creature's turn or end of combat.
        Returns (obs, reward, done, info).
        """
        if self._done:
            raise RuntimeError("Call reset() before step() after episode ends.")

        reward = self.reward_cfg.step

        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf) if self.silent else contextlib.nullcontext()

        with ctx:
            order = self.cm.initiative.initiative_order
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
            reward += self.reward_cfg.win if won else self.reward_cfg.loss

        obs  = self._get_obs_for_next_trained_creature()
        info = {"round": self.cm.initiative.round}
        return obs, reward, done, info

    def _outcome_won(self) -> bool:
        return getattr(self, "_won", False)

    def _damage_reward(self) -> float:
        reward = 0.0
        for _, c in self.cm.initiative.initiative_order:
            if c.team == self.trained_team:
                continue
            prev  = self._prev_enemy_hp.get(id(c), c.hp)
            delta = prev - c.hp
            if delta > 0:
                reward += delta * self.reward_cfg.damage_scale
                if not c.is_alive():
                    reward += self.reward_cfg.kill
            self._prev_enemy_hp[id(c)] = c.hp
        return reward

    def _get_obs_for_next_trained_creature(self) -> list[float]:
        for _, c in self.cm.initiative.initiative_order:
            if c.team == self.trained_team and c.is_alive():
                memory  = self.memories.get(self.trained_team)
                enemies = self.cm.battle_map.enemies_of(c)
                allies  = [
                    x for _, x in self.cm.initiative.initiative_order
                    if x.team == self.trained_team and x is not c and x.is_alive()
                ]
                if memory:
                    max_rounds = self.scenario_data.get("max_rounds", 30)
                    return memory.get_state_vector(c, enemies, allies,
                                                   max_rounds=max_rounds)
                break
        return [0.0] * 12


# ---------------------------------------------------------------------------
# TrainingLog
# ---------------------------------------------------------------------------

class TrainingLog:
    """
    Records per-episode or per-generation training stats.
    Supports CSV/JSON export and matplotlib convergence plots.
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
        import time
        entry = dict(kwargs)
        if self._start_ts is not None:
            entry.setdefault("elapsed_s", round(time.time() - self._start_ts, 1))
        self.episodes.append(entry)

    def save_csv(self, path: str) -> None:
        import csv
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
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"name": self.name, "entries": self.episodes}, f, indent=2)
        print(f"  [Log] JSON saved → {path}")

    @classmethod
    def load_json(cls, path: str) -> "TrainingLog":
        with open(path) as f:
            data = json.load(f)
        log = cls(name=data.get("name", path))
        log.episodes = data.get("entries", [])
        return log

    @classmethod
    def load_csv(cls, path: str) -> "TrainingLog":
        import csv
        name = os.path.splitext(os.path.basename(path))[0]
        log  = cls(name=name)
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

    def plot(
        self,
        smoothing: int = 20,
        save_path: str | None = None,
        show: bool = True,
    ) -> None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("  [Log] matplotlib not available — skipping plot")
            return

        if not self.episodes:
            print("  [Log] nothing to plot yet")
            return

        is_rl  = "reward"     in self.episodes[0]
        is_evo = "generation" in self.episodes[0]

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

            wins     = [e.get("win", 0) for e in self.episodes]
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


