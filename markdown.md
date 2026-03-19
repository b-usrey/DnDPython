# D&D 5e Encounter Simulation Framework

A turn-based D&D 5e combat simulator written in Python. Supports player characters, monsters, spells, saving throws, conditions, action economy, tactical AI with team memory, and a matplotlib visualiser that exports video replays.

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [Architecture Overview](#architecture-overview)
3. [Class Interactions](#class-interactions)
4. [Event System](#event-system)
5. [Action Economy](#action-economy)
6. [Attack Pipeline](#attack-pipeline)
7. [Saving Throws](#saving-throws)
8. [Feature System](#feature-system)
9. [Tactical AI](#tactical-ai)
10. [Visualiser](#visualiser)
11. [Known Limitations](#known-limitations)
12. [How To: Add a New Character](#how-to-add-a-new-character)
13. [How To: Add a New Class](#how-to-add-a-new-class)
14. [How To: Add a New Subclass](#how-to-add-a-new-subclass)
15. [How To: Add a New Spell / Reaction](#how-to-add-a-new-spell--reaction)
16. [How To: Add a New Item](#how-to-add-a-new-item)
17. [How To: Add a New Monster](#how-to-add-a-new-monster)
18. [Running a Scenario](#running-a-scenario)

---

## Project Structure

```
currentPythonProject/
├── core/
│   ├── actionTracker.py      Action economy (actions, bonus, reaction, surges, extra attacks)
│   ├── attack.py             WeaponAttack — 4-phase attack pipeline
│   ├── battle_map.py         Grid map, movement, OA, range checks
│   ├── combat_manager.py     Encounter loop, player/AI turn execution
│   ├── creature.py           Base creature class (HP, conditions, inventory)
│   ├── events.py             Shared EventBus (pub/sub)
│   ├── InitiativeManager.py  Initiative order and round tracking
│   ├── ml_strategy.py        RL and evolutionary strategy selectors
│   ├── player_character.py   PlayerCharacter — loads class/subclass features from JSON
│   ├── saving_throw.py       SavingThrow.roll(), DamageOnSave, CommonSaves
│   ├── statBlock.py          Ability scores, modifiers, save proficiencies
│   ├── tactical_ai.py        TacticalAI, TacticalDecision, WeaponProfile
│   ├── team_memory.py        TeamMemory — shared intel per team, state vectors
│   └── tile.py               Tile dataclass (normal/difficult/wall/water)
│
├── data/
│   ├── classes/
│   │   ├── fighter.json      Fighter class definition
│   │   └── ranger.json       Ranger class definition (with Gloom Stalker subclass)
│   ├── features/
│   │   ├── base.py           Feature base class + REGISTRY
│   │   ├── feat_features.py  Sharpshooter
│   │   ├── fighter_features.py  ActionSurge, SecondWind
│   │   ├── fighting_styles.py   Archery
│   │   ├── magic_items.py    BracersOfArchery
│   │   ├── ranger_features.py   DreadAmbusher, FavoredFoe, ExtraAttack
│   │   └── spell_features.py    HellishRebuke
│   ├── monsters/
│   │   └── monsters.py       GOBLIN, ORC templates + MONSTER_REGISTRY
│   ├── enchantments.json
│   └── items.json            Weapon and armour definitions
│
├── utils/
│   ├── battle_visualiser.py  Matplotlib visualiser with trails, dead tokens, video export
│   ├── creatureFactory.py    Spawns creatures with unique IDs (Goblin#1, Goblin#2)
│   ├── scenarioLoader.py     Loads scenario JSON into players + monsters
│   └── load_item.py          Item loading helpers
│
├── scenarios/
│   └── brendiir_vs_goblins.json   Example scenario
│
└── main.py                   CLI entrypoint
```

---

## Architecture Overview

```
main.py
  │
  ├── ScenarioLoader          reads JSON → PlayerCharacter + Creature instances
  ├── BattleMap               placed creatures, movement, range, OA
  ├── InitiativeManager       initiative order, round counter
  ├── CombatManager           encounter loop
  │     ├── _run_turn()       per-creature turn (player or AI)
  │     ├── _do_attack_action() main + extra attacks
  │     ├── _try_move()       movement + opportunity attacks
  │     └── SavingThrow       resolves saves inline
  │
  ├── TacticalAI              plan_turn() → TacticalDecision
  │     └── TeamMemory        threat tracking, recommended_target, state vectors
  │
  ├── EventBus                pub/sub wiring all of the above together
  │     └── Features          subscribe to events, modify attacks/saves in place
  │
  └── BattleVisualiser        optional — patches CombatManager._run_turn
```

---

## Class Interactions

### `Creature`
The base class for everything on the battlefield. Holds HP, AC, conditions, inventory, `StatBlock`, and `ActionTracker`. Does **not** store position — `BattleMap` owns positions.

Key methods:
- `take_damage(amount, damage_type)` — applies damage, broadcasts `creature_downed` on death
- `heal(amount)` — restores HP up to max
- `add_condition(str)` / `has_condition(str)` — condition tracking (lowercase strings)
- `start_turn()` — resets `ActionTracker`, clears `"dodging"`
- `_add_feature_by_name(name)` — looks up `Feature.REGISTRY` and attaches

### `PlayerCharacter(Creature)`
Extends `Creature` with class/subclass loading. On init it reads the class JSON, accumulates HP using the hit die formula, wires saving throw proficiencies into `StatBlock`, and calls `_add_feature_by_name` for every feature unlocked at or below the character's level.

### `StatBlock`
Holds the six ability scores, precomputes modifiers, and tracks save proficiencies.

```python
sb = StatBlock({"Str": 10, "Dex": 20, "Con": 14, "Int": 9, "Wis": 16, "Cha": 8})
sb.mods["Dex"]          # +5
sb.save_bonus("Dex")    # +5 + proficiency if proficient
```

### `BattleMap`
Owns a `_positions` dict (`creature → (col, row)`) and a `_grid` of `Tile` objects. Movement is split into two steps to allow opportunity attacks to fire while the mover is still at their origin:

```
move_creature(creature, col, row)  → returns OA candidates, does NOT update position
commit_move(creature, col, row)    → actually updates _positions
```

`_try_move` in `CombatManager` calls them in this order, executing OA attacks in between.

Key methods:
- `distance_between(a, b)` — Chebyshev distance × 5 (feet)
- `check_attack_range(attacker, target, is_ranged, normal_range, long_range)` → `RangeResult`
- `get_threatened_squares(creature)` — all squares within melee reach
- `enemies_of(creature)` — living creatures on opposing teams
- `is_in_melee_range(a, b)` — Chebyshev distance ≤ 1

### `ActionTracker`
Tracks all action economy resources per turn. Reset at the start of each turn by `Creature.start_turn()`.

| Resource | Description |
|---|---|
| `actions` | Standard actions (1/turn) |
| `bonus_actions` | Bonus actions (1/turn) |
| `reactions` | Reactions (1/round) |
| `extra_attacks` | Permanent pool from Extra Attack feature |
| `remaining_extra_attacks` | Charges left this turn (includes temp grants) |
| `max_action_surges` | Action Surge charges (set by `ActionSurge` feature) |
| `remaining_surges` | Surges left this combat |

Key methods:
- `grant_temp_extra_attack()` — one-turn bonus (Dread Ambusher, Haste)
- `use_action_surge()` — grants extra action + resets extra_attack pool

### `EventBus`
Simple pub/sub. Every creature, feature, and the visualiser subscribe to named events. Features attach via `Feature.subscribe(bus)` which registers each handler in `EVENT_MAP`.

### `CreatureFactory`
Spawns monsters from templates with unique names. Uses a per-species counter so `Goblin` becomes `Goblin#1`, `Goblin#2`, etc. This name flows through the combat log, `TeamMemory`, and visualiser token labels automatically.

---

## Event System

Events are broadcast on the shared `EventBus`. Features subscribe to events by name. The `data` dict passed to each handler always contains relevant context objects.

| Event | When | Key data keys |
|---|---|---|
| `"CombatStarted"` | Before round 1 | `round` |
| `"RoundStarted"` | Start of each new round | `round` |
| `"TurnStarted"` | Before each creature's turn | `creature`, `round` |
| `"TurnEnded"` | After each creature's turn | `creature`, `round` |
| `"attack"` | Phase 1 of attack pipeline | `attacker`, `target`, `attack` |
| `"damage"` | Phase 2 — before damage is rolled | `attacker`, `target`, `attack` |
| `"attack_resolved"` | Phase 4 — after damage applied | `attacker`, `target`, `attack` |
| `"saving_throw"` | Before save roll | `caster`, `target`, `ability`, `dc`, `advantage`, `disadvantage`, `bonus` |
| `"saving_throw_resolved"` | After save resolved | `caster`, `result` (SaveResult) |
| `"creature_downed"` | When HP reaches 0 | `creature` |
| `"opportunity_attack"` | When OA triggers | `attacker`, `target` |

**Modifying events in-place:** Features can modify the `attack` object's fields during `"attack"` (to-hit) and `"damage"` (extra dice), or modify the save context dict during `"saving_throw"` (add bonus, set advantage/disadvantage).

---

## Action Economy

Each turn executes in this order inside `CombatManager`:

```
1. creature.start_turn()          → reset ActionTracker
2. broadcast TurnStarted          → features may grant temp attacks (Dread Ambusher)
3. [Dash if needed]               → spend action, double effective_speed
4. _try_move()                    → move + resolve OAs
5. use_action()                   → spend main action
6. _do_attack_action()            → main attack + use_extra_attack() loop
7. while can_surge:               → Action Surge (fighters)
     use_action_surge()
     _do_attack_action()
8. broadcast TurnEnded
```

`_do_attack_action` is a shared helper used by AI turns, player turns, and Action Surge — it fires one attack then drains `remaining_extra_attacks` in a loop, re-picking targets if the current one goes down mid-loop.

---

## Attack Pipeline

`WeaponAttack.declare_attack()` runs four sequential phases:

```
Phase 1 — broadcast "attack"
          Features modify: to_hit_mod, tags, advantage
          ↓
          roll_to_hit()  →  result["hit"], result["hit_roll"], result["attack_total"]
          ↓
Phase 2 — broadcast "damage"  (only on hit)
          Features modify: extra_dice list
          ↓
          roll_damage()  →  result["damage"]
          target.take_damage() fires here
          ↓
Phase 4 — broadcast "attack_resolved"
          Reactions fire here: HellishRebuke, Shield, Uncanny Dodge, etc.
```

Features hook whichever phase is relevant:
- Modify the **roll** → hook `"attack"` (e.g. Archery +2, Sharpshooter −5/+10)
- Add **extra damage dice** → hook `"damage"` (e.g. Favored Foe 1d6, Sneak Attack)
- **React after damage lands** → hook `"attack_resolved"` (e.g. Hellish Rebuke)

---

## Saving Throws

```python
from core.saving_throw import SavingThrow, DamageOnSave, CommonSaves

# Full control
result = SavingThrow.roll(
    caster      = goblin,
    target      = brendiir,
    ability     = "Dex",        # matches StatBlock key
    dc          = 11,
    on_save     = DamageOnSave.HALF,   # HALF | NONE | FULL
    damage      = 14,
    damage_type = "fire",
    condition_on_fail = None,   # e.g. "frightened", "prone"
    advantage   = False,
    disadvantage = False,
)
# result.success, result.damage_dealt, result.roll, result.total

# Common shortcuts
CommonSaves.dex_half(caster, target, dc=11, damage=14, damage_type="fire")
CommonSaves.wis_condition(caster, target, dc=14, condition="frightened")
CommonSaves.con_half(caster, target, dc=12, damage=10, damage_type="poison")
CommonSaves.str_condition(caster, target, dc=13, condition="prone")
CommonSaves.dex_none(caster, target, dc=15, damage=20, damage_type="lightning")
```

Features can modify saves by subscribing to `"saving_throw"` and mutating the context dict:

```python
def on_saving_throw(self, ctx):
    if ctx["target"] is self.owner:
        ctx["bonus"] += self.owner.proficiency  # e.g. Aura of Protection
        ctx["advantage"] = True                 # e.g. Advantage vs magic
```

---

## Feature System

Every feature is a subclass of `Feature`. Subclassing automatically registers the feature in `Feature.REGISTRY` via `__init_subclass__`, making it available to `_add_feature_by_name`.

```python
from data.features.base import Feature

class MyFeature(Feature):
    name = "My Feature"   # must match the string used in JSON / scenario

    # Map event names to handler method names
    EVENT_MAP = {
        "attack":          "on_attack",
        "attack_resolved": "on_attack_resolved",
        "TurnStarted":     "on_turn_started",
    }

    def on_attack(self, data):
        if data["attacker"] is self.owner:
            data["attack"].to_hit_mod += 1   # +1 to hit

    def on_attack_resolved(self, data):
        # React after damage is dealt
        pass

    def on_turn_started(self, data):
        if data.get("creature") is self.owner and data.get("round") == 1:
            self.owner.speed += 10
```

**To grant temporary extra attacks** (e.g. Haste, Dread Ambusher):
```python
self.owner.actions.grant_temp_extra_attack()
```

**To grant a permanent extra attack** (e.g. Extra Attack feature):
```python
def attach(self, owner, bus):
    super().attach(owner, bus)
    owner.actions.extra_attacks = 1
    owner.actions.remaining_extra_attacks = 1
```

**To grant Action Surge** (e.g. fighter feature):
```python
def attach(self, owner, bus):
    super().attach(owner, bus)
    owner.actions.max_action_surges = 1
    owner.actions.remaining_surges  = 1
```

---

## Tactical AI

`TacticalAI.plan_turn(creature, battle_map, memory=None)` returns a `TacticalDecision` that `CombatManager` executes.

Decision flow:
1. **Pick target** — uses `TeamMemory.recommended_target()` if available, else weakest enemy by HP
2. **Pick weapon** — prefers ranged if target is far, melee if adjacent, avoids disadvantage
3. **Move** — ranged creatures kite, melee creatures close; dash if target unreachable with normal speed
4. **Dash** — if no weapon can reach even after moving, spend action to double speed and try again

`TeamMemory` tracks per-team intelligence:
- Threat profiles per enemy (damage dealt, hit rate, HP trend)
- Ally pressure (how many enemies are targeting each ally)
- `recommended_target()` — focus-fires weakest already-targeted enemy, then highest threat score
- `get_state_vector()` — 10-feature normalised list for the ML strategy layer

**ML strategy layer** (`core/ml_strategy.py`) — not yet wired into live combat, but the infrastructure exists:
```python
from core.ml_strategy import RLStrategySelector, EvolutionarySelector, Strategy

selector = RLStrategySelector()
ai = TacticalAI(strategy_selector=selector)
# Strategies: AGGRESSIVE (charge), KITE (maintain range), RETREAT (fall back)
```

---

## Visualiser

```python
from utils.battle_visualiser import BattleVisualiser

vis = BattleVisualiser(
    battle_map    = bmap,
    event         = event,
    combat_mgr    = cm,
    trail_turns   = None,        # 1 = current turn only | N = last N turns | None = all combat
    save_video    = True,        # write MP4 at end of combat
    video_path    = "combat.mp4",
    frame_duration = 1.5,        # seconds per frame in the video
)
```

Features:
- Movement trail lines per creature, fading with age; historical turns show `R2`, `R3` labels
- Dead creatures stay on the map as ghosted tokens with an X, at their death position
- Token labels: `G1`, `G2` for `Goblin#1`, `Goblin#2`; `B` for `Brendiir`
- Gold glow ring on the active creature; HP bars; threatened-square highlights
- Video export via imageio/ffmpeg; falls back to GIF if MP4 fails

**Keyboard shortcuts during combat:** any key advances to next turn; `Q` quits.

---

## Known Limitations

### Action Economy
- **Bonus action attacks** (e.g. Off-Hand Attack, Polearm Master) are not implemented. The `ActionTracker` tracks `bonus_actions` but no feature currently spends them on attacks.
- **Reactions in player mode** — Hellish Rebuke and OA fire automatically. Players cannot manually choose to use their reaction on other things.
- **Dodge action (AI)** — removed pending a clean `disadvantage` implementation on `WeaponAttack`. The `attack.py` base class only has `self.advantage`.

### Features Not Yet Implemented
The following features appear in the Ranger JSON but print a warning and do nothing:
- `Deft Explorer`, `Spellcasting`, `Ranger Archetype`, `Primeval Awareness`, `Umbral Sight`, `Iron Mind`

The following are partially implemented:
- **Favored Foe** — prints the extra damage die but does not actually add the dice to the roll
- **Bracers of Archery** — checks `data.get("weapon") == "ranged"` but that key is never set in attack data, so the +2 damage bonus never applies

### Spellcasting
- No spell slot tracking
- No concentration management beyond a `concentration` string attribute on `Creature`
- Spells are implemented as features that hook attack/save events, not as a separate casting system

### Combat
- **Multi-target spells** (e.g. Fireball) require a custom feature; there is no AoE target selection in the AI
- **Grapple / Shove** — not implemented
- **Flying / Swim speed** — `BattleMap` is a flat 2D grid; no elevation
- **Cover** — not tracked; all attacks treat LOS as clear
- **Concentration checks** — not triggered when the concentrating creature takes damage
- **Death saving throws** — creatures are simply removed on reaching 0 HP; no downed/stabilise state
- **Short rest / Long rest** — Action Surge resets once per combat, not once per short rest as written

### Map
- All maps are rectangular flat grids using Chebyshev distance (diagonals cost the same as cardinals, which is the D&D 5e optional rule)
- No pathfinding around walls — `_step_toward` walks directly toward the target and may get stuck if a wall blocks the straight line

### Visualiser
- The trail system records one waypoint per `commit_move` call. Because `_step_toward` picks a single destination per turn (not square-by-square), the trail shows start→end per turn rather than every intermediate grid square traversed
- The video export uses `imageio` at a fixed fps derived from `frame_duration`. Very short durations (< 0.5s) may produce inconsistent playback speeds depending on the player

---

## How To: Add a New Character

Add an entry to the `"players"` array in your scenario JSON:

```json
{
  "players": [
    {
      "name": "Valdris",
      "classes": [["Fighter", 5]],
      "subclasses": {"Fighter": "Champion"},
      "stats": {"Str": 18, "Dex": 12, "Con": 16, "Int": 8, "Wis": 10, "Cha": 12},
      "choices": [],
      "items": ["Longsword", "Chain Mail"],
      "equipped": ["Longsword", "Chain Mail"],
      "features": ["Sharpshooter"]
    }
  ]
}
```

**Field reference:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique name on the map |
| `classes` | `[[ClassName, level]]` | One or more classes. First class determines HP. |
| `subclasses` | `{ClassName: SubclassName}` | Keys must match class JSON `subclasses` dict keys |
| `stats` | `{Str, Dex, Con, Int, Wis, Cha}` | Base ability scores before racial bonuses |
| `choices` | `[[class, level, feature, option]]` | For features with options (e.g. Fighting Style) |
| `items` | `[item_name]` | Items to add to inventory; must exist in `data/items.json` |
| `equipped` | `[item_name]` | Subset of items to equip (weapons go to hand slots, armour sets AC) |
| `features` | `[feature_name]` | Extra features beyond what the class grants (feats, racial traits) |

Multiclass example:
```json
"classes": [["Fighter", 3], ["Wizard", 2]]
```
HP uses the first class's hit die formula; both classes' features unlock at the correct levels.

---

## How To: Add a New Class

**Step 1** — Create `data/classes/yourclass.json`:

```json
{
  "class_name": "Paladin",
  "hit_die": 10,
  "primary_abilities": ["Strength", "Charisma"],
  "saving_throws": ["Wisdom", "Charisma"],
  "armor_proficiencies": ["light", "medium", "heavy", "shields"],
  "weapon_proficiencies": ["simple", "martial"],
  "tool_proficiencies": [],
  "skill_choices": {
    "choose": 2,
    "options": ["Athletics", "Insight", "Intimidation", "Medicine", "Persuasion", "Religion"]
  },
  "features_by_level": {
    "1": [
      {"name": "Divine Sense"},
      {"name": "Lay on Hands"}
    ],
    "2": [
      {
        "name": "Fighting Style",
        "options": ["Defense", "Dueling", "Great Weapon Fighting", "Protection"]
      },
      {"name": "Divine Smite"}
    ],
    "5": [
      {"name": "Extra Attack"}
    ]
  },
  "subclasses": {
    "oath of devotion": {
      "features_by_level": {
        "3": [
          {"name": "Sacred Weapon"},
          {"name": "Turn the Unholy"}
        ]
      }
    }
  }
}
```

The feature `name` strings must **exactly match** a class in `Feature.REGISTRY`. If a name has no matching feature class, the framework prints a warning and skips it gracefully.

**Step 2** — Implement any new features (see [Feature System](#feature-system)).

**Step 3** — Import the feature module in `main.py` so it registers:

```python
from data.features.paladin_features import DivineSense, LayOnHands, DivineSmi
```

---

## How To: Add a New Subclass

Add a `subclasses` block to the relevant class JSON. The key must be the subclass name **lowercased with spaces removed**:

```json
"subclasses": {
  "battlemaster": {
    "features_by_level": {
      "3": [
        {"name": "Combat Superiority"},
        {"name": "Student of War"}
      ],
      "7": [
        {"name": "Know Your Enemy"}
      ]
    }
  }
}
```

In the scenario JSON, reference it exactly as typed in the class file (case-insensitive lookup):

```json
"subclasses": {"Fighter": "Battle Master"}
```

The `PlayerCharacter` loader strips spaces and lowercases before matching.

---

## How To: Add a New Spell / Reaction

Spells are implemented as features that hook the attack event pipeline. Most spells fit one of two patterns:

### Pattern 1 — Reaction after being hit (Hellish Rebuke, Shield)

Hook `"attack_resolved"`, check the target is your owner, spend the reaction:

```python
import random
from data.features.base import Feature
from core.saving_throw import CommonSaves

class ShieldSpell(Feature):
    name = "Shield"                              # matches JSON feature name
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def on_attack_resolved(self, data):
        target = data.get("target")
        attack = data.get("attack")

        if target is not self.owner:
            return
        if not attack or not attack.result.get("hit", False):
            return
        if not self.owner.actions.use_reaction():
            return

        # +5 AC until start of next turn — simplest approach: just announce it
        # A full implementation would apply a temporary AC bonus
        print(f"  {self.owner.name} casts Shield! (+5 AC this round)")
```

### Pattern 2 — Spell that deals damage on a save (Fireball, Thunderwave)

Hook `"TurnStarted"` or implement as a feature that fires at the right time, then call `SavingThrow.roll`:

```python
import random
from data.features.base import Feature
from core.saving_throw import SavingThrow, DamageOnSave

class HuntersMark(Feature):
    name = "Hunter's Mark"
    EVENT_MAP = {"damage": "on_damage"}

    def on_damage(self, data):
        if data["attacker"] is not self.owner:
            return
        if "hunters_mark" not in data["attack"].tags:
            return
        # Add 1d6 bonus damage
        data["attack"].extra_dice.append((1, 6))
        print(f"  Hunter's Mark adds 1d6!")

class Thunderwave(Feature):
    """Example: CON save, 2d8 thunder on fail, push 10ft on fail."""
    name = "Thunderwave"
    EVENT_MAP = {}

    def cast(self, caster, target, dc: int):
        damage = sum(random.randint(1, 8) for _ in range(2))
        result = SavingThrow.roll(
            caster      = caster,
            target      = target,
            ability     = "Con",
            dc          = dc,
            on_save     = DamageOnSave.HALF,
            damage      = damage,
            damage_type = "thunder",
        )
        if not result.success:
            print(f"  {target.name} is pushed 10ft!")
            # Position update would go here
```

---

## How To: Add a New Item

### Weapon or Armour (data-driven)

Add an entry to `data/items.json`:

```json
{
  "Rapier": {
    "name": "Rapier",
    "type": "weapon",
    "damage_die": "1d8",
    "damageType": "piercing",
    "ability": "Dex",
    "weapon_type": "martial",
    "attack_type": "melee",
    "normal_range": 5,
    "long_range": 5,
    "attack_bonus": 0,
    "damage_bonus": 0,
    "properties": ["finesse"]
  }
}
```

For a magic weapon, set `attack_bonus` and/or `damage_bonus`:

```json
{
  "Flame Tongue Longsword": {
    "name": "Flame Tongue Longsword",
    "type": "weapon",
    "damage_die": "1d8",
    "damageType": "slashing",
    "ability": "Str",
    "weapon_type": "martial",
    "attack_type": "melee",
    "normal_range": 5,
    "long_range": 5,
    "attack_bonus": 1,
    "damage_bonus": 1,
    "properties": ["versatile"]
  }
}
```

For armour:

```json
{
  "Half Plate": {
    "name": "Half Plate",
    "type": "armor",
    "base_ac": 15,
    "armor_type": "medium",
    "magic_bonus": 0,
    "Description": "Half plate armour"
  }
}
```

### Magic Item with a Feature (data + code)

Add the item to `data/items.json` with a `"feature"` field that matches the feature class `name`:

```json
{
  "Amulet of Health": {
    "name": "Amulet of Health",
    "type": "trinket",
    "item_slot": "Neck",
    "required_attunement": "True",
    "feature": "AmuletOfHealth",
    "description": "Sets Constitution to 19 while attuned."
  }
}
```

Then implement the feature:

```python
# data/features/magic_items.py

class AmuletOfHealth(Feature):
    name = "Amulet Of Health"
    EVENT_MAP = {}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        # Force Con to 19 if currently lower
        if owner.statblock.scores.get("Con", 10) < 19:
            owner.statblock.scores["Con"] = 19
            owner.statblock.mods["Con"]   = 4
            print(f"  {owner.name}'s Constitution set to 19 (Amulet of Health)")
```

Import the feature in `main.py` so the registry can find it:

```python
from data.features.magic_items import BracersOfArchery, AmuletOfHealth
```

---

## How To: Add a New Monster

Add a dict to `data/monsters/monsters.py` and register it:

```python
TROLL = {
    "name": "Troll",
    "hp": 84,
    "ac": 15,
    "proficiency": 3,
    "stats": {
        "Str": 18, "Dex": 13, "Con": 20,
        "Int": 7,  "Wis": 9,  "Cha": 7,
    },
    "save_proficiencies": [],
    "attacks": [
        {
            "name": "Bite",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
        {
            "name": "Claw",
            "attack_type": "melee",
            "attack_bonus": 7,
            "damage_die": 6,
            "damage_mod": 4,
            "normal_range": 5,
            "long_range": 5,
        },
    ],
    "features": ["Regeneration"],   # must be in Feature.REGISTRY
}

MONSTER_REGISTRY["TROLL"] = TROLL
```

If the monster has a special feature (like Regeneration), implement it as a `Feature` subclass and import it in `main.py`. Then reference it in the scenario JSON:

```json
"monsters": [
  {"type": "TROLL", "count": 1}
]
```

**Attack dict field reference:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name |
| `attack_type` | `"melee"` or `"range"` | Determines range checking |
| `attack_bonus` | int | Flat bonus added to the d20 roll |
| `damage_die` | int | Size of damage die (e.g. `6` for 1d6) |
| `damage_mod` | int | Flat bonus added to damage |
| `normal_range` | int | Normal range in feet |
| `long_range` | int | Long range in feet (disadvantage beyond normal) |

---

## Running a Scenario

```powershell
# Auto combat with visualiser
python main.py --json brendiir_vs_goblins.json

# Player controls blue team
python main.py --json brendiir_vs_goblins.json --player

# No visualiser (terminal only)
python main.py --json brendiir_vs_goblins.json --no-vis
```

**Player turn commands:**

| Command | Effect |
|---|---|
| `move <col> <row>` | Move to a grid square |
| `attack` | Attack the nearest enemy (prompts for target/weapon) |
| `dash` | Spend action for +speed movement this turn |
| `surge` | Spend Action Surge for an extra attack action (fighters only) |
| `map` | Reprint the ASCII map |
| `info` | Show HP and action resources |
| `auto` | Hand turn off to the AI |
| `end` | End your turn |

**Scenario JSON map format:**

```json
"map": {
  "width": 20,
  "height": 16,
  "walls":            [[col, row, width, height]],
  "difficult_terrain": [[col, row, width, height]]
}
```

**Scenario JSON positions format:**

```json
"positions": {
  "Brendiir": [3, 7],
  "monsters": [[14, 5], [14, 10]]
}
```

Any players or monsters without explicit positions are auto-placed: players in the left 20% of the map, monsters in the right 20%, scanning row by row for passable unoccupied squares.