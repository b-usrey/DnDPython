"""
Tests for utils.scenarioLoader.normalize_weapon_role / apply_weapon_roles
and for CombatEnv honouring weapon_role.

Background: main.py, the TheDM API and CombatEnv each had their own copy
of the weapon_role rule -- and CombatEnv's copy assigned every monster
every weapon regardless of role. The web builder also emitted tokens
("range", "mixed") that no path recognised, so they silently meant
"random". One shared helper now owns the rule and accepts the legacy
spellings, so a scenario JSON is the same fight everywhere.
"""
import io
import contextlib
import random

import importlib, pkgutil, data.features
for _m in pkgutil.iter_modules(data.features.__path__):
    if _m.name != "base":
        importlib.import_module(f"data.features.{_m.name}")

from core.events import EventBus
from core.ml_strategy import CombatEnv
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import (
    ScenarioLoader, apply_weapon_roles, normalize_weapon_role,
)


HERO = {
    "name": "Hero",
    "classes": [["Fighter", 3]],
    "subclasses": {},
    "stats": {"Str": 16, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
    "choices": [],
    "items": ["Longsword"],
    "equipped": ["Longsword"],
    "features": [],
}


def scenario(monsters):
    return {
        "name": "weapon role test",
        "max_rounds": 3,
        "map": {"width": 10, "height": 8, "walls": [], "difficult_terrain": []},
        "positions": {"Hero": [1, 4]},
        "players": [HERO],
        "monsters": monsters,
    }


def load_monsters(sc):
    event   = EventBus()
    loader  = ScenarioLoader(CreatureFactory(), event)
    with contextlib.redirect_stdout(io.StringIO()):
        _players, monsters = loader.load(sc)
    return monsters


def kinds(monster):
    return sorted({a.get("attack_type", "melee") for a in monster._attack_templates})


# ---------------------------------------------------------------------------
# normalize_weapon_role
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_canonical_tokens_pass_through(self):
        for tok in ("random", "melee", "ranged", "all"):
            assert normalize_weapon_role(tok) == tok

    def test_legacy_builder_spellings_map_to_intent(self):
        # These are what the web builder used to emit; every path treated
        # them as "random" because nobody recognised them.
        assert normalize_weapon_role("range") == "ranged"
        assert normalize_weapon_role("mixed") == "random"

    def test_case_and_whitespace_insensitive(self):
        assert normalize_weapon_role("  MELEE ") == "melee"

    def test_missing_or_garbage_is_random(self):
        assert normalize_weapon_role(None) == "random"
        assert normalize_weapon_role("") == "random"
        assert normalize_weapon_role("banana") == "random"


# ---------------------------------------------------------------------------
# apply_weapon_roles -- goblins carry a Scimitar (melee) and a Shortbow (ranged)
# ---------------------------------------------------------------------------

class TestApplyWeaponRoles:
    def test_all_gives_every_weapon(self):
        sc = scenario([{"type": "GOBLIN", "count": 2, "weapon_role": "all"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert all(kinds(m) == ["melee", "range"] for m in monsters)

    def test_melee_strips_the_bow(self):
        sc = scenario([{"type": "GOBLIN", "count": 2, "weapon_role": "melee"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert all(kinds(m) == ["melee"] for m in monsters)

    def test_ranged_strips_the_blade(self):
        sc = scenario([{"type": "GOBLIN", "count": 2, "weapon_role": "ranged"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert all(kinds(m) == ["range"] for m in monsters)

    def test_legacy_range_token_means_ranged(self):
        sc = scenario([{"type": "GOBLIN", "count": 2, "weapon_role": "range"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert all(kinds(m) == ["range"] for m in monsters)

    def test_random_gives_each_monster_exactly_one_kind(self):
        sc = scenario([{"type": "GOBLIN", "count": 6, "weapon_role": "random"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters, rng=random.Random(0))
        assert all(len(kinds(m)) == 1 for m in monsters)

    def test_random_on_single_kind_monster_keeps_everything(self):
        # Ghasts only have melee attacks: a coin flip makes no sense, so
        # they keep the full list rather than a 50% chance of nothing.
        sc = scenario([{"type": "GHAST", "count": 2, "weapon_role": "random"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters, rng=random.Random(0))
        assert all(m._attack_templates and kinds(m) == ["melee"] for m in monsters)

    def test_ranged_on_melee_only_monster_falls_back_to_all(self):
        sc = scenario([{"type": "GHAST", "count": 1, "weapon_role": "ranged"}])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert kinds(monsters[0]) == ["melee"]

    def test_groups_are_matched_by_order(self):
        sc = scenario([
            {"type": "GOBLIN", "count": 1, "weapon_role": "melee"},
            {"type": "GOBLIN", "count": 1, "weapon_role": "ranged"},
        ])
        monsters = load_monsters(sc)
        apply_weapon_roles(sc, monsters)
        assert kinds(monsters[0]) == ["melee"]
        assert kinds(monsters[1]) == ["range"]

    def test_reports_assignments(self):
        sc = scenario([{"type": "GOBLIN", "count": 1, "weapon_role": "melee"}])
        monsters = load_monsters(sc)
        assigned = apply_weapon_roles(sc, monsters)
        assert assigned == [(monsters[0], "melee")]


# ---------------------------------------------------------------------------
# CombatEnv -- the training/eval path -- now honours the role too
# ---------------------------------------------------------------------------

class TestCombatEnvHonoursRole:
    def _red_kinds(self, role):
        sc = scenario([{"type": "GOBLIN", "count": 2, "weapon_role": role}])
        env = CombatEnv(scenario_data=sc, trained_team="red", silent=True)
        with contextlib.redirect_stdout(io.StringIO()):
            env.reset()
        reds = [c for _, c in env.cm.initiative.initiative_order if c.team == "red"]
        return [kinds(c) for c in reds]

    def test_ranged_role_reaches_training_monsters(self):
        assert self._red_kinds("ranged") == [["range"], ["range"]]

    def test_all_role_matches_the_old_unconditional_behaviour(self):
        # The five calibrated training/eval scenarios were rewritten to say
        # "all" so their balance is unchanged by this fix.
        assert self._red_kinds("all") == [["melee", "range"], ["melee", "range"]]
