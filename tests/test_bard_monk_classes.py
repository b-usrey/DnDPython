"""
Tests for the Bard and Monk class JSON files (data/classes/bard.json,
data/classes/monk.json) plus their new Python features
(data/features/bard_features.py, data/features/monk_features.py).
"""
import io
import contextlib

from core.events import EventBus
from core.player_character import PlayerCharacter


def make_character(class_name, level, subclass, stats):
    event = EventBus()
    with contextlib.redirect_stdout(io.StringIO()):
        return PlayerCharacter(
            f"Test{class_name}", [[class_name, level]], {class_name: subclass},
            stats, event, choices=[],
        )


BARD_STATS = {"Str": 8, "Dex": 14, "Con": 12, "Int": 10, "Wis": 10, "Cha": 18}
MONK_STATS = {"Str": 10, "Dex": 18, "Con": 14, "Int": 10, "Wis": 16, "Cha": 8}


class TestBardClass:
    def test_constructs_without_crashing(self):
        make_character("Bard", 5, "College of Lore", BARD_STATS)

    def test_has_expected_combat_features_at_level_5(self):
        bard = make_character("Bard", 5, "College of Lore", BARD_STATS)
        names = {f.name for f in bard.features}
        for expected in ("Spellcasting", "BardicInspiration", "ViciousMockery",
                          "HealingWord", "Thunderwave", "CureWounds", "HoldPerson"):
            assert expected in names, f"missing {expected}"

    def test_spell_slots_match_full_caster_progression_at_level_5(self):
        bard = make_character("Bard", 5, "College of Lore", BARD_STATS)
        assert bard.spell_slots.remaining() == {1: 4, 2: 3, 3: 2}

    def test_spell_dc_and_attack_use_charisma(self):
        bard = make_character("Bard", 5, "College of Lore", BARD_STATS)
        # Cha 18 -> +4 mod; level 5 -> proficiency +3
        assert bard.spell_slots.spell_attack == 7
        assert bard.spell_slots.spell_dc == 15

    def test_college_of_valor_subclass_also_constructs(self):
        make_character("Bard", 6, "College of Valor", BARD_STATS)

    def test_college_of_valor_gets_extra_attack(self):
        bard = make_character("Bard", 6, "College of Valor", BARD_STATS)
        names = {f.name for f in bard.features}
        assert "ExtraAttack" in names
        assert bard.actions.extra_attacks == 1

    def test_bardic_inspiration_uses_from_charisma_and_level(self):
        bard = make_character("Bard", 5, "College of Lore", BARD_STATS)
        insp = next(f for f in bard.features if f.name == "BardicInspiration")
        assert insp._uses_remaining == 4   # Cha 18 -> +4 mod
        assert insp._die_size == 8         # level 5 -> d8


class TestMonkClass:
    def test_constructs_without_crashing(self):
        make_character("Monk", 5, "Way of the Open Hand", MONK_STATS)

    def test_has_expected_combat_features_at_level_5(self):
        monk = make_character("Monk", 5, "Way of the Open Hand", MONK_STATS)
        names = {f.name for f in monk.features}
        for expected in ("MartialArts", "UnarmoredDefenseMonk", "Ki",
                          "UnarmoredMovement", "DeflectMissiles",
                          "ExtraAttack", "StunningStrike"):
            assert expected in names, f"missing {expected}"

    def test_ki_pool_matches_monk_level(self):
        monk = make_character("Monk", 7, "Way of Shadow", MONK_STATS)
        ki = next(f for f in monk.features if f.name == "Ki")
        assert ki.ki_remaining == 7

    def test_martial_arts_die_matches_level(self):
        monk = make_character("Monk", 11, "Way of Shadow", MONK_STATS)
        ma = next(f for f in monk.features if f.name == "MartialArts")
        assert ma._die == 8

    def test_unarmored_movement_bonus_applied(self):
        monk = make_character("Monk", 6, "Way of the Open Hand", MONK_STATS)
        assert monk.speed == 45   # base 30 + 15 (lv6 bonus)

    def test_extra_attack_only_after_level_5(self):
        monk = make_character("Monk", 4, "Way of the Open Hand", MONK_STATS)
        names = {f.name for f in monk.features}
        assert "ExtraAttack" not in names
        assert "StunningStrike" not in names

    def test_way_of_shadow_subclass_also_constructs(self):
        make_character("Monk", 3, "Way of Shadow", MONK_STATS)

    def test_way_of_the_four_elements_subclass_also_constructs(self):
        make_character("Monk", 3, "Way of the Four Elements", MONK_STATS)
