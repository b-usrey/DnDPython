"""
Tests for the EV-based -5/+10 power-attack trade (Sharpshooter / Great
Weapon Master), replacing the old flat target-HP threshold that ignored
the attacker's own accuracy and the target's AC:
  - core.attack.hit_probability()
  - data.features.feat_features._worth_the_power_attack_trade()
  - Sharpshooter.on_attack / GreatWeaponMaster.on_attack apply the trade
    exactly when the shared helper says it's worth it
"""
from types import SimpleNamespace

import pytest

from core.attack import WeaponAttack, hit_probability
from data.features.feat_features import (
    Sharpshooter,
    GreatWeaponMaster,
    _worth_the_power_attack_trade,
)


# ---------------------------------------------------------------------------
# hit_probability
# ---------------------------------------------------------------------------

class TestHitProbability:
    def test_basic_case(self):
        # needed = 15 - 5 = 10 -> (21-10)/20 = 0.55
        assert hit_probability(to_hit_bonus=5, target_ac=15) == pytest.approx(0.55)

    def test_clamped_at_upper_bound(self):
        # trivially easy to hit -- clamped to 0.95, not 1.0
        assert hit_probability(to_hit_bonus=20, target_ac=5) == pytest.approx(0.95)

    def test_clamped_at_lower_bound(self):
        # essentially unhittable -- clamped to 0.05, not lower
        assert hit_probability(to_hit_bonus=0, target_ac=40) == pytest.approx(0.05)

    def test_lower_to_hit_bonus_means_lower_probability(self):
        assert hit_probability(10, 15) > hit_probability(5, 15)


# ---------------------------------------------------------------------------
# _worth_the_power_attack_trade
# ---------------------------------------------------------------------------

def make_attack(to_hit_mod, damage_mod, base_dice="1d8"):
    attacker = SimpleNamespace(crit_threshold=20)
    target = SimpleNamespace()
    attack = WeaponAttack(attacker, target, base_dice, item=None, range=True)
    attack.to_hit_mod = to_hit_mod
    attack.damage_mod = damage_mod
    return attack


def make_target(ac, hp=100):
    return SimpleNamespace(ac=ac, hp=hp)


class TestWorthThePowerAttackTrade:
    def test_worth_it_with_high_accuracy_and_healthy_target(self):
        """+11 to hit vs AC 12: even at -5 you're still hitting on a 6+,
        so the accuracy cost is tiny and the +10 damage is a clear win."""
        attack = make_attack(to_hit_mod=11, damage_mod=3)
        target = make_target(ac=12, hp=100)
        assert _worth_the_power_attack_trade(attack, target) is True

    def test_not_worth_it_with_low_accuracy(self):
        """+2 to hit vs AC 18: already need a 16+, dropping to -3 effective
        makes most attacks miss outright -- not worth it."""
        attack = make_attack(to_hit_mod=2, damage_mod=2)
        target = make_target(ac=18, hp=100)
        assert _worth_the_power_attack_trade(attack, target) is False

    def test_not_worth_it_when_normal_hit_already_overkills(self):
        """Target has only 3 HP left and average damage already exceeds
        that -- the +10 is entirely wasted overkill, so paying accuracy
        for it is a pure loss once both options are HP-capped."""
        attack = make_attack(to_hit_mod=11, damage_mod=3)   # avg ~7.5, easily lethal
        target = make_target(ac=12, hp=3)
        assert _worth_the_power_attack_trade(attack, target) is False

    def test_indifferent_case_leans_on_real_hit_math_not_hp_alone(self):
        """A high-HP target with mediocre accuracy should decline the trade
        -- confirms the decision tracks accuracy, not just 'target has a
        lot of HP left' the way the old flat threshold did."""
        attack = make_attack(to_hit_mod=3, damage_mod=2)
        target = make_target(ac=17, hp=200)   # plenty of HP, but a bad matchup
        assert _worth_the_power_attack_trade(attack, target) is False


# ---------------------------------------------------------------------------
# Feature-level: Sharpshooter / Great Weapon Master
# ---------------------------------------------------------------------------

class TestSharpshooterFeature:
    def test_applies_trade_when_worth_it(self):
        feat = Sharpshooter()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attack = make_attack(to_hit_mod=11, damage_mod=3)
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 6     # 11 - 5
        assert attack.damage_mod == 13    # 3 + 10
        assert "sharpshooter" in attack.tags

    def test_skips_trade_when_not_worth_it(self):
        feat = Sharpshooter()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attack = make_attack(to_hit_mod=2, damage_mod=2)
        target = make_target(ac=18, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 2     # unchanged
        assert attack.damage_mod == 2     # unchanged
        assert "sharpshooter" not in attack.tags

    def test_ignores_melee_attacks(self):
        feat = Sharpshooter()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attacker = SimpleNamespace(crit_threshold=20)
        attack = WeaponAttack(attacker, SimpleNamespace(), "1d8", item=None, range=False)
        attack.to_hit_mod, attack.damage_mod = 11, 3
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 11    # unchanged -- not a ranged attack
        assert "sharpshooter" not in attack.tags

    def test_ignores_other_creatures_attacks(self):
        feat = Sharpshooter()
        feat.owner = SimpleNamespace(crit_threshold=20)
        someone_else = SimpleNamespace(crit_threshold=20)
        attack = make_attack(to_hit_mod=11, damage_mod=3)
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": someone_else, "target": target})

        assert attack.to_hit_mod == 11
        assert "sharpshooter" not in attack.tags


class TestGreatWeaponMasterFeature:
    def _heavy_weapon_attack(self, to_hit_mod, damage_mod):
        attacker = SimpleNamespace(crit_threshold=20)
        attack = WeaponAttack(attacker, SimpleNamespace(), "2d6", item=None, range=False)
        attack.to_hit_mod, attack.damage_mod = to_hit_mod, damage_mod
        attack.item = SimpleNamespace(properties=["heavy"])
        return attack

    def test_applies_trade_when_worth_it(self):
        feat = GreatWeaponMaster()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attack = self._heavy_weapon_attack(to_hit_mod=11, damage_mod=4)
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 6
        assert attack.damage_mod == 14
        assert "great_weapon_master" in attack.tags

    def test_requires_heavy_property(self):
        feat = GreatWeaponMaster()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attack = self._heavy_weapon_attack(to_hit_mod=11, damage_mod=4)
        attack.item = SimpleNamespace(properties=[])   # not heavy
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 11
        assert "great_weapon_master" not in attack.tags

    def test_ignores_ranged_attacks(self):
        feat = GreatWeaponMaster()
        owner = SimpleNamespace(crit_threshold=20)
        feat.owner = owner
        attack = WeaponAttack(owner, SimpleNamespace(), "2d6", item=None, range=True)
        attack.to_hit_mod, attack.damage_mod = 11, 4
        attack.item = SimpleNamespace(properties=["heavy"])
        target = make_target(ac=12, hp=100)

        feat.on_attack({"attack": attack, "attacker": owner, "target": target})

        assert attack.to_hit_mod == 11
        assert "great_weapon_master" not in attack.tags
