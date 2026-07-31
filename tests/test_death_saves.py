"""
Tests for death saving throws (core/creature.py):
  - Ordinary creatures (DEATH_SAVES=False) die outright at 0 HP
  - DEATH_SAVES=True creatures fall unconscious and dying instead
  - roll_death_save(): nat 20 revives, 3 successes stabilises, 3 failures kills
  - Taking damage while dying is an automatic failure (2 on a crit),
    massive damage kills instantly
  - Healing a dying creature wakes it up and clears death save progress
"""
import random

from core.creature import Creature
from core.events import EventBus


def make_stats():
    return {"Str": 12, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 10}


class _MortalCreature(Creature):
    """Ordinary creature — dies outright at 0 HP (DEATH_SAVES=False default)."""
    pass


class _HeroicCreature(Creature):
    """PlayerCharacter-style creature — rolls death saves at 0 HP."""
    DEATH_SAVES = True


def make_mortal(hp=10, ac=14):
    return _MortalCreature("Goblin", hp, ac, make_stats(), EventBus())


def make_hero(hp=10, ac=14):
    return _HeroicCreature("Hero", hp, ac, make_stats(), EventBus())


# ---------------------------------------------------------------------------
# Ordinary creatures die outright
# ---------------------------------------------------------------------------

class TestOrdinaryCreaturesDieOutright:
    def test_dies_at_zero_hp(self):
        c = make_mortal(hp=5)
        c.take_damage(5)
        assert c.hp == 0
        assert not c.is_alive()
        assert c.has_condition("dead")
        assert not c.has_condition("dying")

    def test_broadcasts_creature_downed_without_dying_flag(self):
        c = make_mortal(hp=5)
        seen = []
        c.event_manager.subscribe("creature_downed", lambda data: seen.append(data))
        c.take_damage(5)
        assert len(seen) == 1
        assert seen[0].get("dying") is None


# ---------------------------------------------------------------------------
# Entering the dying state
# ---------------------------------------------------------------------------

class TestEnteringDyingState:
    def test_drops_to_dying_instead_of_dying_outright(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        assert hero.hp == 0
        assert hero.is_alive()   # still "alive" — unconscious, not dead
        assert hero.has_condition("unconscious")
        assert hero.has_condition("dying")

    def test_broadcasts_creature_downed_with_dying_flag(self):
        hero = make_hero(hp=10)
        seen = []
        hero.event_manager.subscribe("creature_downed", lambda data: seen.append(data))
        hero.take_damage(10)
        assert seen[0]["dying"] is True

    def test_overkill_damage_still_only_downs_not_kills(self):
        """A big single hit that drops HP well past 0 still just starts the
        dying state — massive-damage instant death only applies to hits
        taken *while already dying*, not the hit that causes the drop."""
        hero = make_hero(hp=10)
        hero.take_damage(999)
        assert hero.is_alive()
        assert hero.has_condition("dying")


# ---------------------------------------------------------------------------
# roll_death_save()
# ---------------------------------------------------------------------------

class TestRollDeathSave:
    def test_no_op_when_not_dying(self):
        hero = make_hero(hp=10)
        hero.roll_death_save()
        assert hero.death_save_successes == 0
        assert hero.death_save_failures == 0

    def test_natural_20_revives_to_one_hp(self, monkeypatch):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        monkeypatch.setattr(random, "randint", lambda a, b: 20)
        hero.roll_death_save()
        assert hero.hp == 1
        assert hero.is_alive()
        assert not hero.has_condition("dying")
        assert not hero.has_condition("unconscious")

    def test_three_successes_stabilises(self, monkeypatch):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        monkeypatch.setattr(random, "randint", lambda a, b: 15)  # always a success
        hero.roll_death_save()
        hero.roll_death_save()
        assert hero.has_condition("dying")   # still dying after 2 successes
        hero.roll_death_save()
        assert not hero.has_condition("dying")   # stabilised
        assert hero.has_condition("unconscious")  # still unconscious, just stable
        assert hero.is_alive()
        assert hero.death_save_successes == 0
        assert hero.death_save_failures == 0

    def test_three_failures_kills(self, monkeypatch):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        monkeypatch.setattr(random, "randint", lambda a, b: 5)  # always a failure
        hero.roll_death_save()
        hero.roll_death_save()
        assert hero.is_alive()
        hero.roll_death_save()
        assert not hero.is_alive()
        assert hero.has_condition("dead")
        assert not hero.has_condition("dying")

    def test_natural_1_counts_as_two_failures(self, monkeypatch):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)
        hero.roll_death_save()
        assert hero.death_save_failures == 2
        assert hero.is_alive()
        hero.roll_death_save()
        assert not hero.is_alive()   # 4 failures total, well past 3


# ---------------------------------------------------------------------------
# Damage taken while dying
# ---------------------------------------------------------------------------

class TestDamageWhileDying:
    def test_hit_while_dying_is_one_failure(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        hero.take_damage(3)
        assert hero.death_save_failures == 1
        assert hero.is_alive()

    def test_critical_hit_while_dying_is_two_failures(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        hero.take_damage(3, critical=True)
        assert hero.death_save_failures == 2
        assert hero.is_alive()

    def test_massive_damage_kills_instantly(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        hero.take_damage(10)   # >= max_hp in a single hit while dying
        assert not hero.is_alive()
        assert hero.has_condition("dead")

    def test_repeated_hits_accumulate_to_death(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        hero.take_damage(3)
        hero.take_damage(3)
        assert hero.is_alive()
        hero.take_damage(3)
        assert not hero.is_alive()


# ---------------------------------------------------------------------------
# Healing while dying
# ---------------------------------------------------------------------------

class TestHealingWhileDying:
    def test_heal_revives_and_clears_death_saves(self):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        hero.take_damage(3)   # one failure logged
        assert hero.death_save_failures == 1
        hero.heal(5)
        assert hero.hp == 5
        assert hero.is_alive()
        assert not hero.has_condition("dying")
        assert not hero.has_condition("unconscious")
        assert hero.death_save_failures == 0
        assert hero.death_save_successes == 0

    def test_heal_is_noop_on_truly_dead_creature(self, monkeypatch):
        hero = make_hero(hp=10)
        hero.take_damage(10)
        monkeypatch.setattr(random, "randint", lambda a, b: 1)   # nat 1 x2 -> dead in 2 rolls
        hero.roll_death_save()
        hero.roll_death_save()
        assert not hero.is_alive()
        healed = hero.heal(20)
        assert healed == 0
        assert hero.hp == 0
