"""
core/battle_map.py

Owns the spatial state of an encounter: the grid of Tiles and the
position of every Creature on it.

All spatial questions go through BattleMap — Creature never stores x, y.

    map = BattleMap(10, 10)
    map.place(goblin, 4, 4)
    map.place(brendiir, 7, 4)

    map.distance_between(goblin, brendiir)   # 15  (3 squares × 5ft)
    map.is_in_melee_range(goblin, brendiir)  # False

    oa_targets = map.move_creature(goblin, 5, 4)
    # returns list of creatures that get an opportunity attack
    # then updates goblin's position
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.tile import Tile

if TYPE_CHECKING:
    from core.creature import Creature  # avoid circular import at runtime


# ---------------------------------------------------------------------------
# RangeResult — returned by range checks so callers know *why* an attack
# is valid or invalid, not just True/False.
# ---------------------------------------------------------------------------

class RangeResult:
    def __init__(self, valid: bool, reason: str = "", disadvantage: bool = False):
        self.valid = valid
        self.reason = reason
        self.disadvantage = disadvantage   # ranged attack while in melee

    def __bool__(self):
        return self.valid

    def __repr__(self):
        flag = " [disadvantage]" if self.disadvantage else ""
        return f"RangeResult(valid={self.valid}, reason={self.reason!r}{flag})"


# ---------------------------------------------------------------------------
# BattleMap
# ---------------------------------------------------------------------------

class BattleMap:
    """
    A rectangular grid of Tiles with creature placement tracking.

    Coordinates are (col, row) with (0, 0) at top-left.
    Each square represents 5 feet.

    Args:
        width:  number of columns
        height: number of rows
        default_tile: tile type to fill the grid with (default: normal)
    """

    MELEE_REACH = 5       # feet — standard reach for most creatures
    SQUARE_SIZE = 5       # feet per grid square

    def __init__(self, width: int, height: int, default_tile: Tile | None = None):
        self.width = width
        self.height = height

        # Build grid as list-of-lists: grid[row][col]
        tile = default_tile or Tile.normal()
        self._grid: list[list[Tile]] = [
            [Tile(terrain_type=tile.terrain_type,
                  passable=tile.passable,
                  movement_cost=tile.movement_cost)
             for _ in range(width)]
            for _ in range(height)
        ]

        # Creature → (col, row).  Only creatures on the map appear here.
        self._positions: dict[Creature, tuple[int, int]] = {}

    # ------------------------------------------------------------------
    # Grid access
    # ------------------------------------------------------------------

    def get_tile(self, col: int, row: int) -> Tile:
        self._check_bounds(col, row)
        return self._grid[row][col]

    def set_tile(self, col: int, row: int, tile: Tile) -> None:
        self._check_bounds(col, row)
        self._grid[row][col] = tile

    def set_rect(self, col: int, row: int, w: int, h: int, tile: Tile) -> None:
        """Fill a rectangular region with a tile type."""
        for r in range(row, row + h):
            for c in range(col, col + w):
                if self._in_bounds(c, r):
                    self._grid[r][c] = Tile(
                        terrain_type=tile.terrain_type,
                        passable=tile.passable,
                        movement_cost=tile.movement_cost,
                    )

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------

    def place(self, creature: Creature, col: int, row: int) -> None:
        """
        Put a creature on the map at (col, row).
        Raises ValueError if the square is out of bounds or impassable.
        """
        self._check_bounds(col, row)
        tile = self._grid[row][col]
        if not tile.passable:
            raise ValueError(
                f"Cannot place {creature.name} on impassable tile at ({col}, {row})"
            )
        self._positions[creature] = (col, row)

    def remove(self, creature: Creature) -> None:
        """Remove a creature from the map (e.g. when downed or fleeing)."""
        self._positions.pop(creature, None)

    def get_position(self, creature: Creature) -> tuple[int, int] | None:
        """Return (col, row) for creature, or None if not on the map."""
        return self._positions.get(creature)

    def get_creature_at(self, col: int, row: int) -> Creature | None:
        """Return whichever creature occupies (col, row), or None."""
        for creature, pos in self._positions.items():
            if pos == (col, row):
                return creature
        return None

    def all_creatures(self) -> list[Creature]:
        return list(self._positions.keys())

    # ------------------------------------------------------------------
    # Distance & range
    # ------------------------------------------------------------------

    def distance_between(self, a: Creature, b: Creature) -> int:
        """
        Return the distance in feet between two creatures using
        Chebyshev distance (5e diagonal counting — diagonals cost 5ft).

        Raises LookupError if either creature isn't on the map.
        """
        pos_a = self._require_position(a)
        pos_b = self._require_position(b)
        return self._chebyshev_feet(pos_a, pos_b)

    def is_in_melee_range(self, attacker: Creature, target: Creature,
                           reach: int | None = None) -> bool:
        """
        True if target is within melee reach of attacker.
        reach defaults to MELEE_REACH (5ft). Pass 10 for polearm/whip reach.
        """
        effective_reach = reach if reach is not None else self.MELEE_REACH
        try:
            return self.distance_between(attacker, target) <= effective_reach
        except LookupError:
            return False

    def check_attack_range(
        self,
        attacker: Creature,
        target: Creature,
        is_ranged: bool,
        normal_range: int = 5,
        long_range: int | None = None,
    ) -> RangeResult:
        """
        Validate whether an attack can reach its target and flag disadvantage.

        For melee attacks:
          - Valid within normal_range (default 5ft / reach weapons pass 10)
          - Invalid beyond that

        For ranged attacks:
          - Valid within normal_range (full accuracy)
          - Valid within long_range but with disadvantage
          - Invalid beyond long_range
          - Disadvantage if attacker is in melee range of ANY enemy
            (the "shooting in melee" rule, PHB p.195)

        Returns a RangeResult with .valid, .reason, and .disadvantage.
        """
        try:
            dist = self.distance_between(attacker, target)
        except LookupError as e:
            return RangeResult(False, str(e))

        if not is_ranged:
            if dist <= normal_range:
                return RangeResult(True, "in melee range")
            return RangeResult(
                False,
                f"target is {dist}ft away, melee reach is {normal_range}ft"
            )

        # Ranged attack
        effective_long = long_range if long_range is not None else normal_range

        if dist > effective_long:
            return RangeResult(
                False,
                f"target is {dist}ft away, max range is {effective_long}ft"
            )

        disadvantage = False
        reason = f"target is {dist}ft away"

        # Disadvantage if any enemy is adjacent to the attacker
        if self._attacker_is_in_melee(attacker):
            disadvantage = True
            reason += " (ranged attack while in melee — disadvantage)"

        if long_range and dist > normal_range:
            disadvantage = True
            reason += f" (beyond normal range of {normal_range}ft — disadvantage)"

        return RangeResult(True, reason, disadvantage=disadvantage)

    def _attacker_is_in_melee(self, attacker: Creature) -> bool:
        """True if any enemy creature is within melee reach of attacker."""
        for other, _ in self._positions.items():
            if other is attacker:
                continue
            if other.team != attacker.team and self.is_in_melee_range(attacker, other):
                return True
        return False

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def move_creature(
        self,
        creature: Creature,
        new_col: int,
        new_row: int,
    ) -> list[Creature]:
        """
        Move creature to (new_col, new_row).

        Checks:
          1. Destination is in bounds and passable
          2. Which enemies had creature in their threatened square
             before the move (opportunity attack candidates)

        Returns a list of creatures that are entitled to an opportunity
        attack (they were threatening the mover's origin square and the
        mover is leaving their reach voluntarily).

        Does NOT automatically trigger the attacks — the caller
        (InitiativeManager / CombatManager) broadcasts the event and
        lets each creature decide whether to use their reaction.

        Raises:
          LookupError  if creature is not on the map
          ValueError   if destination is out of bounds or impassable
        """
        self._require_position(creature)
        self._check_bounds(new_col, new_row)

        dest_tile = self._grid[new_row][new_col]
        if not dest_tile.passable:
            raise ValueError(
                f"{creature.name} cannot move to ({new_col}, {new_row}): impassable"
            )

        # Find opportunity attack candidates before moving
        oa_targets = self._get_opportunity_attackers(creature, new_col, new_row)

        # NOTE: position is committed AFTER returning oa_targets so that
        # callers can execute OA attacks while the mover is still at their
        # origin square (correct range / adjacency for the attack roll).
        # CombatManager._try_move must commit the position itself after OAs.
        return oa_targets

    def commit_move(self, creature: Creature, new_col: int, new_row: int) -> None:
        """
        Commit a previously-validated move.  Called by CombatManager after
        opportunity attacks have been resolved so that OA range checks use
        the mover's origin square, not the destination.
        """
        self._positions[creature] = (new_col, new_row)

    def move_creature_immediate(
        self,
        creature: Creature,
        new_col: int,
        new_row: int,
    ) -> list:
        """
        Move creature immediately (no OA — used for forced movement,
        teleportation, etc.).
        """
        self._require_position(creature)
        self._check_bounds(new_col, new_row)
        dest_tile = self._grid[new_row][new_col]
        if not dest_tile.passable:
            raise ValueError(
                f"{creature.name} cannot move to ({new_col}, {new_row}): impassable"
            )
        self._positions[creature] = (new_col, new_row)
        return []

    def movement_cost_to(self, creature: Creature, col: int, row: int) -> int:
        """
        Return the movement cost in feet to step into (col, row).
        Creatures with ignore_difficult_terrain (Land's Stride) treat
        difficult terrain as normal cost.
        """
        self._check_bounds(col, row)
        cost = self._grid[row][col].movement_cost
        if cost > self.SQUARE_SIZE and getattr(creature, "ignore_difficult_terrain", False):
            cost = self.SQUARE_SIZE
        return cost

    def get_threatened_squares(
        self, creature: Creature, reach: int | None = None
    ) -> set[tuple[int, int]]:
        """
        Return the set of (col, row) squares this creature threatens
        with a melee attack (all squares within reach).
        """
        pos = self._require_position(creature)
        effective_reach = reach if reach is not None else self.MELEE_REACH
        squares = set()
        radius = effective_reach // self.SQUARE_SIZE
        col, row = pos
        for dc in range(-radius, radius + 1):
            for dr in range(-radius, radius + 1):
                nc, nr = col + dc, row + dr
                if (dc, dr) == (0, 0):
                    continue
                if self._in_bounds(nc, nr):
                    squares.add((nc, nr))
        return squares

    def _get_opportunity_attackers(
        self, mover: Creature, new_col: int, new_row: int
    ) -> list[Creature]:
        """
        Return enemies that threaten the mover's CURRENT square but
        NOT the destination square — i.e. the mover is leaving their
        reach, which triggers an opportunity attack.
        """
        origin = self._positions[mover]
        oa_candidates = []

        for other, _ in self._positions.items():
            if other is mover:
                continue
            if other.team == mover.team:
                continue  # allies don't get OA
            if other.has_condition("incapacitated"):
                continue  # incapacitated creatures can't react
            if other.has_condition("unconscious"):
                continue  # unconscious creatures can't react either (e.g. dying at 0 HP)

            threatened = self.get_threatened_squares(other)
            leaving_reach = (origin in threatened) and \
                            ((new_col, new_row) not in threatened)

            if leaving_reach:
                oa_candidates.append(other)

        return oa_candidates

    # ------------------------------------------------------------------
    # Utility / display
    # ------------------------------------------------------------------

    def creatures_within(
        self, origin: Creature, distance: int
    ) -> list[tuple[Creature, int]]:
        """
        Return [(creature, distance_ft), ...] for all creatures within
        `distance` feet of origin, sorted nearest first.
        """
        results = []
        for other in self._positions:
            if other is origin:
                continue
            try:
                dist = self.distance_between(origin, other)
                if dist <= distance:
                    results.append((other, dist))
            except LookupError:
                pass
        return sorted(results, key=lambda x: x[1])

    def enemies_of(self, creature: Creature) -> list[Creature]:
        """Return all living creatures on the opposing team."""
        return [
            c for c in self._positions
            if c.team != creature.team and c.is_alive()
        ]

    def print_grid(self) -> None:
        """
        Print an ASCII representation of the map to stdout.
        Useful for debugging scenarios.

        Legend:  .  normal    ~  water    #  wall    ^  difficult
                 Uppercase letter = first letter of creature's name
        """
        # Build a position lookup: (col, row) → creature
        pos_lookup = {pos: c for c, pos in self._positions.items()}

        terrain_chars = {
            "normal": ".",
            "difficult": "^",
            "wall": "#",
            "water": "~",
        }

        print(f"  " + "".join(str(c % 10) for c in range(self.width)))
        for row in range(self.height):
            row_str = f"{row % 10} "
            for col in range(self.width):
                if (col, row) in pos_lookup:
                    row_str += pos_lookup[(col, row)].name[0].upper()
                else:
                    tile = self._grid[row][col]
                    row_str += terrain_chars.get(tile.terrain_type, "?")
            print(row_str)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chebyshev_feet(
        self, pos_a: tuple[int, int], pos_b: tuple[int, int]
    ) -> int:
        """
        Chebyshev distance × SQUARE_SIZE.
        In 5e, moving diagonally costs the same as moving cardinally,
        so Chebyshev (max of dx, dy) is the correct metric.
        """
        dx = abs(pos_a[0] - pos_b[0])
        dy = abs(pos_a[1] - pos_b[1])
        return max(dx, dy) * self.SQUARE_SIZE

    def _in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    def _check_bounds(self, col: int, row: int) -> None:
        if not self._in_bounds(col, row):
            raise ValueError(
                f"Position ({col}, {row}) is outside the map "
                f"({self.width}×{self.height})"
            )

    def _require_position(self, creature: Creature) -> tuple[int, int]:
        pos = self._positions.get(creature)
        if pos is None:
            raise LookupError(
                f"{creature.name} is not on this map — call place() first"
            )
        return pos


# ---------------------------------------------------------------------------
# Quick smoke test — python -m core.battle_map
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from core.events import EventBus
    from core.creature import Creature

    event = EventBus()
    stats = {"Str": 10, "Dex": 14, "Con": 10, "Int": 10, "Wis": 10, "Cha": 10}

    ranger = Creature("Brendiir", hp=60, ac=15, stats=stats, event_manager=event)
    ranger.team = "blue"
    goblin1 = Creature("Goblin A", hp=7, ac=13, stats=stats, event_manager=event)
    goblin2 = Creature("Goblin B", hp=7, ac=13, stats=stats, event_manager=event)

    # 10×8 map with a wall column and a patch of difficult terrain
    bmap = BattleMap(10, 8)
    bmap.set_rect(5, 0, 1, 8, Tile.wall())          # wall at column 5
    bmap.set_rect(7, 3, 3, 3, Tile.difficult())      # difficult terrain patch

    bmap.place(ranger,  1, 4)
    bmap.place(goblin1, 3, 4)
    bmap.place(goblin2, 3, 6)

    print("=== Initial map ===")
    bmap.print_grid()

    print(f"\nDistance Brendiir → Goblin A: {bmap.distance_between(ranger, goblin1)}ft")
    print(f"Distance Brendiir → Goblin B: {bmap.distance_between(ranger, goblin2)}ft")
    print(f"Brendiir in melee of Goblin A: {bmap.is_in_melee_range(ranger, goblin1)}")
    print(f"Brendiir in melee of Goblin B: {bmap.is_in_melee_range(ranger, goblin2)}")

    print(f"\nRanged attack check (Brendiir → Goblin B, longbow 150/600):")
    result = bmap.check_attack_range(ranger, goblin2, is_ranged=True,
                                     normal_range=150, long_range=600)
    print(f"  {result}")

    print(f"\nMelee attack check (Brendiir → Goblin A, reach 5ft):")
    result = bmap.check_attack_range(ranger, goblin1, is_ranged=False, normal_range=5)
    print(f"  {result}")

    print(f"\nGoblin A moves from (3,4) toward (2,4) — leaving Brendiir's reach?")
    oa = bmap.move_creature(goblin1, 2, 4)
    print(f"  Opportunity attack targets: {[c.name for c in oa]}")

    print("\n=== After Goblin A moves ===")
    bmap.print_grid()

    print(f"\nCreatures within 20ft of Brendiir:")
    for c, d in bmap.creatures_within(ranger, 20):
        print(f"  {c.name} at {d}ft")