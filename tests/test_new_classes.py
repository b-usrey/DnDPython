"""
Tests for the Sorcerer and Druid class JSON files (data/classes/sorcerer.json,
data/classes/druid.json) -- both lean on spell/mechanic building blocks that
already existed (Wizard/Sorc.-tagged blast spells, Druid-tagged PoisonSpray/
MoonbeamSpell, and the universal Spellcasting feature already registering
both classes' ability/caster-type), so these files mainly needed to exist
and wire up correctly.
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


SORC_STATS  = {"Str": 8, "Dex": 14, "Con": 14, "Int": 10, "Wis": 10, "Cha": 18}
DRUID_STATS = {"Str": 10, "Dex": 14, "Con": 14, "Int": 10, "Wis": 18, "Cha": 8}


class TestSorcererClass:
    def test_constructs_without_crashing(self):
        make_character("Sorcerer", 5, "Draconic Bloodline", SORC_STATS)

    def test_has_expected_combat_spells_at_level_5(self):
        sorc = make_character("Sorcerer", 5, "Draconic Bloodline", SORC_STATS)
        names = {f.name for f in sorc.features}
        for expected in ("Spellcasting", "FireBolt", "RayOfFrost",
                          "MagicMissile", "BurningHands", "ScorchingRay",
                          "MirrorImage", "Fireball", "LightningBolt"):
            assert expected in names, f"missing {expected}"

    def test_spell_slots_match_full_caster_progression_at_level_5(self):
        sorc = make_character("Sorcerer", 5, "Draconic Bloodline", SORC_STATS)
        assert sorc.spell_slots.remaining() == {1: 4, 2: 3, 3: 2}

    def test_spell_dc_and_attack_use_charisma(self):
        sorc = make_character("Sorcerer", 5, "Draconic Bloodline", SORC_STATS)
        # Cha 18 -> +4 mod; level 5 -> proficiency +3
        assert sorc.spell_slots.spell_attack == 7
        assert sorc.spell_slots.spell_dc == 15

    def test_wild_magic_subclass_also_constructs(self):
        make_character("Sorcerer", 6, "Wild Magic", SORC_STATS)

    def test_higher_level_gets_cone_of_cold(self):
        sorc = make_character("Sorcerer", 9, "Draconic Bloodline", SORC_STATS)
        names = {f.name for f in sorc.features}
        assert "ConeOfCold" in names


class TestDruidClass:
    def test_constructs_without_crashing(self):
        make_character("Druid", 5, "Circle of the Moon", DRUID_STATS)

    def test_has_expected_combat_spells_at_level_5(self):
        druid = make_character("Druid", 5, "Circle of the Moon", DRUID_STATS)
        names = {f.name for f in druid.features}
        for expected in ("Spellcasting", "PoisonSpray", "HealingWord",
                          "MoonbeamSpell", "CureWounds", "Blight"):
            assert expected in names, f"missing {expected}"

    def test_spell_slots_match_full_caster_progression_at_level_5(self):
        druid = make_character("Druid", 5, "Circle of the Moon", DRUID_STATS)
        assert druid.spell_slots.remaining() == {1: 4, 2: 3, 3: 2}

    def test_spell_dc_and_attack_use_wisdom(self):
        druid = make_character("Druid", 5, "Circle of the Moon", DRUID_STATS)
        # Wis 18 -> +4 mod; level 5 -> proficiency +3
        assert druid.spell_slots.spell_attack == 7
        assert druid.spell_slots.spell_dc == 15

    def test_circle_of_the_land_subclass_also_constructs(self):
        make_character("Druid", 3, "Circle of the Land", DRUID_STATS)
