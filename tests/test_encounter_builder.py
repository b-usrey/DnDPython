"""
Tests for utils/encounter_builder.py:
  - Reference tables (CR->XP, per-level thresholds, monster-count multiplier
    with the DMG party-size adjustment)
  - party_xp_threshold / assess_difficulty correctness
  - build_encounter: input validation, pool filtering, and that it actually
    finds a composition landing on/near the target XP budget
"""
import random

import pytest

from utils.encounter_builder import (
    CR_TO_XP,
    DIFFICULTIES,
    _base_multiplier,
    _party_adjusted_multiplier,
    assess_difficulty,
    build_encounter,
    monster_xp,
    party_xp_threshold,
)


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

class TestCrToXp:
    def test_known_values(self):
        assert CR_TO_XP[0.25] == 50     # Goblin
        assert CR_TO_XP[0.5] == 100     # Orc
        assert CR_TO_XP[1] == 200       # Bugbear
        assert CR_TO_XP[8] == 3900      # Young Green Dragon

    def test_monotonically_increasing(self):
        crs = sorted(CR_TO_XP.keys())
        xps = [CR_TO_XP[cr] for cr in crs]
        assert xps == sorted(xps)


class TestMonsterXp:
    def test_looks_up_by_cr(self):
        assert monster_xp({"cr": 2}) == 450

    def test_raises_when_no_cr(self):
        with pytest.raises(KeyError):
            monster_xp({"name": "Mystery Blob"})

    def test_raises_on_unmapped_cr(self):
        with pytest.raises(ValueError):
            monster_xp({"cr": 2.5})   # not a real CR value


class TestPartyXpThreshold:
    def test_single_level_1_character(self):
        assert party_xp_threshold([1], "easy") == 25
        assert party_xp_threshold([1], "medium") == 50
        assert party_xp_threshold([1], "hard") == 75
        assert party_xp_threshold([1], "deadly") == 100

    def test_sums_across_party(self):
        # Four level-3 characters, medium = 150 each
        assert party_xp_threshold([3, 3, 3, 3], "medium") == 600

    def test_mixed_levels(self):
        assert party_xp_threshold([1, 2], "easy") == 25 + 50

    def test_rejects_unknown_difficulty(self):
        with pytest.raises(ValueError):
            party_xp_threshold([1], "impossible")


class TestMultiplierTiers:
    def test_base_multiplier_tiers(self):
        assert _base_multiplier(1) == 1.0
        assert _base_multiplier(2) == 1.5
        assert _base_multiplier(3) == 2.0
        assert _base_multiplier(6) == 2.0
        assert _base_multiplier(7) == 2.5
        assert _base_multiplier(10) == 2.5
        assert _base_multiplier(11) == 3.0
        assert _base_multiplier(14) == 3.0
        assert _base_multiplier(15) == 4.0
        assert _base_multiplier(30) == 4.0

    def test_no_adjustment_for_standard_party_size(self):
        for size in (3, 4, 5):
            assert _party_adjusted_multiplier(3, size) == 2.0

    def test_small_party_steps_up_one_tier(self):
        assert _party_adjusted_multiplier(3, 2) == 2.5    # 2.0 -> 2.5
        assert _party_adjusted_multiplier(1, 2) == 1.5    # 1.0 -> 1.5

    def test_large_party_steps_down_one_tier(self):
        assert _party_adjusted_multiplier(3, 6) == 1.5    # 2.0 -> 1.5
        assert _party_adjusted_multiplier(1, 6) == 0.5    # 1.0 -> 0.5

    def test_clamped_at_table_edges(self):
        # Already at the bottom tier -- can't step down further
        assert _party_adjusted_multiplier(1, 20) == 0.5
        # Already at the top tier -- can't step up further
        assert _party_adjusted_multiplier(30, 1) == 4.0


class TestAssessDifficulty:
    def test_below_easy_is_trivial(self):
        assert assess_difficulty(10, [1]) == "trivial"

    def test_exact_thresholds(self):
        assert assess_difficulty(25, [1]) == "easy"
        assert assess_difficulty(50, [1]) == "medium"
        assert assess_difficulty(75, [1]) == "hard"
        assert assess_difficulty(100, [1]) == "deadly"

    def test_between_thresholds_rounds_down_to_band(self):
        assert assess_difficulty(60, [1]) == "medium"   # between medium(50) and hard(75)

    def test_far_above_deadly_still_deadly(self):
        assert assess_difficulty(999999, [1]) == "deadly"


# ---------------------------------------------------------------------------
# build_encounter
# ---------------------------------------------------------------------------

class TestBuildEncounterValidation:
    def test_rejects_empty_party(self):
        with pytest.raises(ValueError):
            build_encounter([])

    def test_rejects_out_of_range_level(self):
        with pytest.raises(ValueError):
            build_encounter([21])
        with pytest.raises(ValueError):
            build_encounter([0])

    def test_rejects_non_integer_level(self):
        with pytest.raises(ValueError):
            build_encounter([3.5])

    def test_rejects_unknown_difficulty(self):
        with pytest.raises(ValueError):
            build_encounter([3], difficulty="impossible")

    def test_rejects_max_monsters_below_one(self):
        with pytest.raises(ValueError):
            build_encounter([3], max_monsters=0)

    def test_rejects_pool_with_no_usable_cr(self):
        with pytest.raises(ValueError):
            build_encounter([3], monster_pool={"MYSTERY": {"name": "???"}})

    def test_skips_monsters_missing_cr_rather_than_failing_whole_pool(self):
        pool = {
            "GOOD": {"cr": 1},
            "BAD":  {"name": "no cr field"},
        }
        result = build_encounter([3, 3, 3, 3], monster_pool=pool, rng=random.Random(1))
        assert all(m["type"] == "GOOD" for m in result["monsters"])


class TestBuildEncounterComposition:
    def test_finds_exact_match_with_a_single_monster_type(self):
        """4 level-3 characters, medium threshold = 600 XP. A CR-1 monster
        (200 XP) at count=2 with the standard-party 1.5x multiplier hits
        exactly 600 -- the unique best answer in a one-monster-type pool,
        so this should be found deterministically."""
        pool = {"BUGBEAR": {"cr": 1}}
        result = build_encounter(
            [3, 3, 3, 3], difficulty="medium", monster_pool=pool,
            max_monsters=8, rng=random.Random(42),
        )
        assert result["target_xp"] == 600
        assert result["adjusted_xp"] == 600
        assert result["base_xp"] == 400
        assert result["multiplier"] == 1.5
        assert result["monsters"] == [{"type": "BUGBEAR", "count": 2}]
        assert result["difficulty_achieved"] == "medium"

    def test_result_shape(self):
        result = build_encounter([5, 5, 5, 5], difficulty="hard", rng=random.Random(7))
        assert isinstance(result["monsters"], list)
        assert all({"type", "count"} <= set(m.keys()) for m in result["monsters"])
        assert result["difficulty_requested"] == "hard"
        assert result["party_levels"] == [5, 5, 5, 5]
        assert result["monster_count"] == sum(m["count"] for m in result["monsters"])

    def test_respects_max_distinct_types(self):
        result = build_encounter(
            [4, 4, 4, 4], difficulty="deadly", max_distinct_types=1,
            rng=random.Random(3),
        )
        assert len(result["monsters"]) <= 1

    def test_respects_max_monsters(self):
        result = build_encounter(
            [10, 10, 10, 10], difficulty="deadly", max_monsters=3,
            rng=random.Random(9),
        )
        assert result["monster_count"] <= 3

    def test_lands_within_a_reasonable_band_of_target_across_many_seeds(self):
        """Not every combination of party/difficulty/pool has an exact
        answer, but with the full registry's CR spread it should usually
        land close. Check it's never wildly off across a spread of seeds."""
        from data.monsters.monsters import MONSTER_REGISTRY
        for seed in range(10):
            result = build_encounter(
                [4, 4, 4, 4], difficulty="medium",
                monster_pool=MONSTER_REGISTRY, rng=random.Random(seed),
            )
            target = result["target_xp"]
            assert result["adjusted_xp"] <= target * 2.5
            assert result["monsters"]   # never returns an empty encounter
