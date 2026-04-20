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
        from core.ml_strategy import RLStrategySelector
        from core.team_memory import TeamMemory
        sel = RLStrategySelector()
        sel.load(args.load)
        sel.eps = 0.0   # pure exploitation — no random moves during a single run
        cm.ai.strategy_selector = sel
        cm.ai.trained_team = args.team   # gate selector to trained team only
        # Ensure TeamMemory exists for the trained team so get_state_vector works
        if args.team not in cm.memories:
            cm.memories = TeamMemory.create_for_all_teams(battle_map, event)
        print(f"  [ML] Loaded policy from {args.load} → controlling team '{args.team}' (ε=0)")

    # ── Visualiser (optional; handles save_video internally) ────────────
    if not args.no_vis:
        save_video = getattr(args, "save_video", False)
        video_path = getattr(args, "video_path", "combat.mp4")
        BattleVisualiser(battle_map, event, cm,
                         save_video=save_video,
                         video_path=video_path)

    outcome = cm.run()
    print(f"\nOutcome: {outcome}")

    # ── Combat log (optional JSON) ───────────────────────────────────────
    log_path = getattr(args, "log_path", None)
    if log_path:
        import json, os
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
    from core.ml_strategy import (
        CombatEnv, RLStrategySelector, EvolutionarySelector,
        StrategyTrainer, TrainingLog,
    )

    scenario_data = load_json(args.json)
    os.makedirs(args.save_dir, exist_ok=True)

    run_name = args.run_name or os.path.splitext(args.json)[0]
    log      = TrainingLog(name=run_name, trained_team=args.team)

    env = CombatEnv(
        scenario_data=scenario_data,
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
        )

        weights_path = os.path.join(args.save_dir, f"{run_name}_rl.npy")
        sel.save(weights_path)

    elif args.method == "evo":
        sel = EvolutionarySelector(
            pop_size       = args.pop_size,
            elite_frac     = args.elite_frac,
            mutation_scale = args.mutation_scale,
        )
        if args.load:
            sel.load(args.load)

        trainer = StrategyTrainer(env, sel)
        trainer.train_evolutionary(
            n_gens          = args.generations,
            combats_per_ind = args.combats_per_ind,
            verbose         = True,
            log             = log,
        )

        weights_path = os.path.join(args.save_dir, f"{run_name}_evo.npy")
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
    from core.ml_strategy import CombatEnv, RLStrategySelector, TrainingLog

    scenario_data = load_json(args.json)

    env = CombatEnv(
        scenario_data=scenario_data,
        trained_team=args.team,
        silent=True,
    )

    sel = RLStrategySelector()
    sel.load(args.load)
    sel.eps = 0.0          # pure exploitation — no random actions

    # ── Trained-policy evaluation ────────────────────────────────────────
    print(f"\n  Evaluating trained policy over {args.n} episodes (ε=0)...")
    trained_wins = 0
    for i in range(args.n):
        env.run_episode(selector=sel)
        if env._outcome_won():
            trained_wins += 1
        if (i + 1) % (args.n // 10) == 0:
            print(f"    {i+1}/{args.n}  running win rate: {trained_wins/(i+1):.1%}")

    trained_rate = trained_wins / args.n

    # ── Random baseline ──────────────────────────────────────────────────
    print(f"\n  Evaluating random baseline over {args.n} episodes...")
    random_wins = 0
    for i in range(args.n):
        env.run_episode(selector=None)   # None → rule-based / random TacticalAI
        if env._outcome_won():
            random_wins += 1

    random_rate = random_wins / args.n

    # ── Report ───────────────────────────────────────────────────────────
    delta = trained_rate - random_rate
    print(f"\n  {'─'*40}")
    print(f"  Trained policy win rate : {trained_rate:.1%}  ({trained_wins}/{args.n})")
    print(f"  Random baseline win rate: {random_rate:.1%}  ({random_wins}/{args.n})")
    print(f"  Improvement over random : {delta:+.1%}")
    if delta > 0.05:
        print("  ✓ Policy learned something meaningful above chance.")
    elif delta > 0:
        print("  ~ Marginal improvement — consider more training episodes.")
    else:
        print("  ✗ Policy is no better than random — training has not converged.")
    print(f"  {'─'*40}\n")


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
    # Combat log
    run_p.add_argument("--log-path",   default=None,
                       help="If given, write a JSON combat log to this path")

    # ── train: ML training loop ──────────────────────────────────────────
    train_p = sub.add_parser("train", help="Train a strategy selector")
    train_p.add_argument("--json",      required=True,
                         help="Scenario JSON filename (in scenarios/)")
    train_p.add_argument("--method",    choices=["rl", "evo"], default="rl",
                         help="Training method: rl (Q-table) or evo (evolutionary)")
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

    # ── eval: evaluate a trained selector against a random baseline ──────
    eval_p = sub.add_parser("eval", help="Evaluate a trained selector (ε=0) vs random baseline")
    eval_p.add_argument("--json",   required=True, help="Scenario JSON filename (in scenarios/)")
    eval_p.add_argument("--load",   required=True, help="Path to trained .npy weights file")
    eval_p.add_argument("--team",   default="red", help="Trained team (default: red)")
    eval_p.add_argument("--n",      type=int, default=200,
                        help="Number of evaluation episodes (default: 200)")

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
    elif args.command == "train":
        run_training(args)
    elif args.command == "eval":
        run_evaluation(args)
    stop_time = time.perf_counter()
    print(f"Process took: {(stop_time-start_time):.4f} seconds")