"""
Tests for TacticalAI._score_weapon and _pick_weapon.
"""
import pytest
from types import SimpleNamespace
from core.tactical_ai import TacticalAI, WeaponProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_target(ac=14):
    return SimpleNamespace(ac=ac, hp=30, max_hp=30, name="Target")


def make_weapon(
    name="Longsword",
    is_ranged=False,
    attack_bonus=5,
    damage_die="1d8",
    damage_mod=3,
    normal_range=5,
    long_range=5,
):
    return WeaponProfile(
        name=name,
        is_ranged=is_ranged,
        normal_range=normal_range,
        long_range=long_range,
        attack_bonus=attack_bonus,
        damage_die=damage_die,
        damage_mod=damage_mod,
    )


class _RangeResult:
    def __init__(self, valid=True, disadvantage=False):
        self.valid = valid
        self.disadvantage = disadvantage


class _FakeBattleMap:
    def __init__(self, dist=5):
        self.dist = dist

    def check_attack_range(self, attacker, target, is_ranged, normal_range, long_range):
        return _RangeResult(valid=True, disadvantage=False)

    def distance_between(self, a, b):
        return self.dist


def make_creature(concentrating=False):
    return SimpleNamespace(concentration="Hunter's Mark" if concentrating else None)


# ---------------------------------------------------------------------------
# _score_weapon
# ---------------------------------------------------------------------------

class TestScoreWeapon:
    def setup_method(self):
        self.ai = TacticalAI()
        self.target = make_target(ac=14)

    def test_base_dpr(self):
        weapon = make_weapon(attack_bonus=5, damage_die="1d8", damage_mod=3)
        # avg = 4.5 + 3 = 7.5; needed = 14-5 = 9; p_hit = 12/20 = 0.6
        score = self.ai._score_weapon(weapon, self.target, dist=5, is_concentrating=False)
        assert score == pytest.approx(0.6 * 7.5)

    def test_two_die_weapon(self):
        weapon = make_weapon(attack_bonus=5, damage_die="2d6", damage_mod=0)
        # avg = 2*(6+1)/2 + 0 = 7.0; p_hit = 0.6
        score = self.ai._score_weapon(weapon, self.target, dist=5, is_concentrating=False)
        assert score == pytest.approx(0.6 * 7.0)

    def test_concentration_bonus_on_ranged(self):
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=5, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        base = self.ai._score_weapon(bow, self.target, dist=5, is_concentrating=False)
        boosted = self.ai._score_weapon(bow, self.target, dist=5, is_concentrating=True)
        assert boosted == pytest.approx(base * 1.5)

    def test_range_bonus_when_target_far(self):
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=5, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        close = self.ai._score_weapon(bow, self.target, dist=5, is_concentrating=False)
        far = self.ai._score_weapon(bow, self.target, dist=30, is_concentrating=False)
        assert far == pytest.approx(close * 1.2)

    def test_both_ranged_modifiers_stack(self):
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=5, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        base = self.ai._score_weapon(bow, self.target, dist=5, is_concentrating=False)
        both = self.ai._score_weapon(bow, self.target, dist=30, is_concentrating=True)
        assert both == pytest.approx(base * 1.5 * 1.2)

    def test_melee_gets_no_modifiers(self):
        sword = make_weapon(is_ranged=False)
        base = self.ai._score_weapon(sword, self.target, dist=5, is_concentrating=False)
        with_all = self.ai._score_weapon(sword, self.target, dist=30, is_concentrating=True)
        assert base == pytest.approx(with_all)

    def test_bad_damage_die_falls_back_to_five(self):
        weapon = WeaponProfile("Improvised", False, 5, 5,
                               attack_bonus=0, damage_die="1dX", damage_mod=0)
        score = self.ai._score_weapon(weapon, self.target, dist=5, is_concentrating=False)
        # fallback avg=5.0; needed=14; p_hit=(21-14)/20=0.35
        assert score == pytest.approx(0.35 * 5.0)

    def test_p_hit_clamped_at_min_0_05(self):
        # Very high AC: even with low attack bonus, P(hit) never < 0.05
        weapon = make_weapon(attack_bonus=0, damage_die="1d6", damage_mod=0)
        target_hard = make_target(ac=25)
        score = self.ai._score_weapon(weapon, target_hard, dist=5, is_concentrating=False)
        # avg_1d6 = 3.5; p_hit clamped to 0.05
        assert score == pytest.approx(0.05 * 3.5)

    def test_p_hit_clamped_at_max_0_95(self):
        # Very low AC: P(hit) never > 0.95
        weapon = make_weapon(attack_bonus=20, damage_die="1d6", damage_mod=0)
        target_easy = make_target(ac=2)
        score = self.ai._score_weapon(weapon, target_easy, dist=5, is_concentrating=False)
        assert score == pytest.approx(0.95 * 3.5)


# ---------------------------------------------------------------------------
# _pick_weapon
# ---------------------------------------------------------------------------

class TestPickWeapon:
    def setup_method(self):
        self.ai = TacticalAI()
        self.target = make_target(ac=14)

    def test_picks_highest_dpr_melee(self):
        sword = make_weapon("Sword", damage_die="1d8", damage_mod=3)
        dagger = make_weapon("Dagger", damage_die="1d4", damage_mod=1)
        picked = self.ai._pick_weapon(
            make_creature(), self.target, [sword, dagger], _FakeBattleMap(dist=5)
        )
        assert picked.name == "Sword"

    def test_prefers_ranged_when_concentrating(self):
        # Melee sword scores higher base, but ranged bow wins with ×1.5 concentration bonus
        sword = make_weapon("Sword", is_ranged=False, attack_bonus=7,
                            damage_die="1d8", damage_mod=4)
        # Sword: p_hit=(21-7)/20=0.7, avg=8.5 → 5.95
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=6, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        # Bow base: p_hit=(21-8)/20=0.65, avg=7.5 → 4.875 × 1.5 = 7.3125
        picked = self.ai._pick_weapon(
            make_creature(concentrating=True), self.target, [sword, bow], _FakeBattleMap(dist=5)
        )
        assert picked.name == "Bow"

    def test_melee_wins_over_bow_when_not_concentrating_and_close(self):
        sword = make_weapon("Sword", is_ranged=False, attack_bonus=7,
                            damage_die="1d8", damage_mod=4)
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=6, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        # Same values as above but not concentrating, dist=5 → bow gets no modifier
        # Sword: 5.95   Bow: 4.875 (no ×1.5)  → sword wins
        picked = self.ai._pick_weapon(
            make_creature(concentrating=False), self.target, [sword, bow], _FakeBattleMap(dist=5)
        )
        assert picked.name == "Sword"

    def test_prefers_ranged_when_target_far(self):
        sword = make_weapon("Sword", is_ranged=False, attack_bonus=5, damage_die="1d8", damage_mod=3)
        bow = make_weapon("Bow", is_ranged=True, attack_bonus=5, damage_die="1d8",
                          damage_mod=3, normal_range=150, long_range=600)
        # At 30ft both have same base score, bow gets ×1.2 → wins
        # Sword: 0.6*7.5=4.5    Bow: 4.5*1.2=5.4
        picked = self.ai._pick_weapon(
            make_creature(), self.target, [sword, bow], _FakeBattleMap(dist=30)
        )
        assert picked.name == "Bow"

    def test_fallback_when_no_valid_range(self):
        class _NoRangeBattleMap(_FakeBattleMap):
            def check_attack_range(self, attacker, target, is_ranged, normal_range, long_range):
                return _RangeResult(valid=False, disadvantage=False)

        sword = make_weapon("Sword")
        # Falls back to weapons[0] when nothing in pool
        picked = self.ai._pick_weapon(
            make_creature(), self.target, [sword], _NoRangeBattleMap()
        )
        assert picked.name == "Sword"
