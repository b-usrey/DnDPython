from dataclasses import dataclass, field


@dataclass
class Tile:
    """
    A single square on the battle grid (5ft × 5ft).

    terrain_type examples: "normal", "difficult", "water", "wall"
    movement_cost: feet to enter this square (5 normal, 10 difficult)
    passable: False for walls, pillars, solid obstacles
    """
    terrain_type: str = "normal"
    passable: bool = True
    movement_cost: int = 5
    # Future: cover value, elevation, hazard flags
    # cover: int = 0        # 0, 2 (half), 5 (three-quarters)
    # elevation: int = 0    # feet above ground level

    @classmethod
    def normal(cls):
        return cls(terrain_type="normal", passable=True, movement_cost=5)

    @classmethod
    def difficult(cls):
        return cls(terrain_type="difficult", passable=True, movement_cost=10)

    @classmethod
    def wall(cls):
        return cls(terrain_type="wall", passable=False, movement_cost=0)

    @classmethod
    def water(cls):
        return cls(terrain_type="water", passable=True, movement_cost=10)

    def __repr__(self):
        return f"Tile({self.terrain_type})"