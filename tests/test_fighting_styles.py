"""
Tests for data/features/fighting_styles.py's Archery fighting style.

Regression coverage for a real bug: "attack" broadcasts on the shared
event bus for every attack in the whole combat, not just this feature's
owner's. Archery's on_attack had no attacker check, so its +2 to-hit (and
the "archery" tag) was silently applying to every attack by everyone --
allies and enemies alike -- any time an archer was anywhere in the fight,
discovered via the character-analyzer's by_tag breakdown showing "archery"
on a Two-Weapon-Fighting melee fighter who never took the feat.
"""
from types import SimpleNamespace

from core.attack import WeaponAttack
from data.features.fighting_styles import Archery


def make_attack(attacker, ranged):
    target = SimpleNamespace()
    attack = WeaponAttack(attacker, target, "1d8", item=None, range=ranged)
    attack.to_hit_mod = 5
    return attack


class TestArchery:
    def test_adds_bonus_and_tag_for_owners_own_ranged_attack(self):
        owner = SimpleNamespace(crit_threshold=20)
        feat = Archery()
        feat.owner = owner
        attack = make_attack(owner, ranged=True)

        feat.on_attack({"attacker": owner, "attack": attack})

        assert attack.to_hit_mod == 7
        assert "archery" in attack.tags

    def test_does_not_affect_owners_melee_attack(self):
        owner = SimpleNamespace(crit_threshold=20)
        feat = Archery()
        feat.owner = owner
        attack = make_attack(owner, ranged=False)

        feat.on_attack({"attacker": owner, "attack": attack})

        assert attack.to_hit_mod == 5
        assert "archery" not in attack.tags

    def test_does_not_affect_another_creatures_attack(self):
        """The actual bug: Archery used to fire for ANY attack broadcast on
        the shared bus, not just the owner's."""
        owner = SimpleNamespace(crit_threshold=20)
        someone_else = SimpleNamespace(crit_threshold=20)
        feat = Archery()
        feat.owner = owner
        attack = make_attack(someone_else, ranged=True)

        feat.on_attack({"attacker": someone_else, "attack": attack})

        assert attack.to_hit_mod == 5
        assert "archery" not in attack.tags

    def test_does_not_affect_an_enemys_ranged_attack(self):
        """Same bug, worst case: an archer ally in the fight used to hand
        out +2 to-hit to attacking monsters too."""
        owner = SimpleNamespace(crit_threshold=20)
        enemy = SimpleNamespace(crit_threshold=20)
        feat = Archery()
        feat.owner = owner
        attack = make_attack(enemy, ranged=True)

        feat.on_attack({"attacker": enemy, "attack": attack})

        assert attack.to_hit_mod == 5
        assert "archery" not in attack.tags
