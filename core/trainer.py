from __future__ import annotations

import numpy as np

from core.ml_strategy import CombatEnv, StrategySelector, TrainingLog
from core.selectors.rl_selector import RLStrategySelector, _rl_train_worker
from core.selectors.evo_selector import EvolutionarySelector, _evo_fitness_worker


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
        log: TrainingLog | None = None,
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

            chunk     = n_episodes // workers
            remainder = n_episodes % workers
            chunks    = [chunk + (1 if i < remainder else 0) for i in range(workers)]
            sel          = self.selector
            report_every = max(50, chunks[0] // 40)

            _mgr           = multiprocessing.Manager()
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

            if log is not None:
                ep_r, ep_w, ep_e = worker_results[0][1:]
                for i, (r, w, e) in enumerate(zip(ep_r, ep_w, ep_e)):
                    log.record(episode=i + 1, reward=r, win=w, epsilon=e)
                print(f"\n  {log.summary()}")

            return worker_results[0][1]

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
            G   = self.env._outcome_reward()
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
        log: TrainingLog | None = None,
        workers:         int  = 1,
    ) -> list[float]:
        """
        Evolutionary training. Each individual is scored by win-rate over
        combats_per_ind episodes. Elite individuals are kept and mutated.

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
                pop_sz  = self.selector.pop_sz
                fut_map = {
                    _pool.submit(_evo_fitness_worker,
                                 (self.env.scenario_data,
                                  self.selector.get_individual(idx).tolist(),
                                  self.env.trained_team, combats_per_ind)): idx
                    for idx in range(pop_sz)
                }
                fitness     = [0.0] * pop_sz
                done        = 0
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
                        if self.env.run_episode(selector=self.selector) > 0:
                            wins += 1
                    fitness.append(wins / combats_per_ind)

            best       = max(fitness)
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

    # -- DQN training ------------------------------------------------------

    def train_dqn(
        self,
        n_episodes:  int  = 500,
        verbose:     bool = True,
        print_every: int  = 50,
        log: TrainingLog | None = None,
    ) -> list[float]:
        """
        DQN training via experience replay.

        Records (obs, action) pairs during each episode using the same
        instrumented-selector approach as train_rl(), then pushes all
        transitions to the replay buffer with the fractional outcome reward
        and runs a minibatch gradient step. This gives DQN's replay +
        target-network stability benefits while reusing the existing
        run_episode() interface.

        Pass log=TrainingLog("run_name") to record per-episode stats.
        Returns list of per-episode total rewards.
        """
        from core.selectors.dqn_selector import DQNStrategySelector
        assert isinstance(self.selector, DQNStrategySelector), \
            "train_dqn requires a DQNStrategySelector"

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
            ep_reward = self.env.run_episode(selector=self.selector)
            outcome   = self.env._outcome_reward()
            won       = self.env._outcome_won()

            # Push every (obs, action) pair from this episode to the buffer.
            # All transitions get the fractional outcome reward; the final
            # transition is marked done=True so the target Q is not bootstrapped.
            n = len(trajectory)
            for i, (obs, action) in enumerate(trajectory):
                is_last  = (i == n - 1)
                next_obs = trajectory[i + 1][0] if not is_last else obs
                self.selector.update(obs, action, outcome, next_obs, done=is_last)

            self.selector.decay_epsilon()
            episode_rewards.append(ep_reward)

            if log is not None:
                log.record(
                    episode=ep + 1,
                    reward=ep_reward,
                    win=int(won),
                    epsilon=round(self.selector.eps, 4),
                )

            if verbose and (ep + 1) % print_every == 0:
                recent   = episode_rewards[-print_every:]
                win_rate = sum(1 for r in recent if r > 0) / len(recent)
                print(
                    f"  [DQN] ep {ep+1}/{n_episodes}  "
                    f"avg_reward={np.mean(recent):.3f}  "
                    f"win_rate={win_rate:.0%}  "
                    f"eps={self.selector.eps:.3f}"
                )

        self.selector.select = _orig_select
        if log is not None:
            print(f"\n  {log.summary()}")
        return episode_rewards
