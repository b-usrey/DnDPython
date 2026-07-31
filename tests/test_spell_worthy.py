"""
Tests for TeamMemory.spell_worthy: HP floor gates, danger override, cantrips.
"""
import pytest
from types import SimpleNamespace
from core.team_memory import TeamMemory, ThreatProfile


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _FakeEventBus:
    def subscribe(self, event_name, handler):
        pass


class _FakeBattleMap:
    def all_creatures(self):
        return []


def make_memory():
    return TeamMemory("blue", _FakeEventBus(), _FakeBattleMap())


def make_target(hp, max_hp=100):
    return SimpleNamespace(hp=hp, max_hp=max_hp, name="Target")


def inject_threat(memory, target, danger_damage_per_hit, attacks=2):
    """Add a ThreatProfile with a known danger_score (all hits land)."""
    profile = ThreatProfile(
        creature=target,
        attacks_observed=attacks,
        hits_landed=attacks,
        damage_rolls_seen=[danger_damage_per_hit] * attacks,
    )
    memory._threats[id(target)] = profile


# ---------------------------------------------------------------------------
# Cantrips
# ---------------------------------------------------------------------------

class TestCantrip:
    def test_cantrip_always_worthy_at_low_hp(self):
        mem = make_memory()
        assert mem.spell_worthy(0, make_target(hp=1)) is True

    def test_cantrip_always_worthy_at_zero_hp(self):
        mem = make_memory()
        assert mem.spell_worthy(0, make_target(hp=0)) is True


# ---------------------------------------------------------------------------
# HP floor gates (no threat profile → no danger override)
# ---------------------------------------------------------------------------

class TestHpFloorGates:
    def test_target_above_floor_is_worthy(self):
        mem = make_memory()
        assert mem.spell_worthy(1, make_target(hp=15)) is True  # floor=10

    def test_target_at_exact_floor_is_worthy(self):
        mem = make_memory()
        assert mem.spell_worthy(1, make_target(hp=10)) is True

    def test_target_below_floor_without_profile_not_worthy(self):
        mem = make_memory()
        assert mem.spell_worthy(1, make_target(hp=9)) is False

    def test_slot_floors_match_constants(self):
        mem = make_memory()
        expected = {1: 10, 2: 16, 3: 26, 4: 36, 5: 48}
        for level, floor in expected.items():
            t_above = make_target(hp=floor)
            t_below = make_target(hp=floor - 1)
            assert mem.spell_worthy(level, t_above) is True, f"slot {level}: hp={floor} should pass"
            assert mem.spell_worthy(level, t_below) is False, f"slot {level}: hp={floor-1} should fail"

    def test_unknown_slot_level_uses_fallback_formula(self):
        mem = make_memory()
        # Slot 6: floor = 6 * 10 = 60
        assert mem.spell_worthy(6, make_target(hp=60)) is True
        assert mem.spell_worthy(6, make_target(hp=59)) is False


# ---------------------------------------------------------------------------
# Danger override
# ---------------------------------------------------------------------------

class TestDangerOverride:
    def test_high_danger_overrides_low_hp(self):
        mem = make_memory()
        target = make_target(hp=2)
        # danger_score = 16.0 (hits every attack for 16) — well above 8.0 threshold
        inject_threat(mem, target, danger_damage_per_hit=16)
        assert mem.spell_worthy(1, target) is True

    def test_danger_exactly_at_threshold_qualifies(self):
        mem = make_memory()
        target = make_target(hp=1)
        # danger_score must be >= 8.0 exactly; 8 damage, 2 hits / 2 attacks → 8.0
        inject_threat(mem, target, danger_damage_per_hit=8, attacks=2)
        assert mem.spell_worthy(1, target) is True

    def test_danger_below_threshold_does_not_override(self):
        mem = make_memory()
        target = make_target(hp=1)
        # danger_score = 5.0, threshold = 8.0 → should not override
        inject_threat(mem, target, danger_damage_per_hit=5, attacks=2)
        assert mem.spell_worthy(1, target) is False

    def test_danger_override_applies_to_higher_slots(self):
        mem = make_memory()
        target = make_target(hp=2)
        # 5th-level slot: floor=48; target has hp=2 → needs danger >= 8.0
        inject_threat(mem, target, danger_damage_per_hit=20)
        assert mem.spell_worthy(5, target) is True

    def test_no_threat_profile_means_zero_danger(self):
        mem = make_memory()
        target = make_target(hp=1)
        # No profile → danger = 0.0 → no override
        assert mem.spell_worthy(3, target) is False
