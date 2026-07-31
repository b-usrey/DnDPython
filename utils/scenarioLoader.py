from core.player_character import PlayerCharacter
from data.features.base import Feature
from data.monsters.monsters import *
from utils.load_item import load_item_json

class ScenarioLoader:
    def __init__(self, factory, event_manager):
        self.factory = factory
        self.event = event_manager

    def load(self, scenario_data):
        players = []
        monsters = []

        # Load player characters
        for pdata in scenario_data.get("players", []):
            # Accept both "features" (CLI builder) and "feats" (web builder)
            features = pdata.get("features") or pdata.get("feats") or []
            pc = PlayerCharacter(
                pdata["name"],
                pdata["classes"],
                pdata.get("subclasses", {}),
                pdata["stats"],
                self.event,
                pdata.get("choices", []),
                feats=features
            )
            # Apply racial speed if exported (web builder sets player.speed)
            if "speed" in pdata:
                pc.speed = pdata["speed"]
            # Load and equip items
            for item_name in pdata.get("items", []):
                item = load_item_json(item_name)
                pc.add_item(item)
            for eq_name in pdata.get("equipped", []):
                pc.equip_item(eq_name)

            # Compute AC from equipped armour + any misc bonuses already
            # applied by feature attach() calls (e.g. Ring of Protection)
            pc.setup_ac()
            pc._max_hp = int(pc._current_hp)

            # Features are already attached via PlayerCharacter.__init__ feats loop.

            players.append(pc)

        # Load monsters
        for mdata in scenario_data.get("monsters", []):
            mtype = mdata["type"].upper()
            if mtype not in MONSTER_REGISTRY:
                print(f"⚠ Monster type '{mdata['type']}' not found in MONSTER_REGISTRY")
                continue
            for _ in range(mdata.get("count", 1)):
                monsters.append(self.factory.create(MONSTER_REGISTRY[mtype], self.event))

        return players, monsters


# ---------------------------------------------------------------------------
# Map building and creature placement
# (shared between main.py and CombatEnv so neither imports the other)
# ---------------------------------------------------------------------------

def build_map(scenario_data):
    """Build a BattleMap from the scenario's optional 'map' block."""
    from core.battle_map import BattleMap
    from core.tile import Tile

    map_data = scenario_data.get("map", {})
    bmap     = BattleMap(map_data.get("width", 20), map_data.get("height", 20))
    for col, row, w, h in map_data.get("walls", []):
        bmap.set_rect(col, row, w, h, Tile.wall())
    for col, row, w, h in map_data.get("difficult_terrain", []):
        bmap.set_rect(col, row, w, h, Tile.difficult())
    return bmap


def _find_placement_squares(battle_map, start_col, col_range, count):
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
        f"(only found {len(found)})."
    )


def place_creatures(scenario_data, players, monsters, battle_map):
    """Place creatures on the map from the scenario's 'positions' block."""
    positions     = scenario_data.get("positions", {})
    map_w         = battle_map.width

    players_needing_auto  = [p for p in players if p.name not in positions]
    monsters_needing_auto = [
        m for i, m in enumerate(monsters)
        if i >= len(positions.get("monsters", []))
    ]

    player_zone_w  = max(4, map_w // 5)
    monster_zone_w = max(4, map_w // 5)
    monster_start  = map_w - monster_zone_w

    auto_player_squares  = _find_placement_squares(
        battle_map, 1, player_zone_w, len(players_needing_auto)
    ) if players_needing_auto else []
    auto_monster_squares = _find_placement_squares(
        battle_map, monster_start, monster_zone_w, len(monsters_needing_auto)
    ) if monsters_needing_auto else []

    auto_pi = 0
    for player in players:
        col, row = positions[player.name] if player.name in positions \
                   else auto_player_squares[auto_pi]
        if player.name not in positions:
            auto_pi += 1
        battle_map.place(player, col, row)
        print(f"  Placed {player.name} at ({col}, {row})")

    explicit = positions.get("monsters", [])
    auto_mi  = 0
    for i, monster in enumerate(monsters):
        if i < len(explicit):
            col, row = explicit[i]
        else:
            col, row = auto_monster_squares[auto_mi]
            auto_mi += 1
        battle_map.place(monster, col, row)
        print(f"  Placed {monster.name} at ({col}, {row})")