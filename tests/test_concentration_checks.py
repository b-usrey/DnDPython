"""
Tests for concentration checks on damage (core/creature.py take_damage):
  - Damage while concentrating triggers a CON save (DC = max(10, damage // 2))
  - Failing breaks concentration and notifies the registered feature
  - Succeeding keeps concentration intact
  - No check when not concentrating, or when damage is fully absorbed by temp HP
  - Dropping to 0 HP always ends concentration, regardless of the save
"""
import random

from core.creature import Creature
from core.events import EventBus


def make_stats(con=14):
    return {"Str": 12, "Dex": 12, "Con": con, "Int": 10, "Wis": 10, "Cha": 10}


def make_creature(hp=20, ac=14, con=14):
    return Creature("Wizard", hp, ac, make_stats(con), EventBus())


class _RecordingFeature:
    def __init__(self):
        self.broken = False

    def on_concentration_broken(self):
        self.broken = True


class TestConcentrationCheckTrigger:
    def test_no_check_when_not_concentrating(self, monkeypatch):
        c = make_creature(hp=20)
        called = []
        monkeypatch.setattr(random, "randint", lambda a, b: called.append(1) or 10)
        c.take_damage(6)
        assert called == []   # no d20 rolled — no save attempted

    def test_no_check_when_damage_fully_absorbed_by_temp_hp(self, monkeypatch):
        c = make_creature(hp=20)
        c.add_temp_hp(10)
        c.start_concentration("Hold Person")
        called = []
        monkeypatch.setattr(random, "randint", lambda a, b: called.append(1) or 10)
        c.take_damage(6)   # fully absorbed by temp HP — no real damage taken
        assert called == []
        assert c.concentration == "Hold Person"

    def test_check_triggers_on_damage_while_concentrating(self, monkeypatch):
        c = make_creature(hp=20)
        c.start_concentration("Hold Person")
        monkeypatch.setattr(random, "randint", lambda a, b: 15)   # comfortably succeeds
        c.take_damage(6)
        assert c.concentration == "Hold Person"   # DC max(10,3)=10, roll 15+mod succeeds


class TestConcentrationCheckOutcome:
    def test_failed_save_breaks_concentration_and_notifies_feature(self, monkeypatch):
        c = make_creature(hp=20, con=8)   # -1 Con mod, no proficiency -> weak save
        feature = _RecordingFeature()
        c.start_concentration("Hold Person", feature=feature)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)   # guaranteed failure
        c.take_damage(20)   # DC = max(10, 10) = 10; 1 - 1 = 0, fails
        assert c.concentration is None
        assert feature.broken is True

    def test_successful_save_keeps_concentration(self, monkeypatch):
        c = make_creature(hp=20, con=20)   # +5 Con mod, strong save
        feature = _RecordingFeature()
        c.start_concentration("Hold Person", feature=feature)
        monkeypatch.setattr(random, "randint", lambda a, b: 10)
        c.take_damage(6)   # DC = max(10, 3) = 10; 10 + 5 = 15, succeeds
        assert c.concentration == "Hold Person"
        assert feature.broken is False

    def test_dc_scales_with_damage_taken(self, monkeypatch):
        c = make_creature(hp=100, con=14)   # +2 Con mod
        c.start_concentration("Hold Person")
        rolls = []
        monkeypatch.setattr(random, "randint", lambda a, b: rolls.append(1) or 7)
        # 40 damage -> DC = max(10, 20) = 20; roll 7 + 2 = 9 < 20 -> fails
        c.take_damage(40)
        assert c.concentration is None


class TestConcentrationEndsOnZeroHp:
    def test_dropping_to_zero_breaks_concentration_without_a_save(self, monkeypatch):
        c = make_creature(hp=10, con=20)   # very strong save, shouldn't matter
        feature = _RecordingFeature()
        c.start_concentration("Hold Person", feature=feature)
        rolled = []
        monkeypatch.setattr(random, "randint", lambda a, b: rolled.append(1) or 20)
        c.take_damage(10)   # exactly kills — no save is rolled, concentration just ends
        assert c.concentration is None
        assert feature.broken is True
        assert rolled == []   # confirms no saving throw was attempted
