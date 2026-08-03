"""
Tests for Monk class mechanics (data/features/monk_features.py):
  - _martial_arts_die level scaling
  - MartialArts: lazy weapon-upgrade on first TurnStarted, DEX preference,
    bonus-action unarmed strike, yielding to Flurry of Blows
  - Ki / Flurry of Blows resource + bonus-action mechanics
  - Deflect Missiles damage reduction
  - Stunning Strike save-or-stun mechanics
"""
from types import SimpleNamespace

import pytest

from core.actionTracker import ActionTracker
from core.item import Item
from core.saving_throw import SaveResult
from data.features.monk_features import (
    MartialArts,
    UnarmoredDefenseMonk,
    UnarmoredMovement,
    Ki,
    DeflectMissiles,
    StunningStrike,
    _martial_arts_die,
    _unarmored_movement_bonus,
)


class FakeBus:
    def subscribe(self, *a, **k):
        pass


class FakeCreature:
    def __init__(self, name="Monk", hp=20, max_hp=20, str_mod=0, dex_mod=0,
                 wis_mod=0, con_mod=0, proficiency=2, monk_level=1, speed=30):
        self.name = name
        self.hp = hp
        self.max_hp = max_hp
        self.statblock = SimpleNamespace(mods={
            "Str": str_mod, "Dex": dex_mod, "Wis": wis_mod, "Con": con_mod,
        })
        self.proficiency = proficiency
        self.classes = [("Monk", monk_level)]
        self.actions = ActionTracker()
        self.equipped_items = []
        self.features = []
        self.conditions = set()
        self.speed = speed

    def heal(self, amount):
        healed = min(amount, self.max_hp - self.hp)
        self.hp += healed
        return healed

    def add_condition(self, c):
        self.conditions.add(c.lower())

    def remove_condition(self, c):
        self.conditions.discard(c.lower())

    def has_condition(self, c):
        return c.lower() in self.conditions

    def is_alive(self):
        return self.hp > 0


def make_weapon(name, damage_die, ability="Str", properties=None):
    return Item(
        name, "weapon", damage_die=damage_die, damageType="bludgeoning",
        ability=ability, weapon_type="simple", attack_type="melee",
        normal_range=5, long_range=5, attack_bonus=0, damage_bonus=0,
        properties=properties or [],
    )


# ---------------------------------------------------------------------------
# _martial_arts_die
# ---------------------------------------------------------------------------

class TestMartialArtsDieScaling:
    @pytest.mark.parametrize("level,expected", [
        (1, 4), (4, 4), (5, 6), (10, 6), (11, 8), (16, 8), (17, 10), (20, 10),
    ])
    def test_scaling(self, level, expected):
        assert _martial_arts_die(level) == expected


class TestUnarmoredMovementScaling:
    @pytest.mark.parametrize("level,expected", [
        (1, 10), (5, 10), (6, 15), (9, 15), (10, 20), (13, 20),
        (14, 25), (17, 25), (18, 30), (20, 30),
    ])
    def test_scaling(self, level, expected):
        assert _unarmored_movement_bonus(level) == expected

    def test_attach_adds_bonus_to_speed(self):
        owner = FakeCreature(monk_level=6, speed=30)
        UnarmoredMovement().attach(owner, FakeBus())
        assert owner.speed == 45


# ---------------------------------------------------------------------------
# Martial Arts
# ---------------------------------------------------------------------------

class TestMartialArtsUpgrade:
    def test_attach_only_records_die_size(self):
        owner = FakeCreature(monk_level=5)
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        assert feat._die == 6
        assert owner.equipped_items == []   # nothing injected yet

    def test_first_turn_started_injects_unarmed_strike(self):
        owner = FakeCreature(monk_level=1, str_mod=0, dex_mod=2)
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        names = [i.name for i in owner.equipped_items]
        assert "Unarmed Strike" in names
        unarmed = next(i for i in owner.equipped_items if i.name == "Unarmed Strike")
        assert unarmed.damage_die == "1d4"
        assert unarmed.ability == "Dex"   # dex_mod(2) >= str_mod(0)

    def test_upgrades_equipped_monk_weapon_die_when_bigger(self):
        owner = FakeCreature(monk_level=11, str_mod=1, dex_mod=1)
        owner.equipped_items.append(make_weapon("Shortsword", "1d6", ability="Dex",
                                                  properties=["light", "finesse"]))
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        sword = next(i for i in owner.equipped_items if i.name == "Shortsword")
        assert sword.damage_die == "1d8"   # lv11 martial arts die (d8) beats d6

    def test_does_not_downgrade_bigger_weapon_die(self):
        owner = FakeCreature(monk_level=1, str_mod=1, dex_mod=1)
        owner.equipped_items.append(make_weapon("Shortsword", "1d6", ability="Dex",
                                                  properties=["light", "finesse"]))
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        sword = next(i for i in owner.equipped_items if i.name == "Shortsword")
        assert sword.damage_die == "1d6"   # lv1 martial arts die (d4) doesn't beat d6

    def test_skips_two_handed_and_heavy_weapons(self):
        owner = FakeCreature(monk_level=11, str_mod=3, dex_mod=1)
        owner.equipped_items.append(make_weapon("Quarterstaff", "1d6",
                                                  properties=["two-handed"]))
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        staff = next(i for i in owner.equipped_items if i.name == "Quarterstaff")
        assert staff.damage_die == "1d6"   # excluded -- two-handed
        assert staff.ability == "Str"      # not switched to Dex either

    def test_switches_ability_to_dex_only_when_dex_is_higher(self):
        owner = FakeCreature(monk_level=1, str_mod=3, dex_mod=1)
        owner.equipped_items.append(make_weapon("Quarterstaff", "1d6"))
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        staff = next(i for i in owner.equipped_items if i.name == "Quarterstaff")
        assert staff.ability == "Str"   # str_mod(3) > dex_mod(1) -- keep STR

    def test_grants_bonus_unarmed_strike_when_no_ki_available(self):
        owner = FakeCreature(monk_level=1)
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        assert owner.actions.remaining_extra_attacks == 1
        assert owner.actions.bonus_actions == 0

    def test_yields_bonus_action_to_ki_when_ki_available(self):
        owner = FakeCreature(monk_level=2)
        ki = Ki()
        ki.attach(owner, FakeBus())
        owner.features.append(ki)
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": owner})
        # Martial Arts declined to spend the bonus action -- ki untouched,
        # bonus action still available for Ki's own handler to spend.
        assert ki.ki_remaining == 2
        assert owner.actions.bonus_actions == 1
        assert owner.actions.remaining_extra_attacks == 0

    def test_ignores_other_creatures_turns(self):
        owner = FakeCreature(monk_level=1)
        other = FakeCreature(name="Other")
        feat = MartialArts()
        feat.attach(owner, FakeBus())
        feat.on_turn_started({"creature": other})
        assert owner.equipped_items == []
        assert owner.actions.bonus_actions == 1


# ---------------------------------------------------------------------------
# Unarmored Defense (Monk) -- flag only
# ---------------------------------------------------------------------------

class TestUnarmoredDefenseMonk:
    def test_sets_flag(self):
        owner = FakeCreature()
        UnarmoredDefenseMonk().attach(owner, FakeBus())
        assert owner.monk_unarmored_defense is True


# ---------------------------------------------------------------------------
# Ki / Flurry of Blows
# ---------------------------------------------------------------------------

class TestKi:
    def test_attach_sets_pool_to_monk_level(self):
        owner = FakeCreature(monk_level=7)
        ki = Ki()
        ki.attach(owner, FakeBus())
        assert ki.ki_remaining == 7

    def test_flurry_grants_two_extra_attacks_and_spends_ki(self):
        owner = FakeCreature(monk_level=3)
        ki = Ki()
        ki.attach(owner, FakeBus())
        ki.on_turn_started({"creature": owner})
        assert ki.ki_remaining == 2
        assert owner.actions.remaining_extra_attacks == 2
        assert owner.actions.bonus_actions == 0

    def test_flurry_skipped_when_no_ki_remaining(self):
        owner = FakeCreature(monk_level=1)
        ki = Ki()
        ki.attach(owner, FakeBus())
        ki.ki_remaining = 0
        ki.on_turn_started({"creature": owner})
        assert owner.actions.remaining_extra_attacks == 0
        assert owner.actions.bonus_actions == 1   # untouched

    def test_flurry_skipped_when_bonus_action_already_spent(self):
        owner = FakeCreature(monk_level=3)
        owner.actions.bonus_actions = 0
        ki = Ki()
        ki.attach(owner, FakeBus())
        ki.on_turn_started({"creature": owner})
        assert ki.ki_remaining == 3   # unspent
        assert owner.actions.remaining_extra_attacks == 0


# ---------------------------------------------------------------------------
# Deflect Missiles
# ---------------------------------------------------------------------------

class TestDeflectMissiles:
    def test_reduces_damage_on_ranged_hit(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.monk_features.random.randint", lambda a, b: 5
        )
        owner = FakeCreature(hp=10, max_hp=20, dex_mod=2, monk_level=3)
        feat = DeflectMissiles()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(range=True)
        feat.on_damage_dealt({"target": owner, "attack": attack})
        # reduction = 5 (roll) + 2 (dex) + 3 (level) = 10
        assert owner.hp == 20   # healed back up to cap

    def test_ignores_melee_attacks(self):
        owner = FakeCreature(hp=10, max_hp=20)
        feat = DeflectMissiles()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(range=False)
        feat.on_damage_dealt({"target": owner, "attack": attack})
        assert owner.hp == 10

    def test_ignores_other_creatures_damage(self):
        owner = FakeCreature(hp=10, max_hp=20)
        other = FakeCreature(name="Other", hp=5, max_hp=20)
        feat = DeflectMissiles()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(range=True)
        feat.on_damage_dealt({"target": other, "attack": attack})
        assert owner.hp == 10
        assert other.hp == 5

    def test_requires_reaction_available(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.monk_features.random.randint", lambda a, b: 5
        )
        owner = FakeCreature(hp=10, max_hp=20, dex_mod=2, monk_level=3)
        owner.actions.reactions = 0
        feat = DeflectMissiles()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(range=True)
        feat.on_damage_dealt({"target": owner, "attack": attack})
        assert owner.hp == 10   # no reaction available -- no reduction


# ---------------------------------------------------------------------------
# Stunning Strike
# ---------------------------------------------------------------------------

def _saveresult(success):
    return SaveResult(
        target=None, ability="Con", dc=15, roll=10, bonus=0, total=10,
        success=success,
    )


class TestStunningStrike:
    def test_stuns_target_on_failed_save(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.monk_features.SavingThrow.roll",
            lambda **kwargs: _saveresult(False),
        )
        owner = FakeCreature(monk_level=5, wis_mod=2, proficiency=3)
        ki = Ki()
        ki.attach(owner, FakeBus())
        owner.features.append(ki)
        target = FakeCreature(name="Target")

        feat = StunningStrike()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(item=Item("Unarmed Strike", "weapon", properties=["monk"]))
        feat.on_hit({"attacker": owner, "target": target, "attack": attack})

        assert ki.ki_remaining == 4
        assert feat._stunned_target is target

    def test_no_stun_on_successful_save(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.monk_features.SavingThrow.roll",
            lambda **kwargs: _saveresult(True),
        )
        owner = FakeCreature(monk_level=5)
        ki = Ki()
        ki.attach(owner, FakeBus())
        owner.features.append(ki)
        target = FakeCreature(name="Target")

        feat = StunningStrike()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(item=Item("Unarmed Strike", "weapon", properties=["monk"]))
        feat.on_hit({"attacker": owner, "target": target, "attack": attack})

        assert ki.ki_remaining == 4   # ki still spent on the attempt
        assert feat._stunned_target is None

    def test_skipped_without_ki(self, monkeypatch):
        monkeypatch.setattr(
            "data.features.monk_features.SavingThrow.roll",
            lambda **kwargs: _saveresult(False),
        )
        owner = FakeCreature(monk_level=5)
        ki = Ki()
        ki.attach(owner, FakeBus())
        ki.ki_remaining = 0
        owner.features.append(ki)
        target = FakeCreature(name="Target")

        feat = StunningStrike()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(item=Item("Unarmed Strike", "weapon", properties=["monk"]))
        feat.on_hit({"attacker": owner, "target": target, "attack": attack})

        assert feat._stunned_target is None

    def test_ignores_non_monk_weapons(self):
        owner = FakeCreature(monk_level=5)
        ki = Ki()
        ki.attach(owner, FakeBus())
        owner.features.append(ki)
        target = FakeCreature(name="Target")

        feat = StunningStrike()
        feat.attach(owner, FakeBus())
        attack = SimpleNamespace(item=Item("Longbow", "weapon", properties=[]))
        feat.on_hit({"attacker": owner, "target": target, "attack": attack})

        assert ki.ki_remaining == 5   # untouched
        assert feat._stunned_target is None

    def test_clears_stun_on_own_next_turn(self):
        owner = FakeCreature(monk_level=5)
        target = FakeCreature(name="Target")
        target.add_condition("stunned")

        feat = StunningStrike()
        feat.attach(owner, FakeBus())
        feat._stunned_target = target
        feat.on_turn_started({"creature": owner})

        assert not target.has_condition("stunned")
        assert feat._stunned_target is None
