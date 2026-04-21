import os
import json
from argparse import ArgumentParser

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.battle_map import BattleMap
from core.tile import Tile
from core.combat_manager import CombatManager, CombatMode
from data.features.base import *
from data.features.fighter_features import ActionSurge, SecondWind
from data.monsters.monsters import *
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader
from utils.battle_visualiser import BattleVisualiser


def load_json(filename):
    path = os.path.join("scenarios", filename)
    with open(path, "r") as f:
        return json.load(f)


def build_map(scenario_data) -> BattleMap:
    """
    Build a BattleMap from the scenario's optional 'map' block.
    Falls back to a sensible default if no map is defined.

    Scenario map format:
        "map": {
            "width": 20,
            "height": 20,
            "difficult_terrain": [[5,3,3,4]],   // [col, row, w, h]
            "walls":             [[10,0,1,20]]
        }
    """
    map_data = scenario_data.get("map", {})
    width  = map_data.get("width",  20)
    height = map_data.get("height", 20)
    bmap   = BattleMap(width, height)

    for col, row, w, h in map_data.get("walls", []):
        bmap.set_rect(col, row, w, h, Tile.wall())
    for col, row, w, h in map_data.get("difficult_terrain", []):
        bmap.set_rect(col, row, w, h, Tile.difficult())

    return bmap


def _find_placement_squares(
    battle_map, start_col: int, col_range: int, count: int
) -> list[tuple[int, int]]:
    """
    Find `count` empty, passable squares in the column band
    [start_col, start_col + col_range).  Scans row by row, left to right.
    Raises ValueError if there aren't enough free squares.
    """
    found = []
    for row in range(battle_map.height):
        for col in range(start_col, min(start_col + col_range, battle_map.width)):
            if not battle_map._in_bounds(col, row):
                continue
            if not battle_map.get_tile(col, row).passable:
                continue
            if battle_map.get_creature_at(col, row) is not None:
                continue
            found.append((col, row))
            if len(found) == count:
                return found
    raise ValueError(
        f"Not enough free squares in columns {start_col}–"
        f"{start_col + col_range - 1} to place {count} creatures "
        f"(only found {len(found)}). Widen the map or add positions to the scenario JSON."
    )


def place_creatures(scenario_data, players, monsters, battle_map) -> None:
    """
    Place creatures on the map from the scenario's 'positions' block.
    Falls back to auto-placement if positions aren't specified.

    Scenario positions format:
        "positions": {
            "Brendiir":  [2, 10],
            "monsters":  [[10, 8], [12, 10]]
        }
    """
    positions    = scenario_data.get("positions", {})
    map_w        = battle_map.width
    map_h        = battle_map.height

    # Work out how many creatures need auto-placement in each zone
    players_needing_auto  = [p for p in players  if p.name not in positions]
    monsters_needing_auto = [
        m for i, m in enumerate(monsters)
        if i >= len(positions.get("monsters", []))
    ]

    # Auto-place players on the left quarter, monsters on the right quarter
    player_zone_w  = max(4, map_w // 5)
    monster_zone_w = max(4, map_w // 5)
    monster_start  = map_w - monster_zone_w

    if players_needing_auto:
        auto_player_squares = _find_placement_squares(
            battle_map, start_col=1,
            col_range=player_zone_w,
            count=len(players_needing_auto),
        )
    else:
        auto_player_squares = []

    if monsters_needing_auto:
        auto_monster_squares = _find_placement_squares(
            battle_map, start_col=monster_start,
            col_range=monster_zone_w,
            count=len(monsters_needing_auto),
        )
    else:
        auto_monster_squares = []

    # Place players
    auto_pi = 0
    for player in players:
        if player.name in positions:
            col, row = positions[player.name]
        else:
            col, row = auto_player_squares[auto_pi]
            auto_pi += 1
        battle_map.place(player, col, row)
        print(f"  Placed {player.name} at ({col}, {row})")

    # Place monsters
    explicit_monster_positions = positions.get("monsters", [])
    auto_mi = 0
    for i, monster in enumerate(monsters):
        if i < len(explicit_monster_positions):
            col, row = explicit_monster_positions[i]
        else:
            col, row = auto_monster_squares[auto_mi]
            auto_mi += 1
        battle_map.place(monster, col, row)
        print(f"  Placed {monster.name} at ({col}, {row})")


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
        mtype = tmpl.get("type", "")
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

    if not args.no_vis:
        BattleVisualiser(battle_map, event, cm,save_video=True)

    outcome = cm.run()
    print(f"\nOutcome: {outcome}")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--json",   required=True, help="Scenario JSON filename")
    parser.add_argument("--player", action="store_true",
                        help="Enable player-input mode for blue team (default: auto)")
    parser.add_argument("--no-vis", action="store_true",
                        help="Disable the matplotlib battle map visualiser")
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