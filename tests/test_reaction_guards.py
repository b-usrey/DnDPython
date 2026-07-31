"""
Tests for the "can't spend a reaction while unconscious/dying" guard
(data/features/base.py Feature._owner_can_react), added to every
reaction-style feature that hooks a "damage_dealt"/"attack"/"hit" event
and spends self.owner.actions.use_reaction() on the owner's behalf.

Without this guard, a downed creature at 0 HP rolling death saves
(Creature.DEATH_SAVES=True, see core/creature.py _start_dying) could still
fire these reactions when hit by follow-up attacks, since is_alive() alone
stays True while dying — only the "unconscious" condition distinguishes it.

Covers: HellishRebuke, ShieldSpell (spell_features.py), UncannyDodge
(rogue_features.py), Retaliation (barbarian_features.py), Sentinel
(feat_features.py), EntropicWard (warlock_features.py), SoulOfVengeance
(paladin_features.py), ShadowyDodge (ranger_features.py).
"""
import random

from core.creature import Creature
from core.events import EventBus
from core.item import Item

from data.features.spell_features import HellishRebuke, ShieldSpell
from data.features.rogue_features import UncannyDodge
from data.features.barbarian_features import Retaliation
from data.features.feat_features import Sentinel
from data.features.warlock_features import EntropicWard
from data.features.paladin_features import SoulOfVengeance, VowOfEnmity
from data.features.ranger_features import ShadowyDodge


def make_stats():
    return {"Str": 14, "Dex": 14, "Con": 14, "Int": 10, "Wis": 10, "Cha": 10}


def make_creature(name, hp=20, ac=14, bus=None):
    return Creature(name, hp, ac, make_stats(), bus or EventBus())


def make_weapon(name="Sword", damage_die="1d6", attack_type="melee"):
    return Item(name, "weapon", damage_die=damage_die, ability="Str",
                attack_bonus=0, damage_bonus=0, attack_type=attack_type)


class FakeAttack:
    """Minimal stand-in for WeaponAttack exposing only what these
    reaction handlers read or write."""
    def __init__(self, hit=True, damage=10, attack_total=15, critical=False):
        self.result = {"hit": hit, "damage": damage, "attack_total": attack_total}
        self.critical = critical
        self.disadvantage = False
        self.advantage = False


# ---------------------------------------------------------------------------
# HellishRebuke — spell_features.py (already checked is_alive(), not unconscious)
# ---------------------------------------------------------------------------

class TestHellishRebukeGuard:
    def test_no_reaction_while_unconscious(self):
        bus = EventBus()
        owner = make_creature("Hero", bus=bus)
        attacker = make_creature("Goblin", hp=10, bus=bus)
        feature = HellishRebuke()
        feature.attach(owner, bus)
        owner.add_condition("unconscious")

        feature.on_damage_dealt(
            {"target": owner, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 1
        assert attacker.hp == 10

    def test_reacts_normally_when_conscious(self, monkeypatch):
        bus = EventBus()
        owner = make_creature("Hero", bus=bus)
        attacker = make_creature("Goblin", hp=10, bus=bus)
        feature = HellishRebuke()
        feature.attach(owner, bus)
        monkeypatch.setattr(random, "randint", lambda a, b: 10)

        feature.on_damage_dealt(
            {"target": owner, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 0
        assert attacker.hp < 10


# ---------------------------------------------------------------------------
# ShieldSpell — spell_features.py (had no is_alive/unconscious check at all)
# ---------------------------------------------------------------------------

class TestShieldSpellGuard:
    def test_no_reaction_while_unconscious(self):
        bus = EventBus()
        owner = make_creature("Wizard", ac=14, bus=bus)
        owner.add_condition("unconscious")
        feature = ShieldSpell()
        feature.attach(owner, bus)
        attack = FakeAttack(attack_total=16)

        feature.on_hit({"target": owner, "attack": attack})

        assert owner.ac == 14
        assert owner.actions.reactions == 1
        assert attack.result["hit"] is True

    def test_reacts_normally_when_conscious(self):
        bus = EventBus()
        owner = make_creature("Wizard", ac=14, bus=bus)
        feature = ShieldSpell()
        feature.attach(owner, bus)
        attack = FakeAttack(attack_total=16)

        feature.on_hit({"target": owner, "attack": attack})

        assert owner.ac == 19
        assert owner.actions.reactions == 0
        assert attack.result["hit"] is False   # +5 AC turns the 16 into a miss


# ---------------------------------------------------------------------------
# UncannyDodge — rogue_features.py (already checked is_alive(), not unconscious)
# ---------------------------------------------------------------------------

class TestUncannyDodgeGuard:
    def test_no_heal_while_unconscious(self):
        bus = EventBus()
        owner = make_creature("Rogue", hp=20, bus=bus)
        owner.take_damage(10)
        feature = UncannyDodge()
        feature.attach(owner, bus)
        owner.add_condition("unconscious")

        feature.on_damage_dealt({"target": owner, "attack": FakeAttack(damage=10)})

        assert owner.hp == 10
        assert owner.actions.reactions == 1

    def test_halves_damage_when_conscious(self):
        bus = EventBus()
        owner = make_creature("Rogue", hp=20, bus=bus)
        owner.take_damage(10)
        feature = UncannyDodge()
        feature.attach(owner, bus)

        feature.on_damage_dealt({"target": owner, "attack": FakeAttack(damage=10)})

        assert owner.hp == 15
        assert owner.actions.reactions == 0


# ---------------------------------------------------------------------------
# Retaliation — barbarian_features.py (already checked is_alive(), not unconscious)
# ---------------------------------------------------------------------------

class TestRetaliationGuard:
    def _setup(self, bus):
        owner = make_creature("Barbarian", hp=20, bus=bus)
        owner.pos = (0, 0)
        owner.equipped_items.append(make_weapon())
        attacker = make_creature("Goblin", hp=10, bus=bus)
        attacker.pos = (1, 0)
        feature = Retaliation()
        feature.attach(owner, bus)
        return owner, attacker, feature

    def test_no_counter_while_unconscious(self, monkeypatch):
        bus = EventBus()
        owner, attacker, feature = self._setup(bus)
        owner.add_condition("unconscious")
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_damage_dealt(
            {"target": owner, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 1
        assert attacker.hp == 10

    def test_counterattacks_when_conscious(self, monkeypatch):
        bus = EventBus()
        owner, attacker, feature = self._setup(bus)
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_damage_dealt(
            {"target": owner, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 0
        assert attacker.hp < 10


# ---------------------------------------------------------------------------
# Sentinel — feat_features.py (already checked is_alive(), not unconscious)
# ---------------------------------------------------------------------------

class TestSentinelGuard:
    def _setup(self, bus):
        owner = make_creature("Fighter", hp=20, bus=bus)
        owner.pos = (0, 0)
        owner.equipped_items.append(make_weapon())
        ally = make_creature("Ally", hp=20, bus=bus)
        attacker = make_creature("Goblin", hp=10, bus=bus)
        attacker.pos = (1, 0)
        feature = Sentinel()
        feature.attach(owner, bus)
        return owner, ally, attacker, feature

    def test_no_counter_while_unconscious(self, monkeypatch):
        bus = EventBus()
        owner, ally, attacker, feature = self._setup(bus)
        owner.add_condition("unconscious")
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_damage_dealt(
            {"target": ally, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 1
        assert attacker.hp == 10

    def test_protects_ally_when_conscious(self, monkeypatch):
        bus = EventBus()
        owner, ally, attacker, feature = self._setup(bus)
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_damage_dealt(
            {"target": ally, "attacker": attacker, "attack": FakeAttack()})

        assert owner.actions.reactions == 0
        assert attacker.hp < 10


# ---------------------------------------------------------------------------
# EntropicWard — warlock_features.py (had no is_alive/unconscious check at all)
# ---------------------------------------------------------------------------

class TestEntropicWardGuard:
    def test_no_reaction_while_unconscious(self):
        bus = EventBus()
        owner = make_creature("Warlock", bus=bus)
        owner.add_condition("unconscious")
        feature = EntropicWard()
        feature.attach(owner, bus)
        attack = FakeAttack()

        feature.on_attack({"target": owner, "attack": attack})

        assert attack.disadvantage is False
        assert owner.actions.reactions == 1

    def test_no_reaction_when_dead(self):
        bus = EventBus()
        owner = make_creature("Warlock", hp=5, bus=bus)
        owner.take_damage(5)   # ordinary creature dies outright at 0 HP
        assert not owner.is_alive()
        feature = EntropicWard()
        feature.attach(owner, bus)
        attack = FakeAttack()

        feature.on_attack({"target": owner, "attack": attack})

        assert attack.disadvantage is False
        assert owner.actions.reactions == 1

    def test_imposes_disadvantage_when_conscious(self):
        bus = EventBus()
        owner = make_creature("Warlock", bus=bus)
        feature = EntropicWard()
        feature.attach(owner, bus)
        attack = FakeAttack()

        feature.on_attack({"target": owner, "attack": attack})

        assert attack.disadvantage is True
        assert owner.actions.reactions == 0


# ---------------------------------------------------------------------------
# SoulOfVengeance — paladin_features.py (already checked is_alive(), not unconscious)
# ---------------------------------------------------------------------------

class TestSoulOfVengeanceGuard:
    def _setup(self, bus):
        owner = make_creature("Paladin", hp=20, bus=bus)
        owner.equipped_items.append(make_weapon())
        attacker = make_creature("Goblin", hp=10, bus=bus)
        vow = VowOfEnmity()
        vow.owner = owner
        vow._vow_target = attacker
        owner.features.append(vow)
        feature = SoulOfVengeance()
        feature.attach(owner, bus)
        return owner, attacker, feature

    def test_no_counter_while_unconscious(self, monkeypatch):
        bus = EventBus()
        owner, attacker, feature = self._setup(bus)
        owner.add_condition("unconscious")
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_attack({"attacker": attacker})

        assert owner.actions.reactions == 1
        assert attacker.hp == 10

    def test_counterattacks_when_conscious(self, monkeypatch):
        bus = EventBus()
        owner, attacker, feature = self._setup(bus)
        monkeypatch.setattr(random, "randint", lambda a, b: 20)

        feature.on_attack({"attacker": attacker})

        assert owner.actions.reactions == 0
        assert attacker.hp < 10


# ---------------------------------------------------------------------------
# ShadowyDodge — ranger_features.py (had no is_alive/unconscious check at all)
# ---------------------------------------------------------------------------

class TestShadowyDodgeGuard:
    def test_no_reaction_while_unconscious(self):
        bus = EventBus()
        owner = make_creature("Ranger", bus=bus)
        owner.add_condition("unconscious")
        feature = ShadowyDodge()
        feature.attach(owner, bus)
        attack = FakeAttack()

        feature.on_attack({"target": owner, "attack": attack})

        assert attack.disadvantage is False
        assert owner.actions.reactions == 1

    def test_imposes_disadvantage_when_conscious(self):
        bus = EventBus()
        owner = make_creature("Ranger", bus=bus)
        feature = ShadowyDodge()
        feature.attach(owner, bus)
        attack = FakeAttack()

        feature.on_attack({"target": owner, "attack": attack})

        assert attack.disadvantage is True
        assert owner.actions.reactions == 0
