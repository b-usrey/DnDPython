"""
Tests for the 3 new "identity" features added to TeamMemory.get_state_vector
(indices 12-14: has_ranged_option, relative_tankiness, has_spell_resources).

These exist so a single policy (DQN/Evo) can tell *which* creature it's
controlling apart from *what situation* it's in -- without them, a fighter
and an archer facing the identical fight get an identical state vector.
"""
from types import SimpleNamespace

import pytest

from core.team_memory import TeamMemory


class _FakeEventBus:
    def subscribe(self, *_): pass


class _FakeBattleMap:
    """Distances are looked up from a dict keyed by (a, b) id pairs, set
    per-test; defaults to "adjacent" (distance 0) for anything unset."""
    def __init__(self, distances=None):
        self._distances = distances or {}

    def all_creatures(self):
        return []

    def distance_between(self, a, b):
        return self._distances.get((id(a), id(b)), 10)


def make_memory(battle_map=None):
    mem = TeamMemory("blue", _FakeEventBus(), battle_map or _FakeBattleMap())
    return mem


def make_creature(hp=30, max_hp=30, equipped_items=None, attack_templates=None,
                   spell_slots=None, name="Creature"):
    kwargs = dict(
        name=name, hp=hp, max_hp=max_hp,
        equipped_items=equipped_items or [],
        _attack_templates=attack_templates or [],
    )
    c = SimpleNamespace(**kwargs)
    if spell_slots is not None:
        c.spell_slots = spell_slots
    return c


def make_weapon(attack_type="melee"):
    return SimpleNamespace(item_type="weapon", attack_type=attack_type)


# ---------------------------------------------------------------------------
# _has_ranged_option
# ---------------------------------------------------------------------------

class TestHasRangedOption:
    def test_true_for_equipped_ranged_weapon(self):
        c = make_creature(equipped_items=[make_weapon("range")])
        assert TeamMemory._has_ranged_option(c) is True

    def test_false_for_melee_only(self):
        c = make_creature(equipped_items=[make_weapon("melee")])
        assert TeamMemory._has_ranged_option(c) is False

    def test_false_with_no_weapons(self):
        assert TeamMemory._has_ranged_option(make_creature()) is False

    def test_true_for_monster_ranged_attack_template(self):
        c = make_creature(attack_templates=[{"name": "Shortbow", "attack_type": "range"}])
        assert TeamMemory._has_ranged_option(c) is True

    def test_false_for_monster_melee_only_template(self):
        c = make_creature(attack_templates=[{"name": "Bite", "attack_type": "melee"}])
        assert TeamMemory._has_ranged_option(c) is False

    def test_ignores_non_weapon_items(self):
        armor = SimpleNamespace(item_type="armor", attack_type="range")  # nonsensical but shouldn't count
        c = make_creature(equipped_items=[armor])
        assert TeamMemory._has_ranged_option(c) is False

    def test_true_if_any_of_multiple_weapons_is_ranged(self):
        c = make_creature(equipped_items=[make_weapon("melee"), make_weapon("range")])
        assert TeamMemory._has_ranged_option(c) is True


# ---------------------------------------------------------------------------
# get_state_vector: identity features (indices 12-14)
# ---------------------------------------------------------------------------

class TestIdentityFeaturesInStateVector:
    def test_vector_has_15_features(self):
        mem = make_memory()
        c = make_creature()
        vec = mem.get_state_vector(c, enemies=[], allies=[])
        assert len(vec) == 15

    def test_is_ranged_feature_matches_helper(self):
        mem = make_memory()
        ranged = make_creature(equipped_items=[make_weapon("range")])
        melee  = make_creature(equipped_items=[make_weapon("melee")])
        assert mem.get_state_vector(ranged, enemies=[], allies=[])[12] == 1.0
        assert mem.get_state_vector(melee,  enemies=[], allies=[])[12] == 0.0

    def test_relative_tankiness_is_share_of_team_max_hp(self):
        mem = make_memory()
        tank   = make_creature(max_hp=90)
        squishy = make_creature(max_hp=30)
        # tank's perspective: 90 / (90+30) = 0.75
        vec_tank = mem.get_state_vector(tank, enemies=[], allies=[squishy])
        assert vec_tank[13] == pytest.approx(0.75)
        # squishy's perspective: 30 / (90+30) = 0.25
        vec_squishy = mem.get_state_vector(squishy, enemies=[], allies=[tank])
        assert vec_squishy[13] == pytest.approx(0.25)

    def test_relative_tankiness_solo_creature_is_full_share(self):
        mem = make_memory()
        solo = make_creature(max_hp=50)
        assert mem.get_state_vector(solo, enemies=[], allies=[])[13] == pytest.approx(1.0)

    def test_non_caster_always_has_spell_resources(self):
        mem = make_memory()
        martial = make_creature()   # no spell_slots attribute at all
        assert mem.get_state_vector(martial, enemies=[], allies=[])[14] == 1.0

    def test_caster_with_slots_remaining(self):
        mem = make_memory()
        caster = make_creature(spell_slots=SimpleNamespace(has_slot=lambda lvl=1: True))
        assert mem.get_state_vector(caster, enemies=[], allies=[])[14] == 1.0

    def test_caster_out_of_slots(self):
        mem = make_memory()
        caster = make_creature(spell_slots=SimpleNamespace(has_slot=lambda lvl=1: False))
        assert mem.get_state_vector(caster, enemies=[], allies=[])[14] == 0.0

    def test_identity_features_dont_disturb_existing_core_features(self):
        """Sanity check that indices 0-11 are unaffected by this change --
        spot-check own HP ratio (0) and team HP ratio (1)."""
        mem = make_memory()
        c = make_creature(hp=15, max_hp=30)
        vec = mem.get_state_vector(c, enemies=[], allies=[])
        assert vec[0] == pytest.approx(0.5)
        assert vec[1] == pytest.approx(0.5)
