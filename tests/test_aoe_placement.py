"""
Tests for _AoESpell._find_best_placement:
  - Optimal center picks the cluster with most enemies
  - Self-centered spells always use the caster position
  - MIN_ENEMIES_HIT gate (relaxed to 1 when only 1 enemy exists)
  - FRIENDLY_FIRE_MAX gate blocks positions that clip too many allies
  - FRIENDLY_PENALTY discourages placements that hit allies
  - Score must be positive to fire (no-win situations return None)
"""
import pytest
from types import SimpleNamespace
from data.features.combat_spells import _AoESpell, _creatures_in_aoe, _creatures_in_line


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

def make_statblock(mods=None):
    return SimpleNamespace(mods=mods or {})


def make_creature(name, team, pos, hp=30, max_hp=30, ac=14, dex=0, str_=0):
    return SimpleNamespace(
        name=name, team=team, pos=pos,
        hp=hp, max_hp=max_hp, ac=ac,
        statblock=make_statblock({"Dex": dex, "Str": str_}),
        is_alive=lambda: True,
    )


class _FakeBattleMap:
    """Minimal battle map that answers the three queries _AoESpell uses."""
    def __init__(self, creatures, width=20, height=20):
        self._creatures = creatures
        self._w = width
        self._h = height

    def get_position(self, creature):
        return getattr(creature, "pos", None)

    def enemies_of(self, caster):
        return [c for c in self._creatures
                if c.team != caster.team and c.is_alive()]

    def all_creatures(self):
        return self._creatures

    def _in_bounds(self, col, row):
        return 0 <= col < self._w and 0 <= row < self._h


class _ConcreteAoE(_AoESpell):
    """Instantiable subclass for placement tests."""
    name       = "_TestAoE"
    SLOT_LEVEL = 3
    RADIUS_FT  = 20   # = 4 squares
    CAST_RANGE_FT = 150

    def _avg_damage_at(self, slot_level):
        return 28.0

    def _cast_aoe(self, caster, targets, allies, slot_level):
        pass  # not needed for placement tests


def make_spell():
    s = _ConcreteAoE.__new__(_ConcreteAoE)
    _AoESpell.__init__(s)
    return s


def make_caster(pos=(0, 0), team="blue"):
    c = make_creature("Wizard", team, pos)
    c.proficiency = 4       # needed by _spell_dc
    c.classes     = [("Wizard", 7)]
    c.spell_slots = None    # forces _spell_dc to use the proficiency path
    return c


# ---------------------------------------------------------------------------
# _creatures_in_aoe helper
# ---------------------------------------------------------------------------

class TestCreaturesInAoe:
    def test_hits_creature_at_center(self):
        c = make_creature("A", "red", (5, 5))
        assert _creatures_in_aoe([c], (5, 5), radius_sq=4) == [c]

    def test_hits_creature_at_edge_of_radius(self):
        c = make_creature("A", "red", (5, 9))  # 4 squares away (Chebyshev)
        assert _creatures_in_aoe([c], (5, 5), radius_sq=4) == [c]

    def test_misses_creature_just_outside_radius(self):
        c = make_creature("A", "red", (5, 10))  # 5 squares away
        assert _creatures_in_aoe([c], (5, 5), radius_sq=4) == []

    def test_skips_creature_with_no_pos(self):
        c = make_creature("A", "red", None)
        assert _creatures_in_aoe([c], (5, 5), radius_sq=4) == []

    def test_filters_multiple(self):
        near = make_creature("Near", "red", (5, 5))
        far  = make_creature("Far",  "red", (15, 15))
        result = _creatures_in_aoe([near, far], (5, 5), radius_sq=4)
        assert near in result
        assert far not in result


# ---------------------------------------------------------------------------
# Placement: basic correctness
# ---------------------------------------------------------------------------

class TestFindBestPlacement:
    def _spell(self, **kwargs):
        s = make_spell()
        for k, v in kwargs.items():
            setattr(s, k, v)
        return s

    def test_hits_clustered_enemies(self):
        """Two adjacent enemies should be caught in one Fireball."""
        caster = make_caster(pos=(0, 0))
        e1 = make_creature("Goblin1", "red", (5, 5))
        e2 = make_creature("Goblin2", "red", (5, 6))  # 1 sq away
        bm = _FakeBattleMap([caster, e1, e2])
        spell = self._spell(MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.0)

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, allies = result
        assert e1 in enemies and e2 in enemies
        assert len(allies) == 0

    def test_prefers_larger_cluster(self):
        """Three enemies clustered tighter should win over two spread out."""
        caster = make_caster(pos=(0, 0))
        # Small cluster at (5,5)
        e1 = make_creature("E1", "red", (5, 5))
        e2 = make_creature("E2", "red", (5, 6))
        # Larger cluster at (10, 0)
        e3 = make_creature("E3", "red", (10, 0))
        e4 = make_creature("E4", "red", (10, 1))
        e5 = make_creature("E5", "red", (10, 2))
        bm = _FakeBattleMap([caster, e1, e2, e3, e4, e5])
        spell = self._spell(MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.0, RADIUS_FT=20)

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, _ = result
        # The 3-enemy cluster should win
        assert e3 in enemies and e4 in enemies and e5 in enemies

    def test_returns_none_when_no_enemies(self):
        caster = make_caster()
        bm = _FakeBattleMap([caster])
        assert make_spell()._find_best_placement(caster, bm) is None

    def test_returns_none_when_below_min_enemies(self):
        """Single enemy with MIN_ENEMIES_HIT=2 and two total enemies should fail."""
        caster = make_caster(pos=(0, 0))
        # Two enemies far apart — neither center catches both
        e1 = make_creature("E1", "red", (3, 0))
        e2 = make_creature("E2", "red", (18, 0))  # far away, outside radius
        bm = _FakeBattleMap([caster, e1, e2])
        spell = self._spell(MIN_ENEMIES_HIT=2, RADIUS_FT=10, CAST_RANGE_FT=150)

        # With radius 10ft (2 sq), neither center catches both
        result = spell._find_best_placement(caster, bm)
        # Only one enemy per candidate center → not enough → None
        assert result is None

    def test_relaxes_min_when_only_one_enemy_exists(self):
        """MIN_ENEMIES_HIT should auto-relax to 1 when only 1 enemy is alive."""
        caster = make_caster(pos=(0, 0))
        solo = make_creature("Boss", "red", (4, 0), hp=200)
        bm = _FakeBattleMap([caster, solo])
        spell = self._spell(MIN_ENEMIES_HIT=2)  # normally requires 2

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, _ = result
        assert solo in enemies


# ---------------------------------------------------------------------------
# Friendly fire gates
# ---------------------------------------------------------------------------

class TestFriendlyFireGates:
    def _spell(self, **kwargs):
        s = make_spell()
        for k, v in kwargs.items():
            setattr(s, k, v)
        return s

    def test_no_friendly_fire_allowed_skips_clipping_placement(self):
        """FRIENDLY_FIRE_MAX=0.0 must reject any center that clips an ally."""
        caster = make_caster(pos=(0, 0))
        enemy = make_creature("E", "red",  (5, 5))
        ally  = make_creature("A", "blue", (5, 6))  # adjacent to enemy, inside radius
        bm = _FakeBattleMap([caster, enemy, ally])
        spell = self._spell(
            MIN_ENEMIES_HIT=1, FRIENDLY_FIRE_MAX=0.0, RADIUS_FT=20,
        )

        # Only available center would clip both — must be rejected
        result = spell._find_best_placement(caster, bm)
        if result is not None:
            _, allies_hit = result
            assert len(allies_hit) == 0, "Should not clip ally when FRIENDLY_FIRE_MAX=0"

    def test_permissive_threshold_allows_clipping(self):
        """FRIENDLY_FIRE_MAX=0.5 allows ≤50% ally share; 3 enemies + 1 ally = 25% → fires."""
        # SELF_CENTERED ensures the only candidate center is the caster — no escape.
        caster = make_caster(pos=(0, 0))
        e1   = make_creature("E1", "red",  (1, 0), hp=30)
        e2   = make_creature("E2", "red",  (2, 0), hp=30)
        e3   = make_creature("E3", "red",  (3, 0), hp=30)
        ally = make_creature("A",  "blue", (1, 1), hp=30)  # also within radius
        bm   = _FakeBattleMap([caster, e1, e2, e3, ally])
        spell = self._spell(
            SELF_CENTERED=True, RADIUS_FT=15,  # 3sq — all targets within 3sq of (0,0)
            MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.5, FRIENDLY_PENALTY=2.0,
        )

        result = spell._find_best_placement(caster, bm)
        # 3 enemies, 1 ally → ally share ≈ 25% < 50%; score = 3E − 2A = E > 0 → fires
        assert result is not None
        enemies_hit, allies_hit = result
        assert len(enemies_hit) == 3
        assert ally in allies_hit

    def test_friendly_penalty_avoids_equal_ally_damage(self):
        """FRIENDLY_PENALTY=2 makes 1-enemy + 1-ally score negative → spell doesn't fire."""
        # SELF_CENTERED locks placement to caster so algorithm cannot dodge the ally.
        caster = make_caster(pos=(0, 0))
        enemy = make_creature("E", "red",  (1, 0), hp=30)
        ally  = make_creature("A", "blue", (1, 1), hp=30)  # same distance from caster
        bm    = _FakeBattleMap([caster, enemy, ally])
        spell = self._spell(
            SELF_CENTERED=True, RADIUS_FT=15,
            MIN_ENEMIES_HIT=1,
            FRIENDLY_FIRE_MAX=1.0,  # ratio gate wide open
            FRIENDLY_PENALTY=2.0,   # but penalty: score = E − 2A = −E < 0
        )

        result = spell._find_best_placement(caster, bm)
        assert result is None


# ---------------------------------------------------------------------------
# Self-centered spells
# ---------------------------------------------------------------------------

class TestSelfCentered:
    def test_self_centered_uses_caster_position(self):
        """Thunderwave/BurningHands: center is always the caster."""
        caster = make_caster(pos=(5, 5))
        e1 = make_creature("E1", "red", (5, 6))  # adjacent = within RADIUS=15ft=3sq
        e2 = make_creature("E2", "red", (5, 7))
        bm = _FakeBattleMap([caster, e1, e2])

        s = make_spell()
        s.SELF_CENTERED   = True
        s.RADIUS_FT       = 15
        s.MIN_ENEMIES_HIT = 1

        result = s._find_best_placement(caster, bm)
        assert result is not None
        enemies, _ = result
        assert e1 in enemies and e2 in enemies

    def test_self_centered_returns_none_when_no_enemies_nearby(self):
        """If no enemies are within RADIUS, self-centered spell doesn't fire."""
        caster = make_caster(pos=(0, 0))
        far_enemy = make_creature("E", "red", (15, 15))  # 15 sq away >> RADIUS=3sq
        bm = _FakeBattleMap([caster, far_enemy])

        s = make_spell()
        s.SELF_CENTERED   = True
        s.RADIUS_FT       = 15
        s.MIN_ENEMIES_HIT = 1

        result = s._find_best_placement(caster, bm)
        assert result is None


# ---------------------------------------------------------------------------
# _creatures_in_line helper
# ---------------------------------------------------------------------------

class TestCreaturesInLine:
    def test_hits_creature_on_centerline(self):
        c = make_creature("A", "red", (5, 0))
        result = _creatures_in_line([c], origin=(0, 0), end=(10, 0), half_width_sq=0.5)
        assert result == [c]

    def test_misses_creature_off_to_the_side(self):
        c = make_creature("A", "red", (5, 3))  # well off the 0.5-wide line
        result = _creatures_in_line([c], origin=(0, 0), end=(10, 0), half_width_sq=0.5)
        assert result == []

    def test_misses_creature_behind_origin(self):
        c = make_creature("A", "red", (-2, 0))  # behind the caster
        result = _creatures_in_line([c], origin=(0, 0), end=(10, 0), half_width_sq=0.5)
        assert result == []

    def test_hits_multiple_creatures_collinear(self):
        e1 = make_creature("E1", "red", (3, 0))
        e2 = make_creature("E2", "red", (6, 0))
        e3 = make_creature("E3", "red", (9, 0))
        result = _creatures_in_line([e1, e2, e3], origin=(0, 0), end=(10, 0), half_width_sq=0.5)
        assert e1 in result and e2 in result and e3 in result

    def test_skips_creature_with_no_pos(self):
        c = make_creature("A", "red", None)
        result = _creatures_in_line([c], origin=(0, 0), end=(10, 0), half_width_sq=0.5)
        assert result == []


# ---------------------------------------------------------------------------
# Placement: line shape (Lightning Bolt)
# ---------------------------------------------------------------------------

class _ConcreteLineAoE(_AoESpell):
    """Instantiable line-shaped subclass for placement tests."""
    name            = "_TestLineAoE"
    SLOT_LEVEL      = 3
    SHAPE           = "line"
    LINE_LENGTH_FT  = 100
    LINE_WIDTH_FT   = 5

    def _avg_damage_at(self, slot_level):
        return 28.0

    def _cast_aoe(self, caster, targets, allies, slot_level):
        pass  # not needed for placement tests


def make_line_spell(**kwargs):
    s = _ConcreteLineAoE.__new__(_ConcreteLineAoE)
    _AoESpell.__init__(s)
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


class TestLinePlacement:
    def test_hits_enemies_strung_out_in_a_row(self):
        """Three enemies standing in a straight line should all be caught."""
        caster = make_caster(pos=(0, 0))
        e1 = make_creature("E1", "red", (3, 0))
        e2 = make_creature("E2", "red", (6, 0))
        e3 = make_creature("E3", "red", (9, 0))
        bm = _FakeBattleMap([caster, e1, e2, e3])
        spell = make_line_spell(MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.0)

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, allies = result
        assert e1 in enemies and e2 in enemies and e3 in enemies
        assert len(allies) == 0

    def test_avoids_ally_standing_off_the_line(self):
        """An ally well off to the side of the enemies' line shouldn't be clipped."""
        caster = make_caster(pos=(0, 0))
        e1   = make_creature("E1", "red", (3, 0))
        e2   = make_creature("E2", "red", (6, 0))
        ally = make_creature("A",  "blue", (3, 5))  # off the line entirely
        bm = _FakeBattleMap([caster, e1, e2, ally])
        spell = make_line_spell(MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.0)

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, allies = result
        assert e1 in enemies and e2 in enemies
        assert ally not in allies

    def test_rejects_direction_that_skewers_an_ally(self):
        """The only direction catching 2 enemies also catches an ally standing
        beyond them on the same line — FRIENDLY_FIRE_MAX=0.0 must reject it."""
        caster = make_caster(pos=(0, 0))
        e1   = make_creature("E1", "red", (3, 0))
        e2   = make_creature("E2", "red", (6, 0))
        ally = make_creature("A",  "blue", (9, 0))  # further down the same line
        bm = _FakeBattleMap([caster, e1, e2, ally])
        spell = make_line_spell(MIN_ENEMIES_HIT=2, FRIENDLY_FIRE_MAX=0.0)

        result = spell._find_best_placement(caster, bm)
        assert result is None

    def test_relaxes_min_when_only_one_enemy_exists(self):
        caster = make_caster(pos=(0, 0))
        solo = make_creature("Boss", "red", (5, 0), hp=200)
        bm = _FakeBattleMap([caster, solo])
        spell = make_line_spell(MIN_ENEMIES_HIT=2)

        result = spell._find_best_placement(caster, bm)
        assert result is not None
        enemies, _ = result
        assert solo in enemies

    def test_returns_none_when_no_enemies(self):
        caster = make_caster()
        bm = _FakeBattleMap([caster])
        assert make_line_spell()._find_best_placement(caster, bm) is None
