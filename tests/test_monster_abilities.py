"""
Monster abilities and the engine fixes they depend on.

Background, September 2026: monster attacks resolved at +0 to hit for 1d6
bludgeoning whatever the stat block said; opportunity attacks passed no
weapon at all; nothing set creature.pos, so every area effect found no
targets; paralyzed creatures kept acting; prone never ended. These tests pin
the fixes, then each family of monster ability built on top of them.
"""
import io
import contextlib
import random
from types import SimpleNamespace

import pytest

import importlib, pkgutil, data.features
for _m in pkgutil.iter_modules(data.features.__path__):
    if _m.name != "base":
        importlib.import_module(f"data.features.{_m.name}")

from core.events import EventBus
from core.ml_strategy import CombatEnv
from core.monster_stats import template_dice
from core.saving_throw import SavingThrow, DamageOnSave
from core.tactical_ai import WeaponProfile
from data.features.combat_spells import _creatures_in_cone
from data.monsters.monsters import MONSTER_REGISTRY
from utils.creatureFactory import CreatureFactory
from utils.encounter_builder import CR_TO_XP


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def _hero(name="Hero"):
    return {
        "name": name,
        "classes": [["Fighter", 5]],
        "subclasses": {"Fighter": "Champion"},
        "stats": {"Str": 16, "Dex": 14, "Con": 14, "Int": 8, "Wis": 12, "Cha": 10},
        "items": ["Longsword", "Chain Mail"],
        "equipped": ["Longsword", "Chain Mail"],
    }


def _combat(monsters, positions=None, players=None, width=16, height=12):
    scen = {"name": "test", "max_rounds": 10, "map": {"width": width, "height": height},
            "players": players or [_hero()], "monsters": monsters}
    if positions:
        scen["positions"] = positions
    env = CombatEnv(scen, trained_team="red", silent=True)
    with _quiet():
        env.reset()
    return env.cm


def _find(cm, prefix):
    return next(c for _, c in cm.initiative.initiative_order if c.name.startswith(prefix))


def _make(key):
    with _quiet():
        return CreatureFactory().create(MONSTER_REGISTRY[key], EventBus())


def _feature(creature, name):
    """Find a feature by display name. Instances are named after their
    class ("PackTactics"); the display name lives on the class."""
    return next(f for f in creature.features
                if f.name == name or getattr(type(f), "name", None) == name)


@pytest.fixture
def d20(monkeypatch):
    """Force every die to roll a given value (capped at the die's size)."""
    def force(value):
        monkeypatch.setattr(random, "randint", lambda a, b: max(a, min(b, value)))
    return force


# ── the stat block reaches the dice ──────────────────────────────────────────

def test_multi_die_templates_parse():
    assert template_dice({"damage_dice": "2d10"}) == (2, 10)
    assert template_dice({"damage_die": 8}) == (1, 8)      # legacy one-die form


def test_monster_attack_rolls_its_stat_block():
    cm = _combat([{"type": "HILL_GIANT", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    giant, hero = _find(cm, "Hill Giant"), _find(cm, "Hero")
    club = next(p for p in cm.ai._get_weapon_profiles(giant) if p.name == "Greatclub")
    seen = []
    cm.event.subscribe("attack", lambda d: seen.append(d["attack"])
                       if d.get("attacker") is giant else None)
    with _quiet():
        cm._execute_attack(giant, hero, club)
    a = seen[0]
    assert (a.to_hit_mod, a.base_dice, a.damage_mod, a.damage_type) == \
        (8, (3, 8), 5, "bludgeoning")


def test_opportunity_attack_uses_the_best_melee_weapon():
    cm = _combat([{"type": "HILL_GIANT", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    giant, hero = _find(cm, "Hill Giant"), _find(cm, "Hero")
    seen = []
    cm.event.subscribe("attack", lambda d: seen.append(d["attack"])
                       if d.get("attacker") is giant else None)
    with _quiet():
        cm._execute_attack(giant, hero, None)     # how an opportunity attack arrives
    assert seen[0].to_hit_mod == 8 and seen[0].base_dice == (3, 8)


# ── damage types and conditions ──────────────────────────────────────────────

def test_immunity_vulnerability_and_resistance():
    skeleton = _make("SKELETON")
    assert skeleton.take_damage(10, "poison") == 0
    assert skeleton.take_damage(3, "bludgeoning") == 6
    assert _make("GHAST").take_damage(10, "necrotic") == 5


def test_resistance_to_nonmagical_weapons():
    wight = _make("WIGHT")
    assert wight.take_damage(10, "slashing") == 5
    assert wight.take_damage(10, "slashing", magical=True) == 10
    lich = _make("LICH")
    assert lich.take_damage(10, "piercing") == 0
    assert lich.take_damage(10, "piercing", magical=True) == 10


def test_condition_immunity():
    zombie = _make("ZOMBIE")
    assert zombie.add_condition("poisoned") is False
    assert not zombie.has_condition("poisoned")


def test_paralyzed_creature_loses_its_turn():
    cm = _combat([{"type": "GOBLIN", "count": 1}],
                 positions={"Hero": [3, 3], "monsters": [[8, 3]]})
    goblin = _find(cm, "Goblin")
    goblin.add_condition("paralyzed")
    decision = cm.ai.plan_turn(goblin, cm.battle_map, memory=cm.memories.get(goblin.team))
    assert decision.skip


def test_melee_hit_on_a_paralyzed_target_is_a_crit(d20):
    cm = _combat([{"type": "OGRE", "count": 1, "weapon_role": "melee"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    ogre, hero = _find(cm, "Ogre"), _find(cm, "Hero")
    hero.add_condition("paralyzed")
    club = next(p for p in cm.ai._get_weapon_profiles(ogre) if p.name == "Greatclub")
    seen = []
    cm.event.subscribe("attack_resolved", lambda d: seen.append(d["attack"])
                       if d.get("attacker") is ogre else None)
    d20(15)                                     # a hit, but not a natural 20
    with _quiet():
        cm._execute_attack(ogre, hero, club)
    assert seen[0].critical


def test_paralyzed_creature_fails_dex_saves(d20):
    ogre = _make("OGRE")
    ogre.add_condition("paralyzed")
    d20(20)
    with _quiet():
        res = SavingThrow.roll(caster=ogre, target=ogre, ability="Dex", dc=5,
                               on_save=DamageOnSave.NONE)
    assert not res.success


def test_prone_creature_stands_up_at_half_speed():
    goblin = _make("GOBLIN")
    goblin.add_condition("prone")
    goblin.start_turn()
    assert not goblin.has_condition("prone")
    assert goblin.speed == 15
    goblin.start_turn()
    assert goblin.speed == 30


def test_creature_position_tracks_the_map():
    cm = _combat([{"type": "GOBLIN", "count": 1}],
                 positions={"Hero": [3, 3], "monsters": [[8, 3]]})
    hero = _find(cm, "Hero")
    assert hero.pos == (3, 3)
    cm.battle_map.move_creature_immediate(hero, 4, 3)
    assert hero.pos == (4, 3)


# ── on-hit riders ────────────────────────────────────────────────────────────

def _rider(monster, attack_name):
    return next(t for t in monster._attack_templates if t["name"] == attack_name)["on_hit"]


def test_ghoul_claws_paralyze_on_a_failed_save(d20):
    cm = _combat([{"type": "GHOUL", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    ghoul, hero = _find(cm, "Ghoul"), _find(cm, "Hero")
    d20(1)
    with _quiet():
        _feature(ghoul, "Monster Riders").apply(_rider(ghoul, "Claws"), hero)
    assert hero.has_condition("paralyzed")


def test_paralysis_ends_on_a_successful_repeat_save(d20):
    cm = _combat([{"type": "GHOUL", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    ghoul, hero = _find(cm, "Ghoul"), _find(cm, "Hero")
    riders = _feature(ghoul, "Monster Riders")
    d20(1)
    with _quiet():
        riders.apply(_rider(ghoul, "Claws"), hero)
    d20(20)
    with _quiet():
        riders.on_turn_ended({"creature": hero})
    assert not hero.has_condition("paralyzed")


def test_ghoul_paralysis_spares_undead(d20):
    cm = _combat([{"type": "GHOUL", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    ghoul = _find(cm, "Ghoul")
    claws = next(t for t in ghoul._attack_templates if t["name"] == "Claws")
    skeleton = _make("SKELETON")
    fake = SimpleNamespace(_template=claws, result={"damage": 3}, critical=False)
    d20(1)
    with _quiet():
        _feature(ghoul, "Monster Riders").on_damage_dealt(
            {"attacker": ghoul, "target": skeleton, "attack": fake})
    assert not skeleton.has_condition("paralyzed")


def test_life_drain_reduces_maximum_hp(d20):
    cm = _combat([{"type": "WIGHT", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    wight, hero = _find(cm, "Wight"), _find(cm, "Hero")
    before = hero.max_hp
    fake = SimpleNamespace(result={"damage": 6}, critical=False)
    d20(1)
    with _quiet():
        _feature(wight, "Monster Riders").apply(_rider(wight, "Life Drain"), hero, fake)
    assert hero.max_hp == before - 6


def test_wolf_bite_knocks_prone(d20):
    cm = _combat([{"type": "WOLF", "count": 1}],
                 positions={"Hero": [3, 3], "monsters": [[4, 3]]})
    wolf, hero = _find(cm, "Wolf"), _find(cm, "Hero")
    d20(1)
    with _quiet():
        _feature(wolf, "Monster Riders").apply(_rider(wolf, "Bite"), hero)
    assert hero.has_condition("prone")


def test_extra_rider_damage_respects_immunity():
    dragon = _make("YOUNG_GREEN_DRAGON")
    dragon._attack_templates = MONSTER_REGISTRY["YOUNG_GREEN_DRAGON"]["attacks"]
    riders = _feature(dragon, "Monster Riders")
    bite = _rider(dragon, "Bite")
    skeleton = _make("SKELETON")                   # immune to poison
    with _quiet():
        riders.apply(bite, skeleton)
    assert skeleton.hp == skeleton.max_hp


# ── traits ───────────────────────────────────────────────────────────────────

def test_regeneration_heals_and_fire_stops_it():
    troll = _make("TROLL")
    regen = _feature(troll, "Regeneration")
    with _quiet():
        troll.take_damage(30, "slashing")
        regen.on_turn_started({"creature": troll})
    assert troll.hp == 64
    with _quiet():
        troll.take_damage(5, "fire")
        regen.on_turn_started({"creature": troll})
    assert troll.hp == 59


def test_pack_tactics_needs_an_adjacent_ally():
    cm = _combat([{"type": "WOLF", "count": 2}],
                 positions={"Hero": [5, 5], "monsters": [[6, 5], [12, 5]]})
    wolves = [c for _, c in cm.initiative.initiative_order if c.name.startswith("Wolf")]
    hero = _find(cm, "Hero")
    near = next(w for w in wolves if w.pos == (6, 5))
    far  = next(w for w in wolves if w is not near)
    tactics = _feature(near, "Pack Tactics")
    attack = SimpleNamespace(advantage=False)
    tactics.on_attack({"attacker": near, "target": hero, "attack": attack})
    assert attack.advantage is False
    cm.battle_map.move_creature_immediate(far, 5, 6)
    tactics.on_attack({"attacker": near, "target": hero, "attack": attack})
    assert attack.advantage is True


def test_undead_fortitude_keeps_a_zombie_up(d20):
    zombie = _make("ZOMBIE")
    with _quiet():
        zombie.take_damage(17, "slashing")        # 22 -> 5
        d20(20)
        zombie.take_damage(6, "slashing")         # Con save vs DC 11
    assert zombie.is_alive() and zombie.hp == 1


def test_undead_fortitude_fails_against_radiant(d20):
    zombie = _make("ZOMBIE")
    d20(20)
    with _quiet():
        zombie.take_damage(17, "slashing")
        zombie.take_damage(6, "radiant")
    assert not zombie.is_alive()


def test_martial_advantage_once_per_turn():
    cm = _combat([{"type": "HOBGOBLIN", "count": 2, "weapon_role": "melee"}],
                 positions={"Hero": [5, 5], "monsters": [[6, 5], [5, 6]]})
    hob, hero = _find(cm, "Hobgoblin"), _find(cm, "Hero")
    ma = _feature(hob, "Martial Advantage")
    attack = SimpleNamespace(extra_dice=[])
    with _quiet():
        ma.on_hit({"attacker": hob, "target": hero, "attack": attack})
        ma.on_hit({"attacker": hob, "target": hero, "attack": attack})
    assert attack.extra_dice == [(2, 6)]


def test_nimble_escape_avoids_the_opportunity_attack():
    cm = _combat([{"type": "GOBLIN", "count": 1}],
                 positions={"Hero": [5, 5], "monsters": [[6, 5]]})
    goblin = _find(cm, "Goblin")
    goblin.start_turn()
    oas = []
    cm.event.subscribe("opportunity_attack", lambda d: oas.append(d))
    with _quiet():
        cm._try_move(goblin, 7, 5, 30, silent=True)
    assert not oas
    assert goblin.actions.bonus_actions == 0


# ── recharge actions ─────────────────────────────────────────────────────────

def test_cone_catches_what_is_in_front_not_behind():
    front  = SimpleNamespace(pos=(3, 0))
    behind = SimpleNamespace(pos=(-2, 0))
    wide   = SimpleNamespace(pos=(2, 3))
    edge   = SimpleNamespace(pos=(4, 2))
    caught = _creatures_in_cone([front, behind, wide, edge], (0, 0), (1.0, 0.0), 6)
    assert front in caught and edge in caught
    assert behind not in caught and wide not in caught


def test_breath_recharges_on_a_five_or_six(d20):
    dragon = _make("YOUNG_GREEN_DRAGON")
    breath = _feature(dragon, "Poison Breath")
    breath.available = False
    d20(4)
    with _quiet():
        breath.on_turn_started({"creature": dragon})
    assert not breath.available
    d20(5)
    with _quiet():
        breath.on_turn_started({"creature": dragon})
    assert breath.available


def test_breath_fires_on_a_cluster_and_replaces_the_attacks():
    party = [_hero("Ana"), _hero("Bo"), _hero("Cy")]
    cm = _combat([{"type": "YOUNG_GREEN_DRAGON", "count": 1, "weapon_role": "all"}],
                 positions={"Ana": [6, 4], "Bo": [6, 5], "Cy": [6, 6], "monsters": [[3, 5]]},
                 players=party)
    dragon = _find(cm, "Young Green Dragon")
    used, swings = [], []
    cm.event.subscribe("monster_action", lambda d: used.append(d))
    cm.event.subscribe("attack", lambda d: swings.append(d)
                       if d.get("attacker") is dragon else None)
    with _quiet():
        cm._run_turn(dragon)
    assert used and used[0]["action"] == "Poison Breath"
    assert len(used[0]["targets"]) >= 2
    assert not swings, "the breath should have used the action the attacks need"


def test_breath_is_held_when_attacks_are_worth_more():
    cm = _combat([{"type": "YOUNG_GREEN_DRAGON", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [5, 5], "monsters": [[4, 5]]})
    dragon, hero = _find(cm, "Young Green Dragon"), _find(cm, "Hero")
    dragon.start_turn()
    breath = _feature(dragon, "Poison Breath")
    huge = WeaponProfile("Huge", False, 5, 5, attack_bonus=30, damage_die="40d10")
    with _quiet():
        breath.on_action_phase({"creature": dragon,
                                "decision": SimpleNamespace(weapon=huge, target=hero)})
    assert breath.available and dragon.actions.actions == 1


# ── spellcasting and legendary ───────────────────────────────────────────────

def test_mage_casts_with_its_stat_block():
    from core.attack import WeaponAttack
    mage = _make("MAGE")
    assert mage.spell_slots.spell_dc == 14
    assert mage.spell_slots.has_slot(5)
    fire_bolt = next(i for i in mage.equipped_items if i.name == "Fire Bolt")
    assert fire_bolt.damage_die == "2d10"                  # caster level 9
    assert WeaponAttack(mage, mage, "1d6", item=fire_bolt).to_hit_mod == 6


def test_legendary_resistance_turns_a_failed_save(d20):
    lich = _make("LICH")
    lr = _feature(lich, "Legendary Resistance")
    d20(1)
    with _quiet():
        res = SavingThrow.roll(caster=lich, target=lich, ability="Wis", dc=25,
                               on_save=DamageOnSave.NONE, condition_on_fail="stunned")
    assert res.success
    assert not lich.has_condition("stunned")
    assert lr.uses == 2


def test_legendary_action_tail_attack_at_the_end_of_an_enemy_turn():
    cm = _combat([{"type": "ADULT_RED_DRAGON", "count": 1, "weapon_role": "all"}],
                 positions={"Hero": [5, 5], "monsters": [[8, 5]]}, width=20)
    dragon, hero = _find(cm, "Adult Red Dragon"), _find(cm, "Hero")
    la = _feature(dragon, "Legendary Actions")
    swings = []
    cm.event.subscribe("attack", lambda d: swings.append(getattr(d["attack"], "_weapon_name_hint", None))
                       if d.get("attacker") is dragon else None)
    with _quiet():
        la.on_turn_ended({"creature": hero})
    assert swings == ["Tail"]
    assert la.points == 2


# ── the roster ───────────────────────────────────────────────────────────────

ROSTER = [k for k in MONSTER_REGISTRY if not k.startswith("TRAINING_DUMMY")]


def test_every_attack_template_is_complete():
    for key in ROSTER:
        for atk in MONSTER_REGISTRY[key]["attacks"]:
            assert atk.get("damage_type"), f"{key} {atk['name']} has no damage type"
            n, sides = template_dice(atk)
            assert n >= 1 and sides >= 1


def test_every_monster_has_an_xp_value():
    for key in ROSTER:
        assert MONSTER_REGISTRY[key]["cr"] in CR_TO_XP, key


@pytest.mark.parametrize("key", ROSTER)
def test_every_monster_fights_without_error(key):
    scen = {"name": key, "max_rounds": 3, "map": {"width": 16, "height": 12},
            "players": [_hero()], "monsters": [{"type": key, "count": 1, "weapon_role": "all"}]}
    env = CombatEnv(scen, trained_team="red", silent=True)
    with _quiet():
        env.run_episode(None)
