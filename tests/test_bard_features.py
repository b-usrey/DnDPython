"""
Tests for Bard class mechanics (data/features/bard_features.py):
  - _bardic_die_size level scaling
  - BardicInspiration: targeting, bonus-action gating, uses-per-combat,
    +avg-die bonus applied once to the inspired ally's next attack
  - Vicious Mockery: WIS save, psychic damage, disadvantage on the
    mocked target's next attack roll (once, then clears)
"""
from types import SimpleNamespace

import pytest

from core.actionTracker import ActionTracker
from core.saving_throw import SaveResult
from data.features.bard_features import (
    BardicInspiration,
    ViciousMockery,
    _bardic_die_size,
)


class FakeBus:
    def subscribe(self, *a, **k):
        pass


class FakeCreature:
    def __init__(self, name="Bard", hp=20, max_hp=20, cha_mod=0,
                 bard_level=1, team="blue", proficiency=2):
        self.name = name
        self.hp = hp
        self.max_hp = max_hp
        self.statblock = SimpleNamespace(mods={"Cha": cha_mod})
        self.classes = [("Bard", bard_level)]
        self.actions = ActionTracker()
        self.team = team
        self.proficiency = proficiency

    def is_alive(self):
        return self.hp > 0


class FakeBattleMap:
    def __init__(self, creatures):
        self._creatures = creatures

    def all_creatures(self):
        return self._creatures


# ---------------------------------------------------------------------------
# _bardic_die_size
# ---------------------------------------------------------------------------

class TestBardicDieScaling:
    @pytest.mark.parametrize("level,expected", [
        (1, 6), (4, 6), (5, 8), (9, 8), (10, 10), (14, 10), (15, 12), (20, 12),
    ])
    def test_scaling(self, level, expected):
        assert _bardic_die_size(level) == expected


# ---------------------------------------------------------------------------
# Bardic Inspiration
# ---------------------------------------------------------------------------

class TestBardicInspiration:
    def test_attach_sets_uses_and_die_from_level_and_cha(self):
        owner = FakeCreature(cha_mod=3, bard_level=5)
        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        assert feat._uses_remaining == 3
        assert feat._die_size == 8

    def test_minimum_one_use_even_with_low_cha(self):
        owner = FakeCreature(cha_mod=-1, bard_level=1)
        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        assert feat._uses_remaining == 1

    def test_inspires_lowest_hp_ratio_ally_and_spends_bonus_action(self):
        owner = FakeCreature(cha_mod=2, bard_level=1)
        healthy_ally = FakeCreature(name="Healthy", hp=20, max_hp=20)
        hurt_ally = FakeCreature(name="Hurt", hp=5, max_hp=20)
        owner.battle_map = FakeBattleMap([owner, healthy_ally, hurt_ally])

        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})

        assert feat._inspired is hurt_ally
        assert feat._uses_remaining == 1
        assert owner.actions.bonus_actions == 0

    def test_does_not_inspire_twice_while_pending(self):
        owner = FakeCreature(cha_mod=2, bard_level=1)
        ally = FakeCreature(name="Ally", hp=10, max_hp=20)
        owner.battle_map = FakeBattleMap([owner, ally])

        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        owner.actions.reset()   # new turn, bonus action refreshed
        feat.on_turn_started({"creature": owner})

        assert feat._uses_remaining == 1   # second call was a no-op
        assert owner.actions.bonus_actions == 1   # not spent again

    def test_no_allies_does_not_spend_bonus_action(self):
        owner = FakeCreature(cha_mod=2, bard_level=1)
        owner.battle_map = FakeBattleMap([owner])
        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        assert feat._inspired is None
        assert owner.actions.bonus_actions == 1

    def test_on_attack_adds_average_die_value_once(self):
        owner = FakeCreature(cha_mod=2, bard_level=1)   # d6 die
        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        ally = FakeCreature(name="Ally")
        feat._inspired = ally

        attack = SimpleNamespace(to_hit_mod=5)
        feat.on_attack({"attacker": ally, "attack": attack})
        assert attack.to_hit_mod == pytest.approx(8.5)   # 5 + (6+1)/2
        assert feat._inspired is None   # consumed

        # A second attack by the same ally gets no further bonus
        attack2 = SimpleNamespace(to_hit_mod=5)
        feat.on_attack({"attacker": ally, "attack": attack2})
        assert attack2.to_hit_mod == 5

    def test_on_attack_ignores_uninspired_attacker(self):
        owner = FakeCreature()
        feat = BardicInspiration()
        feat.attach(owner, FakeBus())
        feat._inspired = FakeCreature(name="Ally")
        other = FakeCreature(name="SomeoneElse")
        attack = SimpleNamespace(to_hit_mod=5)
        feat.on_attack({"attacker": other, "attack": attack})
        assert attack.to_hit_mod == 5
        assert feat._inspired is not None   # still pending


# ---------------------------------------------------------------------------
# Vicious Mockery
# ---------------------------------------------------------------------------

def _saveresult(success, damage_dealt=0):
    return SaveResult(
        target=None, ability="Wis", dc=13, roll=10, bonus=0, total=10,
        success=success, damage_dealt=damage_dealt,
    )


class TestViciousMockery:
    def test_marks_target_mocked_on_failed_save(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.bard_features.SavingThrow.roll",
            lambda **kwargs: _saveresult(False),
        )
        owner = FakeCreature(bard_level=1)
        target = FakeCreature(name="Target")
        feat = ViciousMockery()
        feat.owner = owner
        feat._cast(owner, target, 0)
        assert feat._mocked is target

    def test_no_mock_on_successful_save(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.bard_features.SavingThrow.roll",
            lambda **kwargs: _saveresult(True),
        )
        owner = FakeCreature(bard_level=1)
        target = FakeCreature(name="Target")
        feat = ViciousMockery()
        feat.owner = owner
        feat._cast(owner, target, 0)
        assert feat._mocked is None

    def test_on_attack_imposes_disadvantage_once(self):
        feat = ViciousMockery()
        feat.owner = FakeCreature()
        target = FakeCreature(name="Target")
        feat._mocked = target

        attack = SimpleNamespace(disadvantage=False)
        feat.on_attack({"attacker": target, "attack": attack})
        assert attack.disadvantage is True
        assert feat._mocked is None

        attack2 = SimpleNamespace(disadvantage=False)
        feat.on_attack({"attacker": target, "attack": attack2})
        assert attack2.disadvantage is False   # already consumed

    def test_on_attack_ignores_other_attackers(self):
        feat = ViciousMockery()
        feat.owner = FakeCreature()
        target = FakeCreature(name="Target")
        feat._mocked = target
        someone_else = FakeCreature(name="SomeoneElse")

        attack = SimpleNamespace(disadvantage=False)
        feat.on_attack({"attacker": someone_else, "attack": attack})
        assert attack.disadvantage is False
        assert feat._mocked is target   # still pending
