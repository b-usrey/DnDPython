from __future__ import annotations

import os
import random

import numpy as np

from core.ml_strategy import Strategy, N_STRATEGIES, StrategySelector


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
        crossover_rate  probability of uniform crossover between two elites
    """

    def __init__(self, n_features=15, pop_size=20,
                 elite_frac=0.2, mutation_scale=0.1, crossover_rate=0.5):
        super().__init__()
        self.n_obs          = n_features
        self.pop_sz         = pop_size
        self.elite_n        = max(1, int(pop_size * elite_frac))
        self.mut_std        = mutation_scale
        self.crossover_rate = crossover_rate
        self.W   = np.random.randn(n_features, N_STRATEGIES).astype(np.float32)
        self._pop = [
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
# Module-level worker (must be top-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _evo_fitness_worker(args):
    """Evaluate one evolutionary individual and return its win-rate."""
    import io, contextlib
    from core.ml_strategy import CombatEnv
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
