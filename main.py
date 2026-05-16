import os
import json
from argparse import ArgumentParser

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.battle_map import BattleMap
from core.tile import Tile
from core.combat_manager import CombatManager, CombatMode
from data.features.base import Feature

# Auto-register all features by importing every module in data/features/.
# Features self-register via __init_subclass__ when their module is loaded —
# we don't need the names here, just need Python to execute the files.
import importlib, pkgutil, data.features
for _module_info in pkgutil.iter_modules(data.features.__path__):
    if _module_info.name != "base":
        importlib.import_module(f"data.features.{_module_info.name}")
from data.monsters.monsters import *
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader
from utils.battle_visualiser import BattleVisualiser


def load_json(filename):
    path = os.path.join("scenarios", filename)
    with open(path, "r") as f:
        return json.load(f)


def _eval_worker(args_tuple):
    """Module-level function so ProcessPoolExecutor can pickle it on Windows."""
    import io, contextlib
    scenario_data, weights_path, method, team, n = args_tuple
    from core.ml_strategy import CombatEnv, Strategy
    from core.selectors.rl_selector import RLStrategySelector
    from core.selectors.evo_selector import EvolutionarySelector
    from core.selectors.dqn_selector import DQNStrategySelector
    env = CombatEnv(scenario_data=scenario_data, trained_team=team, silent=True)
    if method == "evo":
        sel = EvolutionarySelector()
    elif method == "dqn":
        sel = DQNStrategySelector()
        sel.eps = 0.0
    else:
        sel = RLStrategySelector()
        sel.eps = 0.0
    with contextlib.redirect_stdout(io.StringIO()):
        sel.load(weights_path)
    wins = 0
    total_rounds = 0
    tactic_counts = {s: 0 for s in Strategy}
    for _ in range(n):
        env.run_episode(selector=sel)
        if env._outcome_won():
            wins += 1
        if env.cm is not None:
            total_rounds += env.cm.initiative.round
    for s, c in sel.tactic_counts.items():
        tactic_counts[s] += c
    return wins, {s.name: c for s, c in tactic_counts.items()}, total_rounds


def _baseline_worker(args_tuple):
    scenario_data, team, n = args_tuple
    from core.ml_strategy import CombatEnv
    env = CombatEnv(scenario_data=scenario_data, trained_team=team, silent=True)
    wins = 0
    total_rounds = 0
    for _ in range(n):
        env.run_episode(selector=None)
        if env._outcome_won():
            wins += 1
        if env.cm is not None:
            total_rounds += env.cm.initiative.round
    return wins, total_rounds


# build_map, place_creatures and _find_placement_squares live in scenarioLoader
# so CombatEnv can import them without importing main.py (which would re-run
# the CLI argument parser and cause AttributeError on args.player etc.)
from utils.scenarioLoader import build_map, place_creatures


def main(args):
    event   = EventBus()
    factory = CreatureFactory()

    scenario_data       = load_json(args.json)
    loader              = ScenarioLoader(factory, event)
    players, monsters   = loader.load(scenario_data)

    # Attach monster attack templates so TacticalAI can see them.
    # weapon_role controls which weapons each monster gets:
    #   "all"    -> every weapon in the template (original behaviour)
    #   "melee"  -> melee attacks only
    #   "ranged" -> ranged attacks only
    #   "random" -> one weapon type chosen randomly per monster (default)
    import random as _random
    monster_templates = scenario_data.get("monsters", [])
    monster_idx = 0
    for tmpl in monster_templates:
        mtype = tmpl.get("type", "").upper()
        count = tmpl.get("count", 1)
        role  = tmpl.get("weapon_role", "random")

        if mtype not in MONSTER_REGISTRY:
            monster_idx += count
            continue

        all_attacks    = MONSTER_REGISTRY[mtype].get("attacks", [])
        melee_attacks  = [a for a in all_attacks if a.get("attack_type", "melee") == "melee"]
        ranged_attacks = [a for a in all_attacks if a.get("attack_type", "melee") != "melee"]

        for _ in range(count):
            if monster_idx >= len(monsters):
                break
            monster = monsters[monster_idx]

            if role == "all":
                monster._attack_templates = all_attacks
            elif role == "melee":
                monster._attack_templates = melee_attacks or all_attacks
            elif role == "ranged":
                monster._attack_templates = ranged_attacks or all_attacks
            else:  # "random"
                if melee_attacks and ranged_attacks:
                    pool = _random.choice([melee_attacks, ranged_attacks])
                else:
                    pool = all_attacks
                monster._attack_templates = pool
                role_label = "melee" if pool is melee_attacks else "ranged"
                print(f"  {monster.name} assigned as {role_label} fighter")

            monster_idx += 1

    # Build map and place everyone
    battle_map = build_map(scenario_data)
    print("\n  Placing creatures...")
    place_creatures(scenario_data, players, monsters, battle_map)

    print("\n  Initial map:")
    battle_map.print_grid()

    # Set up initiative and combat
    initiative = InitiativeManager(players + monsters, event)

    mode = CombatMode.PLAYER if args.player else CombatMode.AUTO
    cm = CombatManager(event, initiative, battle_map, mode=mode)

    # ── Attach trained model if supplied ────────────────────────────────
    if getattr(args, "load", None):
        from core.selectors.rl_selector import RLStrategySelector
        from core.selectors.evo_selector import EvolutionarySelector
        from core.selectors.dqn_selector import DQNStrategySelector
        from core.team_memory import TeamMemory
        method = getattr(args, "method", "rl")
        if method == "evo":
            sel = EvolutionarySelector()
        elif method == "dqn":
            sel = DQNStrategySelector()
        else:
            sel = RLStrategySelector()
        sel.load(args.load)
        sel.eps = 0.0   # pure exploitation — no random moves during a single run
        cm.ai.strategy_selector = sel
        cm.ai.trained_team = args.team   # gate selector to trained team only
        # Ensure TeamMemory exists for the trained team so get_state_vector works
        if args.team not in cm.memories:
            cm.memories = TeamMemory.create_for_all_teams(battle_map, event)
        print(f"  [ML] Loaded {method.upper()} policy from {args.load} "
              f"-> controlling team '{args.team}' (eps=0)")

    # ── Visualiser (optional; handles save_video internally) ────────────
    if not args.no_vis:
        save_video = getattr(args, "save_video", False)
        video_path = getattr(args, "video_path", "combat.mp4")
        BattleVisualiser(battle_map, event, cm,
                         save_video=save_video,
                         video_path=video_path)

    # ── Structured JSONL event log (optional) ───────────────────────────
    log_json_path = getattr(args, "log_json", None)
    combat_logger = None
    if log_json_path:
        from utils.combat_logger import CombatLogger
        os.makedirs(os.path.dirname(log_json_path) or ".", exist_ok=True)
        combat_logger = CombatLogger(event, initiative, log_json_path)
        print(f"  [Log] JSONL event log -> {log_json_path}")

    outcome = cm.run()
    print(f"\nOutcome: {outcome}")

    if combat_logger:
        combat_logger.close()

    # ── Combat log (optional JSON) ───────────────────────────────────────
    log_path = getattr(args, "log_path", None)
    if log_path:
        all_creatures = [c for _, c in cm.initiative.initiative_order]
        survivors     = [c for c in all_creatures if c.is_alive()]
        winning_team  = survivors[0].team if survivors else None
        log_data = {
            "scenario":     args.json,
            "outcome":      outcome,
            "winning_team": winning_team,
            "rounds":       cm.initiative.round - 1,
            "trained_team": getattr(args, "team", None),
            "model":        getattr(args, "load", None),
            "creatures": [
                {
                    "name":     c.name,
                    "team":     c.team,
                    "survived": c.is_alive(),
                    "hp_final": c.hp,
                    "hp_max":   c.max_hp,
                }
                for c in all_creatures
            ],
        }
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"  [Log] Combat log saved → {log_path}")


def run_training(args):
    """Train a strategy selector using RL or evolutionary search."""
    import os
    from core.ml_strategy import CombatEnv, TrainingLog
    from core.selectors.rl_selector import RLStrategySelector
    from core.selectors.evo_selector import EvolutionarySelector
    from core.selectors.dqn_selector import DQNStrategySelector
    from core.trainer import StrategyTrainer

    # Load one or more training scenarios.  Multiple --json files are mixed
    # each episode so the policy generalises across encounters.
    scenario_list = [load_json(j) for j in args.json]
    os.makedirs(args.save_dir, exist_ok=True)

    base_name = os.path.splitext(args.json[0])[0] if len(args.json) == 1 else "multi"
    run_name  = args.run_name or base_name
    log       = TrainingLog(name=run_name, trained_team=args.team)

    env = CombatEnv(
        scenario_data=scenario_list,   # list → random pick per episode
        trained_team=args.team,
        silent=not args.verbose,
    )

    if args.method == "rl":
        sel = RLStrategySelector(
            n_bins    = args.bins,
            alpha     = args.alpha,
            gamma     = args.gamma,
            eps       = args.eps,
            eps_min   = args.eps_min,
            eps_decay = args.eps_decay,
        )
        if args.load:
            sel.load(args.load)

        trainer = StrategyTrainer(env, sel)
        trainer.train_rl(
            n_episodes  = args.episodes,
            verbose     = True,
            print_every = args.print_every,
            log         = log,
            workers     = args.workers,
        )

        weights_path = os.path.join(args.save_dir, f"{run_name}_rl.npy")
        sel.save(weights_path)

    elif args.method == "evo":
        sel = EvolutionarySelector(
            pop_size       = args.pop_size,
            elite_frac     = args.elite_frac,
            mutation_scale = args.mutation_scale,
            crossover_rate = args.crossover_rate,
        )
        if args.load:
            sel.load(args.load)

        trainer = StrategyTrainer(env, sel)
        trainer.train_evolutionary(
            n_gens          = args.generations,
            combats_per_ind = args.combats_per_ind,
            verbose         = True,
            log             = log,
            workers         = args.workers,
        )

        weights_path = os.path.join(args.save_dir, f"{run_name}_evo.npy")
        sel.save(weights_path)

    elif args.method == "dqn":
        sel = DQNStrategySelector(
            hidden             = tuple(args.dqn_hidden),
            lr                 = args.dqn_lr,
            gamma              = args.gamma,
            eps                = args.eps,
            eps_min            = args.eps_min,
            eps_decay          = args.eps_decay,
            buffer_size        = args.dqn_buf,
            batch_size         = args.dqn_batch,
            target_update_freq = args.dqn_target_freq,
        )
        if args.load:
            sel.load(args.load)

        trainer = StrategyTrainer(env, sel)
        trainer.train_dqn(
            n_episodes  = args.episodes,
            verbose     = True,
            print_every = args.print_every,
            log         = log,
        )

        weights_path = os.path.join(args.save_dir, f"{run_name}_dqn.pt")
        sel.save(weights_path)

    # Always save the log
    log_csv  = os.path.join(args.save_dir, f"{run_name}_log.csv")
    log_json = os.path.join(args.save_dir, f"{run_name}_log.json")
    log.save_csv(log_csv)
    log.save_json(log_json)

    if args.plot:
        plot_path = os.path.join(args.save_dir, f"{run_name}_convergence.png")
        log.plot(smoothing=args.smoothing, save_path=plot_path, show=False)


def run_evaluation(args):
    """
    Evaluate a trained selector with epsilon frozen at 0 (pure exploitation),
    then compare against a random baseline so you can see how much the policy
    actually learned above chance.

    Usage:
        python main.py eval --json brendiir_vs_goblins.json --load saves/brendiir_vs_goblins_rl.npy
    """
    import math
    from core.ml_strategy import Strategy

    scenario_data = load_json(args.json)

    def _confidence_interval(p, n, z=1.96):
        se = math.sqrt(p * (1 - p) / n) if n > 0 else 0
        return se * z

    def _print_stats(label, wins, n, avg_rounds=None):
        rate = wins / n
        ci   = _confidence_interval(rate, n)
        std  = math.sqrt(rate * (1 - rate))
        print(f"  {label}")
        print(f"    Win rate   : {rate:.1%}  ({wins}/{n})")
        print(f"    Std dev    : {std:.3f}  (per-episode Bernoulli σ)")
        print(f"    95% CI     : [{max(0, rate-ci):.1%}, {min(1, rate+ci):.1%}]")
        if avg_rounds is not None:
            print(f"    Avg rounds : {avg_rounds:.1f}")

    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed

    workers    = getattr(args, "workers", 1)
    chunk_size = max(1, min(20, args.n // 20))  # ~20 progress updates total

    def _make_chunks(total):
        """Split total into chunk_size pieces, last chunk absorbs remainder."""
        sizes = []
        remaining = total
        while remaining > 0:
            sizes.append(min(chunk_size, remaining))
            remaining -= chunk_size
        return sizes

    def _run_with_progress(label, total, futures_fn):
        """Submit tasks, collect results via as_completed, print live progress."""
        chunks      = _make_chunks(total)
        futures     = futures_fn(chunks)
        chunk_map   = {id(f): chunks[i] for i, f in enumerate(futures)}
        wins        = 0
        total_rounds = 0
        tactic_counts = {s: 0 for s in Strategy}
        done        = 0
        t0          = time.perf_counter()
        w_str       = f"{workers} worker{'s' if workers > 1 else ''}"
        print(f"\n  {label}  ({total} eps, {w_str}, chunk={chunk_size})")
        for fut in as_completed(futures):
            result = fut.result()
            if len(result) == 3:
                w, counts, rounds = result
                for name, c in counts.items():
                    tactic_counts[Strategy[name]] += c
            else:
                w, rounds = result
            wins         += w
            total_rounds += rounds
            done         += chunk_map[id(fut)]
            pct     = done / total
            bar     = ("█" * int(pct * 25)).ljust(25)
            wr      = wins / done if done else 0
            elapsed = time.perf_counter() - t0
            eta     = (elapsed / done * (total - done)) if done else 0
            print(f"\r    [{bar}] {done:>{len(str(total))}}/{total}  "
                  f"win rate: {wr:.1%}  elapsed: {elapsed:.0f}s  eta: {eta:.0f}s",
                  end="", flush=True)
        print()
        return wins, tactic_counts, total_rounds

    def _submit_trained(chunks):
        executor = ProcessPoolExecutor(max_workers=workers)
        futs = [
            executor.submit(_eval_worker,
                            (scenario_data, args.load, args.method, args.team, c))
            for c in chunks
        ]
        _submit_trained._executor = executor
        return futs

    def _submit_baseline(chunks):
        executor = ProcessPoolExecutor(max_workers=workers)
        futs = [
            executor.submit(_baseline_worker, (scenario_data, args.team, c))
            for c in chunks
        ]
        _submit_baseline._executor = executor
        return futs

    # ── Trained-policy evaluation ────────────────────────────────────────
    trained_wins, tactic_counts, trained_rounds = _run_with_progress(
        "Trained policy (ε=0)", args.n, _submit_trained
    )
    _submit_trained._executor.shutdown(wait=False)
    trained_rate       = trained_wins / args.n
    trained_avg_rounds = trained_rounds / args.n
    total_tactics      = sum(tactic_counts.values())

    # ── Random baseline ──────────────────────────────────────────────────
    random_wins, _, random_rounds = _run_with_progress(
        "Random baseline", args.n, _submit_baseline
    )
    _submit_baseline._executor.shutdown(wait=False)
    random_rate       = random_wins / args.n
    random_avg_rounds = random_rounds / args.n

    # ── Build results dict ───────────────────────────────────────────────
    def _stats_dict(wins, n):
        p  = wins / n
        ci = _confidence_interval(p, n)
        return {
            "wins": wins, "episodes": n,
            "win_rate": round(p, 4),
            "std_dev":  round(math.sqrt(p * (1 - p)), 4),
            "ci_95_lo": round(max(0.0, p - ci), 4),
            "ci_95_hi": round(min(1.0, p + ci), 4),
        }

    tactic_pcts = {
        s.name: {
            "count": tactic_counts.get(s, 0),
            "pct":   round(tactic_counts.get(s, 0) / total_tactics, 4)
                     if total_tactics > 0 else 0.0,
        }
        for s in Strategy
    }

    results = {
        "scenario":        args.json,
        "weights":         args.load,
        "method":          args.method,
        "trained_team":    args.team,
        "trained_policy":  {**_stats_dict(trained_wins, args.n),
                            "avg_rounds": round(trained_avg_rounds, 2)},
        "random_baseline": {**_stats_dict(random_wins, args.n),
                            "avg_rounds": round(random_avg_rounds, 2)},
        "improvement":     round(trained_rate - random_rate, 4),
        "tactic_counts":   tactic_pcts,
        "total_tactic_turns": total_tactics,
    }

    # ── Print report ─────────────────────────────────────────────────────
    delta = results["improvement"]
    sep   = f"  {'─'*44}"
    print(f"\n{sep}")
    _print_stats("Trained policy:", trained_wins, args.n, trained_avg_rounds)
    print()
    _print_stats("Random baseline:", random_wins, args.n, random_avg_rounds)
    print(f"\n  Improvement over random : {delta:+.1%}")
    if delta > 0.05:
        print("  ✓ Policy learned something meaningful above chance.")
    elif delta > 0:
        print("  ~ Marginal improvement — consider more training episodes.")
    else:
        print("  ✗ Policy is no better than random — training has not converged.")

    print(f"\n  Tactic selections ({total_tactics} total turns):")
    for strategy in Strategy:
        count = tactic_counts.get(strategy, 0)
        pct   = count / total_tactics if total_tactics > 0 else 0
        bar   = "█" * int(pct * 30)
        print(f"    {strategy.name:<12} {count:>6}  ({pct:.1%})  {bar}")
    print(sep)

    # ── Save JSON ────────────────────────────────────────────────────────
    if getattr(args, "output", None):
        import json
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Results saved → {args.output}")

    # ── Save plot ────────────────────────────────────────────────────────
    if getattr(args, "plot", None):
        try:
            import matplotlib.pyplot as plt
            import numpy as np

            fig, (ax_w, ax_t) = plt.subplots(1, 2, figsize=(13, 5))
            scenario_name = os.path.splitext(args.json)[0]
            fig.suptitle(
                f"Eval — {scenario_name}  ({args.method.upper()}, n={args.n})",
                fontweight="bold",
            )

            # Left: win rate comparison with 95% CI error bars
            labels = ["Trained policy", "Random baseline"]
            rates  = [trained_rate, random_rate]
            cis    = [
                _confidence_interval(trained_rate, args.n),
                _confidence_interval(random_rate,  args.n),
            ]
            colors = ["steelblue", "gray"]
            bars   = ax_w.bar(labels, rates, color=colors, alpha=0.8, width=0.4)
            ax_w.errorbar(labels, rates, yerr=cis, fmt="none",
                          color="black", capsize=6, linewidth=2)
            for bar, rate in zip(bars, rates):
                ax_w.text(bar.get_x() + bar.get_width() / 2,
                          bar.get_height() + 0.01, f"{rate:.1%}",
                          ha="center", va="bottom", fontweight="bold")
            ax_w.set_ylim(0, min(1.0, max(rates) * 1.5 + 0.1))
            ax_w.set_ylabel("Win rate")
            ax_w.set_title("Win rate vs baseline  (95% CI)")
            ax_w.axhline(random_rate, color="gray", linestyle="--",
                         linewidth=1, alpha=0.5)

            # Right: tactic selection horizontal bar chart
            names  = [s.name for s in Strategy]
            counts = [tactic_counts.get(s, 0) for s in Strategy]
            pcts   = [c / total_tactics if total_tactics > 0 else 0 for c in counts]
            y_pos  = np.arange(len(names))
            ax_t.barh(y_pos, pcts, color="seagreen", alpha=0.8)
            ax_t.set_yticks(y_pos)
            ax_t.set_yticklabels(names)
            ax_t.set_xlabel("Fraction of turns")
            ax_t.set_title(f"Tactic selection  ({total_tactics} turns)")
            ax_t.set_xlim(0, max(pcts) * 1.3 if pcts else 1)
            for i, (p, c) in enumerate(zip(pcts, counts)):
                ax_t.text(p + 0.005, i, f"{p:.1%}  (n={c})",
                          va="center", fontsize=9)

            plt.tight_layout()
            os.makedirs(os.path.dirname(args.plot) or ".", exist_ok=True)
            fig.savefig(args.plot, dpi=150)
            plt.close(fig)
            print(f"  Plot saved → {args.plot}")
        except ImportError:
            print("  matplotlib not available — skipping plot")


if __name__ == "__main__":
    parser = ArgumentParser(
        description="D&D 5e encounter simulator — run a scenario or train AI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── run: play a single scenario ──────────────────────────────────────
    run_p = sub.add_parser("run", help="Run a single combat scenario")
    run_p.add_argument("--json",       required=True, help="Scenario JSON filename (in scenarios/)")
    run_p.add_argument("--player",     action="store_true",
                       help="Player controls blue team")
    run_p.add_argument("--no-vis",     action="store_true",
                       help="Disable the matplotlib visualiser")
    # Trained model
    run_p.add_argument("--load",       default=None,
                       help="Path to trained .npy weights file to use for --team")
    run_p.add_argument("--team",       default="red",
                       help="Which team the loaded model controls (default: red)")
    # Video / GIF output
    run_p.add_argument("--save-video", action="store_true",
                       help="Save the combat as mp4/gif via the visualiser")
    run_p.add_argument("--video-path", default="combat.mp4",
                       help="Output path for the video file (default: combat.mp4)")
    # Trained model method selector
    run_p.add_argument("--method",     choices=["rl", "evo", "dqn"], default="rl",
                       help="Selector type matching the weights file (default: rl)")
    # Combat log
    run_p.add_argument("--log-path",   default=None,
                       help="If given, write a JSON combat log to this path")
    run_p.add_argument("--log-json",   default=None,
                       help="If given, write a JSONL structured event log to this path")

    # ── train: ML training loop ──────────────────────────────────────────
    train_p = sub.add_parser("train", help="Train a strategy selector")
    train_p.add_argument("--json",      required=True, nargs="+",
                         help="Scenario JSON filename(s) in scenarios/. "
                              "Pass multiple to train across all scenarios.")
    train_p.add_argument("--method",    choices=["rl", "evo", "dqn"], default="rl",
                         help="Training method: rl (Q-table), evo (evolutionary), or dqn (deep Q-network)")
    train_p.add_argument("--team",      default="red",
                         help="Which team to train (default: red)")
    train_p.add_argument("--run-name",  default=None,
                         help="Name for log files (default: scenario filename)")
    train_p.add_argument("--save-dir",  default="saves",
                         help="Directory for weights + logs (default: saves/)")
    train_p.add_argument("--load",      default=None,
                         help="Path to existing weights file to resume from")
    train_p.add_argument("--plot",      action="store_true",
                         help="Save a convergence plot after training")
    train_p.add_argument("--smoothing", type=int, default=20,
                         help="Rolling-average window for convergence plot (default: 20)")
    train_p.add_argument("--verbose",   action="store_true",
                         help="Print every episode/generation during training")
    train_p.add_argument("--workers",   type=int, default=1,
                         help="Parallel worker processes (RL: averages independent runs; evo: parallel fitness eval)")
    # RL hyperparams
    rl_g = train_p.add_argument_group("RL hyperparameters")
    rl_g.add_argument("--episodes",    type=int,   default=500)
    rl_g.add_argument("--bins",        type=int,   default=3,
                      help="Q-table bins per observation feature")
    rl_g.add_argument("--alpha",       type=float, default=0.20)
    rl_g.add_argument("--gamma",       type=float, default=0.95)
    rl_g.add_argument("--eps",         type=float, default=1.0)
    rl_g.add_argument("--eps-min",     type=float, default=0.05)
    rl_g.add_argument("--eps-decay",   type=float, default=0.999)
    rl_g.add_argument("--print-every", type=int,   default=50)
    # Evo hyperparams
    evo_g = train_p.add_argument_group("Evolutionary hyperparameters")
    evo_g.add_argument("--generations",     type=int,   default=20)
    evo_g.add_argument("--combats-per-ind", type=int,   default=10)
    evo_g.add_argument("--pop-size",        type=int,   default=20)
    evo_g.add_argument("--elite-frac",      type=float, default=0.2)
    evo_g.add_argument("--mutation-scale",  type=float, default=0.1)
    evo_g.add_argument("--crossover-rate",  type=float, default=0.5,
                       help="Probability of uniform crossover between two elite parents (0=mutation only)")
    # DQN hyperparams
    dqn_g = train_p.add_argument_group("DQN hyperparameters")
    dqn_g.add_argument("--dqn-hidden",       type=int,   nargs="+", default=[64, 32],
                       help="Hidden layer sizes (default: 64 32)")
    dqn_g.add_argument("--dqn-lr",           type=float, default=1e-3,
                       help="Adam learning rate (default: 1e-3)")
    dqn_g.add_argument("--dqn-buf",          type=int,   default=10_000,
                       help="Replay buffer capacity (default: 10000)")
    dqn_g.add_argument("--dqn-batch",        type=int,   default=64,
                       help="Minibatch size (default: 64)")
    dqn_g.add_argument("--dqn-target-freq",  type=int,   default=100,
                       help="Target network hard-update frequency in episodes (default: 100)")

    # ── eval: evaluate a trained selector against a random baseline ──────
    eval_p = sub.add_parser("eval", help="Evaluate a trained selector (ε=0) vs random baseline")
    eval_p.add_argument("--json",   required=True, help="Scenario JSON filename (in scenarios/)")
    eval_p.add_argument("--load",   required=True, help="Path to trained .npy weights file")
    eval_p.add_argument("--method", choices=["rl", "evo", "dqn"], default="rl",
                        help="Selector type matching the weights file (default: rl)")
    eval_p.add_argument("--team",   default="red", help="Trained team (default: red)")
    eval_p.add_argument("--n",      type=int, default=200,
                        help="Number of evaluation episodes (default: 200)")
    eval_p.add_argument("--output",  default=None,
                        help="Save results to this JSON file path")
    eval_p.add_argument("--plot",    default=None,
                        help="Save win rate + tactic chart to this PNG path")
    eval_p.add_argument("--workers", type=int, default=1,
                        help="Parallel worker processes for faster evaluation (default: 1)")

    # ── plot: re-plot a saved training log ───────────────────────────────
    plot_p = sub.add_parser("plot", help="Re-plot a saved training log CSV")
    plot_p.add_argument("--log",       required=True, help="Path to training log CSV")
    plot_p.add_argument("--smoothing", type=int, default=500,
                        help="Rolling-average window (default: 500)")
    plot_p.add_argument("--output",    default=None,
                        help="Save plot to this path instead of showing it")

    # ── build: interactive character + scenario wizard ───────────────────
    sub.add_parser("build", help="Interactive wizard to create a custom character scenario")

    args = parser.parse_args()

    # Backwards-compat: if someone runs the old-style
    #   python main.py --json foo.json
    # instead of the new-style
    #   python main.py run --json foo.json
    # we get a clean error rather than "no attribute 'player'"
    if not hasattr(args, 'command') or args.command is None:
        parser.print_help()
        raise SystemExit(1)


    import time
    start_time = time.perf_counter()
    if args.command == "run":
        main(args)
    elif args.command == "build":
        from utils.character_builder import run_builder
        run_builder()
        raise SystemExit(0)
    elif args.command == "train":
        run_training(args)
    elif args.command == "eval":
        run_evaluation(args)
    elif args.command == "plot":
        from core.ml_strategy import TrainingLog
        log = TrainingLog.load_csv(args.log)
        log.plot(
            smoothing=args.smoothing,
            save_path=args.output,
            show=args.output is None,
        )
        if args.output:
            print(f"  Plot saved → {args.output}")
    stop_time = time.perf_counter()
    print(f"Process took: {(stop_time-start_time):.4f} seconds")