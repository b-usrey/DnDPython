"""
Tests for utils/combat_logger.py:
  - records accumulate in-memory regardless of whether a file path is given
  - output_path=None skips file I/O entirely (for web requests analyzing
    many episodes where writing one file per episode would be wasteful)
  - a real combat produces the expected record types
"""
import io
import contextlib
import json
import os
from types import SimpleNamespace

from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from utils.combat_logger import CombatLogger
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures


SCENARIO = {
    "name": "Combat logger test",
    "max_rounds": 5,
    "map": {"width": 10, "height": 8, "walls": [], "difficult_terrain": []},
    "positions": {"Hero": [1, 3], "monsters": [[6, 3]]},
    "players": [
        {
            "name": "Hero",
            "classes": [["Fighter", 5]],
            "subclasses": {},
            "stats": {"Str": 16, "Dex": 12, "Con": 14, "Int": 10, "Wis": 10, "Cha": 8},
            "choices": [],
            "items": ["Longsword"],
            "equipped": ["Longsword"],
            "features": [],
        },
    ],
    "monsters": [{"type": "GOBLIN", "count": 1, "weapon_role": "melee"}],
}


def run_logged_combat(output_path=None):
    event   = EventBus()
    factory = CreatureFactory()
    loader  = ScenarioLoader(factory, event)
    with contextlib.redirect_stdout(io.StringIO()):
        players, monsters = loader.load(SCENARIO)
        battle_map = build_map(SCENARIO)
        place_creatures(SCENARIO, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        cm = CombatManager(event, initiative, battle_map, mode=CombatMode.AUTO)
        logger = CombatLogger(event, initiative, output_path)
        cm.run()
        logger.close()
    return logger


class TestInMemoryOnly:
    def test_no_path_skips_file_io_but_still_records(self):
        logger = run_logged_combat(output_path=None)
        assert len(logger.records) > 0
        assert logger._file is None

    def test_close_is_a_safe_no_op_without_a_file(self):
        logger = run_logged_combat(output_path=None)
        logger.close()   # already closed once by run_logged_combat -- must not raise

    def test_records_include_turn_start_and_combat_end(self):
        logger = run_logged_combat(output_path=None)
        types = {r["type"] for r in logger.records}
        assert "turn_start" in types
        assert "combat_end" in types


class TestFileWriting:
    def test_writes_jsonl_file_when_path_given(self, tmp_path):
        path = str(tmp_path / "combat.jsonl")
        logger = run_logged_combat(output_path=path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert lines == logger.records


class TestAttackRecordShape:
    def test_attack_records_carry_the_fields_stats_aggregation_needs(self):
        """Character-analyzer stats (hit/crit rate by trigger, power-attack-
        trade audit) are built entirely from these fields -- confirm they're
        actually present rather than assuming the schema docstring is
        accurate."""
        logger = run_logged_combat(output_path=None)
        attacks = [r for r in logger.records if r["type"] == "attack"]
        assert attacks, "expected at least one attack in a 5-round fight"
        for a in attacks:
            assert "hit" in a and isinstance(a["hit"], bool)
            assert "damage" in a
            assert "trigger" in a
            assert "tags" in a and isinstance(a["tags"], list)
            assert "round" in a and "creature" in a and "team" in a


class TestSaveBasedSpellDamage:
    """Save-based spells (Fireball, Thunderwave, PoisonSpray, ...) deal
    damage via SavingThrow.roll(), never through the attack-roll pipeline
    the "attack" record type covers -- without this hook, a caster's
    nova damage would silently be invisible to any stats built from the
    log (e.g. damage-by-round)."""

    def test_logs_save_damage_on_saving_throw_resolved(self):
        event = EventBus()
        initiative = SimpleNamespace(round=3)
        logger = CombatLogger(event, initiative, output_path=None)

        caster = SimpleNamespace(name="Lyra", team="blue")
        target = SimpleNamespace(name="Goblin#1")
        result = SimpleNamespace(
            damage_dealt=14, damage_type="fire", ability="Dex", success=False,
            target=target,
        )
        event.broadcast("saving_throw_resolved", {"caster": caster, "result": result})

        save_records = [r for r in logger.records if r["type"] == "save_damage"]
        assert len(save_records) == 1
        rec = save_records[0]
        assert rec["creature"] == "Lyra"
        assert rec["team"] == "blue"
        assert rec["target"] == "Goblin#1"
        assert rec["damage"] == 14
        assert rec["damage_type"] == "fire"
        assert rec["save_ability"] == "Dex"
        assert rec["save_success"] is False
        assert rec["round"] == 3

    def test_ignores_saves_with_no_damage(self):
        """A successful save with on_save=NONE (or a control-only spell like
        Hold Person) has damage_dealt=0 -- shouldn't pollute the log."""
        event = EventBus()
        initiative = SimpleNamespace(round=1)
        logger = CombatLogger(event, initiative, output_path=None)

        caster = SimpleNamespace(name="Lyra", team="blue")
        result = SimpleNamespace(
            damage_dealt=0, damage_type="", ability="Wis", success=True, target=None,
        )
        event.broadcast("saving_throw_resolved", {"caster": caster, "result": result})

        assert [r for r in logger.records if r["type"] == "save_damage"] == []


class TestResourceSpentLogging:
    def test_logs_resource_spent_event(self):
        event = EventBus()
        initiative = SimpleNamespace(round=4)
        logger = CombatLogger(event, initiative, output_path=None)

        creature = SimpleNamespace(name="Wukong", team="blue")
        event.broadcast("resource_spent", {
            "creature": creature, "resource": "ki", "remaining": 1, "detail": "Flurry of Blows",
        })

        records = [r for r in logger.records if r["type"] == "resource_spent"]
        assert len(records) == 1
        rec = records[0]
        assert rec["creature"] == "Wukong"
        assert rec["team"] == "blue"
        assert rec["resource"] == "ki"
        assert rec["remaining"] == 1
        assert rec["detail"] == "Flurry of Blows"
        assert rec["round"] == 4

    def test_ignores_events_with_no_creature(self):
        event = EventBus()
        initiative = SimpleNamespace(round=1)
        logger = CombatLogger(event, initiative, output_path=None)

        event.broadcast("resource_spent", {"resource": "ki", "remaining": 1})

        assert [r for r in logger.records if r["type"] == "resource_spent"] == []
