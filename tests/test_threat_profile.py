"""
Tests for ThreatProfile: danger_score, _static_damage, threat_score.
"""
import pytest
from types import SimpleNamespace
from core.team_memory import ThreatProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_creature(equipped_items=None, attack_templates=None, stat_mods=None):
    mods = stat_mods or {"Str": 3}
    return SimpleNamespace(
        name="TestCreature",
        equipped_items=equipped_items or [],
        _attack_templates=attack_templates or [],
        statblock=SimpleNamespace(mods=mods),
        hp=50,
        max_hp=100,
    )


def make_weapon_item(name="Longsword", damage_die="1d8", ability="Str"):
    return SimpleNamespace(name=name, item_type="weapon", damage_die=damage_die, ability=ability)


# ---------------------------------------------------------------------------
# _static_damage
# ---------------------------------------------------------------------------

class TestStaticDamage:
    def test_equipped_weapon_avg(self):
        item = make_weapon_item(damage_die="1d8", ability="Str")
        profile = ThreatProfile(creature=make_creature(equipped_items=[item], stat_mods={"Str": 3}))
        # 1d8 avg=4.5, +3 Str = 7.5
        assert profile._static_damage() == pytest.approx(7.5)

    def test_attack_template_avg(self):
        atk = {"damage_die": 6, "damage_mod": 2}
        profile = ThreatProfile(creature=make_creature(attack_templates=[atk]))
        # 1d6 avg=3.5, +2 mod = 5.5
        assert profile._static_damage() == pytest.approx(5.5)

    def test_no_weapons_returns_default(self):
        profile = ThreatProfile(creature=make_creature())
        assert profile._static_damage() == pytest.approx(5.0)

    def test_non_weapon_item_skipped(self):
        armor = SimpleNamespace(name="Plate", item_type="armor")
        profile = ThreatProfile(creature=make_creature(equipped_items=[armor]))
        assert profile._static_damage() == pytest.approx(5.0)

    def test_multiple_weapons_averaged(self):
        dagger = make_weapon_item("Dagger", damage_die="1d4", ability="Str")
        greatsword = make_weapon_item("Greatsword", damage_die="2d6", ability="Str")
        profile = ThreatProfile(
            creature=make_creature(equipped_items=[dagger, greatsword], stat_mods={"Str": 0})
        )
        # Dagger: 1*(4+1)/2 + 0 = 2.5   Greatsword: 2*(6+1)/2 + 0 = 7.0
        # avg = (2.5 + 7.0) / 2 = 4.75
        assert profile._static_damage() == pytest.approx(4.75)

    def test_template_zero_mod(self):
        atk = {"damage_die": 8, "damage_mod": 0}
        profile = ThreatProfile(creature=make_creature(attack_templates=[atk]))
        # 1d8 avg = 4.5
        assert profile._static_damage() == pytest.approx(4.5)


# ---------------------------------------------------------------------------
# danger_score
# ---------------------------------------------------------------------------

class TestDangerScore:
    def test_observed_data_used(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=4,
            hits_landed=3,
            damage_rolls_seen=[10, 12, 8, 14],
        )
        # avg_damage = 44/4 = 11.0, hit_rate = 3/4 = 0.75
        assert profile.danger_score == pytest.approx(11.0 * 0.75)

    def test_fallback_when_no_observed_data(self):
        item = make_weapon_item(damage_die="1d8", ability="Str")
        profile = ThreatProfile(creature=make_creature(equipped_items=[item], stat_mods={"Str": 3}))
        # static_damage = 7.5, fallback = 7.5 * 0.5 = 3.75
        assert profile.danger_score == pytest.approx(3.75)

    def test_fallback_requires_both_attacks_and_rolls(self):
        # attacks_observed > 0 but no damage_rolls_seen → still uses fallback
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=3,
            hits_landed=0,
            damage_rolls_seen=[],
        )
        assert profile.danger_score == pytest.approx(5.0 * 0.5)

    def test_hp_independent(self):
        """danger_score must not change as HP changes — that's the whole point."""
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=2,
            hits_landed=2,
            damage_rolls_seen=[15, 15],
            last_known_hp=5,
            last_known_max_hp=100,
        )
        score_low_hp = profile.danger_score
        profile.last_known_hp = 100
        assert profile.danger_score == pytest.approx(score_low_hp)

    def test_perfect_hit_rate(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=3,
            hits_landed=3,
            damage_rolls_seen=[10, 10, 10],
        )
        # hit_rate = 1.0, avg = 10.0
        assert profile.danger_score == pytest.approx(10.0)

    def test_zero_hit_rate(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=5,
            hits_landed=0,
            damage_rolls_seen=[8, 8, 8, 8, 8],
        )
        # hit_rate = 0/5 = 0.0 → danger = 0
        assert profile.danger_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# threat_score (legacy composite)
# ---------------------------------------------------------------------------

class TestThreatScore:
    def test_decays_with_hp(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=2,
            hits_landed=2,
            damage_rolls_seen=[10, 10],
            last_known_hp=25,
            last_known_max_hp=100,
        )
        # hp_fraction=0.25, danger=10.0
        assert profile.threat_score == pytest.approx(10.0 * 0.25)

    def test_equals_danger_at_full_hp(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=2,
            hits_landed=2,
            damage_rolls_seen=[10, 10],
            last_known_hp=100,
            last_known_max_hp=100,
        )
        assert profile.threat_score == pytest.approx(profile.danger_score)

    def test_zero_max_hp_defaults_fraction_to_one(self):
        profile = ThreatProfile(
            creature=make_creature(),
            attacks_observed=1,
            hits_landed=1,
            damage_rolls_seen=[8],
            last_known_hp=8,
            last_known_max_hp=0,
        )
        assert profile.threat_score == pytest.approx(profile.danger_score * 1.0)
