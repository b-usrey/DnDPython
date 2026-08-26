"""
Tests for:
  - core.attack.Attack.damage_type actually reflecting the weapon's
    damage type (was previously always overwritten back to "bludgeoning"
    right after being set correctly -- see core/attack.py)
  - data.features.feat_features.Piercer
  - data.features.analysis_aids.ForceAdvantage
"""
from types import SimpleNamespace

from core.attack import WeaponAttack
from data.features.feat_features import Piercer
from data.features.analysis_aids import ForceAdvantage


def make_weapon(damage_type="piercing", damage_die="1d8"):
    return SimpleNamespace(
        item_type="weapon", damage_die=damage_die, ability="Str",
        attack_bonus=0, damage_bonus=0, damageType=damage_type, attack_type="melee",
    )


def make_attack(item, crit=False):
    attacker = SimpleNamespace(statblock=SimpleNamespace(mods={"Str": 3}), proficiency=2, crit_threshold=20)
    attack = WeaponAttack(attacker, SimpleNamespace(), item.damage_die, item=item, range=False)
    attack.critical = crit
    return attack


def make_owner():
    return SimpleNamespace(name="Test", crit_threshold=20)


# WeaponAttack.__init__ bakes the Str modifier into damage_mod up front
# (attacker.statblock.mods["Str"] + item.damage_bonus == 3 + 0), so "did
# Piercer touch this attack" means "changed from 3", not "changed from 0".
BASE_DAMAGE_MOD = 3


# ---------------------------------------------------------------------------
# Attack.damage_type regression
# ---------------------------------------------------------------------------

class TestAttackDamageType:
    def test_reflects_the_weapons_actual_damage_type(self):
        attack = make_attack(make_weapon(damage_type="slashing"))
        assert attack.damage_type == "slashing"

    def test_reflects_piercing_too(self):
        attack = make_attack(make_weapon(damage_type="piercing"))
        assert attack.damage_type == "piercing"

    def test_falls_back_to_bludgeoning_with_no_item(self):
        attacker = SimpleNamespace(crit_threshold=20)
        attack = WeaponAttack(attacker, SimpleNamespace(), "1d4", item=None, range=False)
        assert attack.damage_type == "bludgeoning"


# ---------------------------------------------------------------------------
# Piercer
# ---------------------------------------------------------------------------

class TestPiercerFeature:
    def test_ignores_non_piercing_weapons(self):
        feat = Piercer()
        owner = make_owner()
        feat.owner = owner
        attack = make_attack(make_weapon(damage_type="slashing"))

        feat.on_hit({"attacker": owner, "attack": attack})

        assert attack.damage_mod == BASE_DAMAGE_MOD   # unchanged
        assert attack.base_dice == (1, 8)   # untouched
        assert "piercer" not in attack.tags

    def test_rerolls_lowest_die_on_a_piercing_hit(self):
        feat = Piercer()
        owner = make_owner()
        feat.owner = owner
        attack = make_attack(make_weapon(damage_type="piercing"))

        feat.on_hit({"attacker": owner, "attack": attack})

        assert "piercer" in attack.tags
        assert attack.base_dice == (0, 8)          # prevented from re-rolling in roll_damage
        assert BASE_DAMAGE_MOD + 1 <= attack.damage_mod <= BASE_DAMAGE_MOD + 8   # one die's worth, rerolled
        assert feat._used is True

    def test_once_per_turn_only(self):
        feat = Piercer()
        owner = make_owner()
        feat.owner = owner
        attack1 = make_attack(make_weapon(damage_type="piercing"))
        attack2 = make_attack(make_weapon(damage_type="piercing"))

        feat.on_hit({"attacker": owner, "attack": attack1})
        feat.on_hit({"attacker": owner, "attack": attack2})

        assert attack2.damage_mod == BASE_DAMAGE_MOD   # second hit this turn gets nothing
        assert attack2.base_dice == (1, 8)          # untouched

    def test_resets_on_new_turn(self):
        feat = Piercer()
        owner = make_owner()
        feat.owner = owner
        feat.on_hit({"attacker": owner, "attack": make_attack(make_weapon())})
        assert feat._used is True

        feat.on_turn_started({"creature": owner})
        assert feat._used is False

    def test_crit_adds_one_extra_piercing_die_and_stacks_with_reroll(self):
        feat = Piercer()
        owner = make_owner()
        feat.owner = owner
        attack = make_attack(make_weapon(damage_type="piercing"), crit=True)

        feat.on_hit({"attacker": owner, "attack": attack})

        assert attack.extra_dice == [(1, 8)]
        assert attack.base_dice == (0, 8)
        assert BASE_DAMAGE_MOD + 1 <= attack.damage_mod <= BASE_DAMAGE_MOD + 8

    def test_ignores_other_creatures_attacks(self):
        feat = Piercer()
        feat.owner = SimpleNamespace(crit_threshold=20)
        someone_else = SimpleNamespace(crit_threshold=20)
        attack = make_attack(make_weapon(damage_type="piercing"))

        feat.on_hit({"attacker": someone_else, "attack": attack})

        assert attack.damage_mod == BASE_DAMAGE_MOD   # unchanged
        assert attack.base_dice == (1, 8)


# ---------------------------------------------------------------------------
# ForceAdvantage
# ---------------------------------------------------------------------------

class TestForceAdvantage:
    def test_grants_advantage_on_owners_attack(self):
        feat = ForceAdvantage()
        owner = make_owner()
        feat.owner = owner
        attack = make_attack(make_weapon())
        assert attack.advantage is False

        feat.on_attack({"attacker": owner, "attack": attack})

        assert attack.advantage is True

    def test_ignores_other_creatures_attacks(self):
        feat = ForceAdvantage()
        feat.owner = SimpleNamespace(crit_threshold=20)
        someone_else = SimpleNamespace(crit_threshold=20)
        attack = make_attack(make_weapon())

        feat.on_attack({"attacker": someone_else, "attack": attack})

        assert attack.advantage is False
