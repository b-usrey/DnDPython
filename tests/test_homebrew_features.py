"""
Tests for the data-driven homebrew feature system (data/features/homebrew.py):
  - validate_homebrew_definition(): schema/safety-limit enforcement
  - validate_homebrew_class(): whole-class-JSON validation
  - HomebrewFeature: runtime behaviour for each trigger/effect, resource
    gating (max_uses/recharge), and the reaction-economy/unconscious guard
    on the damage_dealt trigger
  - Creature._add_feature_by_name(name, homebrew_def=...): wiring +
    graceful rejection of an invalid definition
"""
from types import SimpleNamespace

from core.creature import Creature
from core.events import EventBus
from data.features.homebrew import (
    HomebrewFeature,
    validate_homebrew_definition,
    validate_homebrew_class,
)


def make_stats():
    return {"Str": 12, "Dex": 14, "Con": 12, "Int": 10, "Wis": 10, "Cha": 10}


def make_creature(name="Hero", hp=20, ac=14):
    return Creature(name, hp, ac, make_stats(), EventBus())


def fake_attack(critical=False, ranged=False):
    return SimpleNamespace(
        extra_dice=[], damage_mod=0, advantage=False, disadvantage=False,
        critical=critical, range=ranged,
    )


# ---------------------------------------------------------------------------
# validate_homebrew_definition
# ---------------------------------------------------------------------------

class TestValidateDefinition:
    def _valid_hit_def(self, **overrides):
        d = {
            "name": "Frost Strike",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}],
            "effects": [{"type": "add_damage_dice", "count": 1, "die": 6}],
        }
        d.update(overrides)
        return d

    def test_accepts_a_well_formed_definition(self):
        assert validate_homebrew_definition(self._valid_hit_def()) == []

    def test_rejects_non_dict(self):
        assert validate_homebrew_definition("not a dict") != []

    def test_rejects_missing_name(self):
        d = self._valid_hit_def()
        del d["name"]
        assert any("name" in e for e in validate_homebrew_definition(d))

    def test_rejects_oversized_name(self):
        d = self._valid_hit_def(name="x" * 100)
        assert any("name" in e for e in validate_homebrew_definition(d))

    def test_rejects_unknown_trigger(self):
        d = self._valid_hit_def(trigger="totally_made_up_event")
        assert any("trigger" in e for e in validate_homebrew_definition(d))

    def test_rejects_attack_pipeline_trigger_without_identity_condition(self):
        """hit/attack/damage_dealt must anchor to the owner, or they'd fire
        on every attack in the whole combat, not just the owner's."""
        d = self._valid_hit_def(conditions=[])
        errors = validate_homebrew_definition(d)
        assert any("identity" in e or "attacker_is_owner" in e for e in errors)

    def test_accepts_target_is_owner_as_identity_condition(self):
        d = self._valid_hit_def(
            trigger="damage_dealt",
            conditions=[{"type": "target_is_owner"}],
            effects=[{"type": "heal", "amount": 5}],
        )
        assert validate_homebrew_definition(d) == []

    def test_rejects_effect_not_valid_for_trigger(self):
        """add_damage_dice only makes sense on 'hit', not 'TurnStarted'."""
        d = self._valid_hit_def(
            trigger="TurnStarted",
            conditions=[],
            effects=[{"type": "add_damage_dice", "count": 1, "die": 6}],
        )
        assert any("doesn't apply to trigger" in e for e in validate_homebrew_definition(d))

    def test_rejects_condition_not_valid_for_trigger(self):
        d = self._valid_hit_def(
            trigger="TurnStarted",
            conditions=[{"type": "is_critical"}],
            effects=[{"type": "heal", "amount": 5}],
        )
        assert any("doesn't apply to trigger" in e for e in validate_homebrew_definition(d))

    def test_rejects_oversized_dice_count(self):
        d = self._valid_hit_def(effects=[{"type": "add_damage_dice", "count": 999, "die": 6}])
        assert any("count" in e for e in validate_homebrew_definition(d))

    def test_rejects_invalid_die_size(self):
        d = self._valid_hit_def(effects=[{"type": "add_damage_dice", "count": 1, "die": 7}])
        assert any("die" in e for e in validate_homebrew_definition(d))

    def test_rejects_oversized_flat_damage(self):
        d = self._valid_hit_def(effects=[{"type": "add_flat_damage", "amount": 99999}])
        assert any("amount" in e for e in validate_homebrew_definition(d))

    def test_rejects_missing_effects(self):
        d = self._valid_hit_def(effects=[])
        assert any("effects" in e for e in validate_homebrew_definition(d))

    def test_rejects_max_uses_without_recharge(self):
        d = self._valid_hit_def(max_uses=1)   # recharge defaults to at_will
        assert any("max_uses" in e for e in validate_homebrew_definition(d))

    def test_rejects_recharge_without_max_uses(self):
        d = self._valid_hit_def(recharge="turn")
        assert any("max_uses" in e for e in validate_homebrew_definition(d))

    def test_accepts_recharge_with_max_uses(self):
        d = self._valid_hit_def(recharge="turn", max_uses=1)
        assert validate_homebrew_definition(d) == []

    def test_rejects_ac_delta_of_zero(self):
        d = self._valid_hit_def(
            trigger="TurnStarted", conditions=[],
            effects=[{"type": "modify_ac", "delta": 0}],
        )
        assert any("delta" in e for e in validate_homebrew_definition(d))

    def test_rejects_oversized_ac_delta(self):
        d = self._valid_hit_def(
            trigger="TurnStarted", conditions=[],
            effects=[{"type": "modify_ac", "delta": 999}],
        )
        assert any("delta" in e for e in validate_homebrew_definition(d))


# ---------------------------------------------------------------------------
# validate_homebrew_class
# ---------------------------------------------------------------------------

class TestValidateClass:
    def _valid_class(self):
        return {
            "hit_die": 8,
            "features_by_level": {
                "1": [{"name": "Second Wind"}],   # a real, registered feature
            },
        }

    def test_accepts_class_referencing_real_features(self):
        assert validate_homebrew_class(self._valid_class()) == []

    def test_rejects_unknown_feature_name(self):
        d = self._valid_class()
        d["features_by_level"]["1"] = [{"name": "Definitely Not A Real Feature"}]
        errors = validate_homebrew_class(d)
        assert any("neither a homebrew block nor a known feature" in e for e in errors)

    def test_accepts_embedded_valid_homebrew(self):
        d = self._valid_class()
        d["features_by_level"]["1"] = [{
            "name": "Frost Strike",
            "homebrew": {
                "name": "Frost Strike",
                "trigger": "hit",
                "conditions": [{"type": "attacker_is_owner"}],
                "effects": [{"type": "add_damage_dice", "count": 1, "die": 6}],
            },
        }]
        assert validate_homebrew_class(d) == []

    def test_rejects_embedded_invalid_homebrew(self):
        d = self._valid_class()
        d["features_by_level"]["1"] = [{
            "name": "Bad Homebrew",
            "homebrew": {"name": "Bad Homebrew", "trigger": "not_a_real_trigger"},
        }]
        errors = validate_homebrew_class(d)
        assert any("Bad Homebrew" in e for e in errors)

    def test_rejects_missing_hit_die(self):
        d = self._valid_class()
        del d["hit_die"]
        assert any("hit_die" in e for e in validate_homebrew_class(d))

    def test_validates_subclass_features_too(self):
        d = self._valid_class()
        d["subclasses"] = {
            "champion": {
                "features_by_level": {
                    "3": [{"name": "Nonexistent Subclass Feature"}]
                }
            }
        }
        errors = validate_homebrew_class(d)
        assert any("champion" in e for e in errors)


# ---------------------------------------------------------------------------
# HomebrewFeature runtime behaviour
# ---------------------------------------------------------------------------

class TestHitTrigger:
    def test_adds_damage_dice_only_when_owner_is_attacker(self):
        owner = make_creature("Hero")
        other = make_creature("Other")
        defn = {
            "name": "Frost Strike",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}],
            "effects": [{"type": "add_damage_dice", "count": 1, "die": 6}],
        }
        owner._add_feature_by_name("Frost Strike", homebrew_def=defn)

        attack = fake_attack()
        owner.event_manager.broadcast("hit", {"attacker": owner, "target": other, "attack": attack})
        assert attack.extra_dice == [(1, 6)]

        attack2 = fake_attack()
        owner.event_manager.broadcast("hit", {"attacker": other, "target": owner, "attack": attack2})
        assert attack2.extra_dice == []   # owner wasn't the attacker — no rider

    def test_add_flat_damage(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Bonus Damage",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}],
            "effects": [{"type": "add_flat_damage", "amount": 3}],
        }
        owner._add_feature_by_name("Bonus Damage", homebrew_def=defn)
        attack = fake_attack()
        owner.event_manager.broadcast("hit", {"attacker": owner, "target": None, "attack": attack})
        assert attack.damage_mod == 3

    def test_condition_gate_is_critical(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Crit Rider",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}, {"type": "is_critical"}],
            "effects": [{"type": "add_damage_dice", "count": 1, "die": 8}],
        }
        owner._add_feature_by_name("Crit Rider", homebrew_def=defn)

        normal_hit = fake_attack(critical=False)
        owner.event_manager.broadcast("hit", {"attacker": owner, "attack": normal_hit})
        assert normal_hit.extra_dice == []

        crit_hit = fake_attack(critical=True)
        owner.event_manager.broadcast("hit", {"attacker": owner, "attack": crit_hit})
        assert crit_hit.extra_dice == [(1, 8)]


class TestAttackTrigger:
    def test_grants_advantage_when_owner_is_target(self):
        """Simulates a homebrew 'foes have advantage attacking you' rider —
        mirrors how the real prone/restrained condition handling works."""
        owner = make_creature("Hero")
        attacker = make_creature("Foe")
        defn = {
            "name": "Exposed",
            "trigger": "attack",
            "conditions": [{"type": "target_is_owner"}],
            "effects": [{"type": "add_advantage"}],
        }
        owner._add_feature_by_name("Exposed", homebrew_def=defn)

        attack = fake_attack()
        owner.event_manager.broadcast("attack", {"attacker": attacker, "target": owner, "attack": attack})
        assert attack.advantage is True

    def test_no_effect_when_owner_not_involved(self):
        owner = make_creature("Hero")
        bystander_a = make_creature("A")
        bystander_b = make_creature("B")
        defn = {
            "name": "Exposed",
            "trigger": "attack",
            "conditions": [{"type": "target_is_owner"}],
            "effects": [{"type": "add_advantage"}],
        }
        owner._add_feature_by_name("Exposed", homebrew_def=defn)

        attack = fake_attack()
        owner.event_manager.broadcast("attack", {"attacker": bystander_a, "target": bystander_b, "attack": attack})
        assert attack.advantage is False


class TestSavingThrowTrigger:
    def test_grants_advantage_on_matching_ability_like_danger_sense(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Homebrew Danger Sense",
            "trigger": "saving_throw",
            "conditions": [{"type": "target_is_owner"}, {"type": "ability_is", "ability": "Dex"}],
            "effects": [{"type": "add_advantage"}],
        }
        owner._add_feature_by_name("Homebrew Danger Sense", homebrew_def=defn)

        ctx = {"target": owner, "ability": "Dex", "advantage": False, "disadvantage": False}
        owner.event_manager.broadcast("saving_throw", ctx)
        assert ctx["advantage"] is True

        ctx2 = {"target": owner, "ability": "Wis", "advantage": False, "disadvantage": False}
        owner.event_manager.broadcast("saving_throw", ctx2)
        assert ctx2["advantage"] is False   # wrong ability — no bonus


class TestDamageDealtTriggerReactionEconomy:
    def _defn(self):
        return {
            "name": "Second Wind Rider",
            "trigger": "damage_dealt",
            "conditions": [{"type": "target_is_owner"}],
            "effects": [{"type": "heal", "amount": 5}],
        }

    def test_heals_self_and_spends_a_reaction(self):
        owner = make_creature("Hero", hp=20)
        owner.take_damage(15)   # down to 5 hp so heal has room
        owner._add_feature_by_name("Second Wind Rider", homebrew_def=self._defn())

        assert owner.actions.reactions == 1
        owner.event_manager.broadcast("damage_dealt", {"attacker": None, "target": owner})
        assert owner.hp == 10
        assert owner.actions.reactions == 0

    def test_noop_when_no_reaction_available(self):
        owner = make_creature("Hero", hp=20)
        owner.take_damage(15)
        owner._add_feature_by_name("Second Wind Rider", homebrew_def=self._defn())
        owner.actions.use_reaction()   # burn the only reaction elsewhere

        owner.event_manager.broadcast("damage_dealt", {"attacker": None, "target": owner})
        assert owner.hp == 5   # no heal — no reaction to spend

    def test_noop_when_owner_unconscious(self):
        """Matches the reaction-guard work: an unconscious creature can't
        spend its reaction on its own homebrew feature either."""
        owner = make_creature("Hero", hp=20)
        owner.take_damage(15)
        owner._add_feature_by_name("Second Wind Rider", homebrew_def=self._defn())
        owner.add_condition("unconscious")

        owner.event_manager.broadcast("damage_dealt", {"attacker": None, "target": owner})
        assert owner.hp == 5


class TestTurnStartedTriggerAndRecharge:
    def test_fires_only_on_owners_own_turn(self):
        owner = make_creature("Hero", hp=20)
        other = make_creature("Other", hp=20)
        owner.take_damage(15)
        defn = {
            "name": "Regeneration",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "heal", "amount": 3}],
        }
        owner._add_feature_by_name("Regeneration", homebrew_def=defn)

        owner.event_manager.broadcast("TurnStarted", {"creature": other})
        assert owner.hp == 5   # not owner's turn — no heal

        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.hp == 8

    def test_max_uses_with_turn_recharge_refills_every_turn(self):
        owner = make_creature("Hero", hp=1, ac=14)
        owner._max_hp = 100
        defn = {
            "name": "Second Wind Regen",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "heal", "amount": 1}],
            "recharge": "turn",
            "max_uses": 1,
        }
        owner._add_feature_by_name("Second Wind Regen", homebrew_def=defn)

        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.hp == 2
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        # A "turn" recharge refills before the effect fires on every turn,
        # so it heals again rather than being stuck at 0 uses forever.
        assert owner.hp == 3

    def test_max_uses_with_encounter_recharge_never_refills(self):
        owner = make_creature("Hero", hp=1)
        owner._max_hp = 100
        defn = {
            "name": "One-Shot Heal",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "heal", "amount": 1}],
            "recharge": "encounter",
            "max_uses": 1,
        }
        owner._add_feature_by_name("One-Shot Heal", homebrew_def=defn)

        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.hp == 2
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.hp == 2   # used up — no refill this encounter

    def test_grant_extra_attack(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Bonus Swing",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "grant_extra_attack"}],
        }
        owner._add_feature_by_name("Bonus Swing", homebrew_def=defn)
        before = owner.actions.remaining_extra_attacks
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.actions.remaining_extra_attacks == before + 1

    def test_modify_ac(self):
        owner = make_creature("Hero", ac=14)
        base_ac = owner.ac
        defn = {
            "name": "Defensive Stance",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "modify_ac", "delta": 2}],
        }
        owner._add_feature_by_name("Defensive Stance", homebrew_def=defn)
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner.ac == base_ac + 2


class TestConditionAndResistanceEffects:
    def test_add_condition_to_target_on_hit(self):
        owner = make_creature("Hero")
        target = make_creature("Foe")
        defn = {
            "name": "Chilling Touch",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}],
            "effects": [{"type": "add_condition", "condition": "slowed", "target": "target"}],
        }
        owner._add_feature_by_name("Chilling Touch", homebrew_def=defn)
        owner.event_manager.broadcast("hit", {"attacker": owner, "target": target, "attack": fake_attack()})
        assert target.has_condition("slowed")

    def test_add_resistance_to_self_on_turn_started(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Stoneskin",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "add_resistance", "damage_type": "fire"}],
        }
        owner._add_feature_by_name("Stoneskin", homebrew_def=defn)
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert "fire" in owner.resistances

    def test_add_temp_hp_on_turn_started(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Ward",
            "trigger": "TurnStarted",
            "conditions": [],
            "effects": [{"type": "add_temp_hp", "amount": 5}],
        }
        owner._add_feature_by_name("Ward", homebrew_def=defn)
        owner.event_manager.broadcast("TurnStarted", {"creature": owner})
        assert owner._temp_hp == 5


# ---------------------------------------------------------------------------
# Creature._add_feature_by_name wiring
# ---------------------------------------------------------------------------

class TestAddFeatureByNameWiring:
    def test_attaches_a_homebrew_feature_instance(self):
        owner = make_creature("Hero")
        defn = {
            "name": "Frost Strike",
            "trigger": "hit",
            "conditions": [{"type": "attacker_is_owner"}],
            "effects": [{"type": "add_damage_dice", "count": 1, "die": 6}],
        }
        owner._add_feature_by_name("Frost Strike", homebrew_def=defn)
        assert len(owner.features) == 1
        assert isinstance(owner.features[0], HomebrewFeature)

    def test_rejects_invalid_definition_without_raising(self):
        owner = make_creature("Hero")
        bad_defn = {"name": "Broken", "trigger": "not_a_real_trigger"}
        owner._add_feature_by_name("Broken", homebrew_def=bad_defn)
        assert owner.features == []   # rejected — nothing attached

    def test_plain_registry_lookup_still_works_without_homebrew_def(self):
        owner = make_creature("Hero")
        owner._add_feature_by_name("Second Wind")   # a real, registered feature
        assert len(owner.features) == 1
        assert not isinstance(owner.features[0], HomebrewFeature)
