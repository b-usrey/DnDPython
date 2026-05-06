"""
utils/combat_logger.py

Subscribes to the EventBus and writes a structured JSONL log
(one JSON object per line) covering every turn, move, attack,
bonus action, and downed event in a combat.

Usage
-----
    logger = CombatLogger(event_bus, initiative, "logs/combat.jsonl")
    cm.run()
    logger.close()

Schema — one record per line
-----------------------------
    turn_start   round, creature, team, hp, max_hp, conditions
    move         round, creature, team, from, to, ft
    attack       round, creature, team, target, weapon, roll, total,
                 target_ac, hit, critical, damage, trigger
                 trigger: "action" | "extra_attack" | "bonus_action"
                          | "opportunity_attack"
    bonus_action round, creature, team, ability, target (non-attack BAs)
    downed       round, creature, team
    combat_end   round, winner_team, survivors
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.events import EventBus


class CombatLogger:
    def __init__(self, event_bus: "EventBus", initiative, output_path: str):
        self._initiative  = initiative
        self._path        = output_path
        self._file        = open(output_path, "w", encoding="utf-8")
        self._pending_oa  = False   # flag: next attack_resolved is an OA

        event_bus.subscribe("TurnStarted",        self._on_turn_started)
        event_bus.subscribe("attack_resolved",     self._on_attack_resolved)
        event_bus.subscribe("opportunity_attack",  self._on_opportunity_attack)
        event_bus.subscribe("move",                self._on_move)
        event_bus.subscribe("bonus_action",        self._on_bonus_action)
        event_bus.subscribe("creature_downed",     self._on_downed)
        event_bus.subscribe("CombatEnded",         self._on_combat_ended)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _round(self) -> int:
        return getattr(self._initiative, "round", 1)

    def _write(self, data: dict) -> None:
        self._file.write(json.dumps(data) + "\n")
        self._file.flush()

    def _creature_fields(self, creature) -> dict:
        return {"creature": creature.name, "team": creature.team}

    def _weapon_name(self, attack) -> str | None:
        if attack.item is not None:
            return attack.item.name
        hint = getattr(attack, "_weapon_name_hint", None)
        if hint:
            return hint
        templates = getattr(attack.attacker, "_attack_templates", None)
        if templates:
            return templates[0].get("name", "natural weapon")
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_turn_started(self, data: dict) -> None:
        creature = data.get("creature")
        if not creature:
            return
        self._write({
            "type":       "turn_start",
            "round":      self._round,
            **self._creature_fields(creature),
            "hp":         creature.hp,
            "max_hp":     creature.max_hp,
            "conditions": sorted(creature.conditions),
        })

    def _on_opportunity_attack(self, data: dict) -> None:
        self._pending_oa = True

    def _on_attack_resolved(self, data: dict) -> None:
        attacker = data.get("attacker")
        target   = data.get("target")
        attack   = data.get("attack")
        if not attacker or not target or not attack:
            return

        if self._pending_oa:
            trigger = "opportunity_attack"
            self._pending_oa = False
        elif "bonus_action" in attack.tags:
            trigger = "bonus_action"
        elif "extra_attack" in attack.tags:
            trigger = "extra_attack"
        else:
            trigger = "action"

        self._write({
            "type":      "attack",
            "round":     self._round,
            **self._creature_fields(attacker),
            "target":    target.name,
            "weapon":    self._weapon_name(attack),
            "roll":      attack.result.get("hit_roll"),
            "total":     attack.result.get("attack_total"),
            "target_ac": target.ac,
            "hit":       attack.result.get("hit", False),
            "critical":  attack.critical,
            "damage":    attack.result.get("damage", 0) if attack.result.get("hit") else 0,
            "trigger":   trigger,
            "tags":      sorted(attack.tags),
        })

    def _on_move(self, data: dict) -> None:
        creature = data.get("creature")
        from_pos = data.get("from")
        to_pos   = data.get("to")
        ft       = data.get("ft", 0)
        if not creature:
            return
        self._write({
            "type":     "move",
            "round":    self._round,
            **self._creature_fields(creature),
            "from":     list(from_pos) if from_pos else None,
            "to":       list(to_pos)   if to_pos   else None,
            "ft":       ft,
        })

    def _on_bonus_action(self, data: dict) -> None:
        creature = data.get("creature")
        self._write({
            "type":    "bonus_action",
            "round":   self._round,
            **self._creature_fields(creature),
            "ability": data.get("ability", "unknown"),
            "target":  data.get("target_name"),
            "detail":  data.get("detail"),
        })

    def _on_downed(self, data: dict) -> None:
        creature = data.get("creature")
        if not creature:
            return
        self._write({
            "type":  "downed",
            "round": self._round,
            **self._creature_fields(creature),
            "hp_final": creature.hp,
        })

    def _on_combat_ended(self, data: dict) -> None:
        survivors = data.get("survivors", [])
        winner    = survivors[0].team if survivors else None
        self._write({
            "type":        "combat_end",
            "round":       self._round,
            "winner_team": winner,
            "survivors":   [c.name for c in survivors],
        })

    # ------------------------------------------------------------------

    def close(self) -> None:
        self._file.close()
