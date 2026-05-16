"""
api.py — FastAPI wrapper for DnDPython combat simulator
Place this file in the root of your DnDPython/ folder (same level as main.py).

Run locally with:
    pip install fastapi uvicorn
    uvicorn api:app --reload

Then open http://127.0.0.1:8000/docs to explore the interactive API.
"""

import contextlib
import io
import json
import os
import importlib
import pkgutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Path setup ──────────────────────────────────────────────────────────────
# Makes sure relative imports (scenarios/, data/) work no matter where
# uvicorn is launched from.
ROOT = Path(__file__).parent
os.chdir(ROOT)

# ── One-time feature registration (mirrors main.py) ──────────────────────────
import data.features
for _mod in pkgutil.iter_modules(data.features.__path__):
    if _mod.name != "base":
        importlib.import_module(f"data.features.{_mod.name}")

from data.monsters.monsters import MONSTER_REGISTRY
from core.events import EventBus
from core.InitiativeManager import InitiativeManager
from core.combat_manager import CombatManager, CombatMode
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader, build_map, place_creatures

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DnDPython Combat API",
    description="Run D&D 5e combat simulations and get structured results back.",
    version="0.1.0",
)

# Allow any origin while you're developing locally.
# Lock this down to your actual domain before going live.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────


class SimulateRequest(BaseModel):
    scenario: dict[str, Any] | None = None
    scenario_name: str | None = None
    episodes: int = 1
    max_episodes: int = 100
    silent: bool = True
    strategy: str | None = None      # aggressive, kite, retreat, focus_fire, protect
    model_path: str | None = None    # path to a saved model file
    model_type: str = "dqn"          # dqn | rl | evo
    trained_team: str = "red"        # which team the loaded model controls


class CreatureSummary(BaseModel):
    name: str
    team: str
    hp: int
    max_hp: int
    alive: bool


class SimulateResponse(BaseModel):
    episodes_run: int
    wins: dict[str, int]             # e.g. {"blue": 7, "red": 2, "none": 1}
    win_rate: float                  # blue team win rate
    avg_rounds: float
    sample_outcome: str              # last episode's outcome string
    creatures: list[CreatureSummary] # last episode's final state
    log: str                         # last episode's combat log
    tactic_distribution: dict[str, int] = {}  # strategy name -> times chosen (model only)

# ── Helper ────────────────────────────────────────────────────────────────────

import random as _random

def _run_episode(
    scenario_data: dict,
    silent: bool = True,
    strategy: str | None = None,
    model_path: str | None = None,
    model_type: str = "dqn",
    trained_team: str = "red",
) -> dict:
    """Run a single combat episode. Returns a plain dict with episode results."""
    captured = io.StringIO()
    ctx = contextlib.redirect_stdout(captured) if silent else contextlib.nullcontext()

    with ctx:
        event   = EventBus()
        factory = CreatureFactory()
        loader  = ScenarioLoader(factory, event)
        players, monsters = loader.load(scenario_data)

        monster_idx = 0
        for tmpl in scenario_data.get("monsters", []):
            mtype = tmpl.get("type", "").upper()
            count = tmpl.get("count", 1)
            role  = tmpl.get("weapon_role", "random")
            if mtype not in MONSTER_REGISTRY:
                monster_idx += count
                continue
            all_attacks    = MONSTER_REGISTRY[mtype].get("attacks", [])
            melee_attacks  = [a for a in all_attacks if a.get("attack_type", "melee") == "melee"]
            ranged_attacks = [a for a in all_attacks if a.get("attack_type", "melee") != "melee"]
            for _ in range(count):
                if monster_idx >= len(monsters):
                    break
                m = monsters[monster_idx]
                if role == "all":
                    m._attack_templates = all_attacks
                elif role == "melee":
                    m._attack_templates = melee_attacks or all_attacks
                elif role == "ranged":
                    m._attack_templates = ranged_attacks or all_attacks
                else:
                    m._attack_templates = _random.choice(
                        [melee_attacks, ranged_attacks]
                    ) or all_attacks
                monster_idx += 1

        battle_map = build_map(scenario_data)
        place_creatures(scenario_data, players, monsters, battle_map)
        initiative = InitiativeManager(players + monsters, event)
        max_rounds = scenario_data.get("max_rounds", 100)
        cm = CombatManager(event, initiative, battle_map, max_rounds=max_rounds)
        if model_path:
            full_path = str(ROOT / model_path)
            if model_type == "rl":
                from core.selectors.rl_selector import RLStrategySelector
                sel = RLStrategySelector()
                sel.load(full_path)
                sel.eps = 0.0
            elif model_type == "evo":
                from core.selectors.evo_selector import EvolutionarySelector
                sel = EvolutionarySelector()
                sel.load(full_path)
            else:
                from core.selectors.dqn_selector import DQNStrategySelector
                sel = DQNStrategySelector()
                sel.load(full_path)
                sel.eps = 0.0
            cm.ai.strategy_selector = sel
            cm.ai.trained_team = trained_team
        elif strategy:
            from core.ml_strategy import Strategy as StrategyEnum
            try:
                cm.ai.current_strategy = StrategyEnum[strategy.upper()]
            except KeyError:
                pass
        outcome = cm.run()

    log = captured.getvalue()

    sel = cm.ai.strategy_selector
    tactic_counts = (
        {s.name.lower(): c for s, c in sel.tactic_counts.items() if c > 0}
        if sel is not None else {}
    )

    outcome_lower = outcome.lower()
    if "blue" in outcome_lower:
        winner = "blue"
    elif "red" in outcome_lower:
        winner = "red"
    else:
        winner = None

    all_creatures = players + monsters
    summaries = [
        CreatureSummary(
            name=c.name,
            team=getattr(c, "team", "unknown"),
            hp=max(c.hp, 0),
            max_hp=c.max_hp,
            alive=c.is_alive(),
        )
        for c in all_creatures
    ]

    return {
        "outcome": outcome,
        "winner": winner,
        "rounds": cm.initiative.round,
        "creatures": summaries,
        "log": log,
        "tactic_counts": tactic_counts,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", summary="Health check")
def root():
    """Quick ping to confirm the API is running."""
    return {"status": "ok", "message": "DnDPython API is live."}


@app.get("/scenarios", summary="List available scenario files")
def list_scenarios():
    """Returns the names of all .json files in the scenarios/ folder."""
    scenarios_dir = ROOT / "scenarios"
    if not scenarios_dir.exists():
        return {"scenarios": []}
    files = [f.name for f in scenarios_dir.glob("*.json")]
    return {"scenarios": files}


@app.get("/scenarios/{filename}", summary="Fetch a scenario's JSON")
def get_scenario(filename: str):
    """Returns the raw JSON of a named scenario file."""
    path = ROOT / "scenarios" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{filename}' not found.")
    return json.loads(path.read_text())


@app.post("/simulate", response_model=SimulateResponse, summary="Run a combat simulation")
def simulate(req: SimulateRequest):
    """
    Run a full combat simulation.

    Supply **either**:
    - `scenario_name` — the filename of a scenario in scenarios/ (e.g. `"brendiir_vs_goblins.json"`)
    - `scenario` — a complete scenario dict inline in the request body

    Returns the outcome, round count, per-creature final HP, and the full combat log.
    """
    if req.scenario_name:
        path = ROOT / "scenarios" / req.scenario_name
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Scenario '{req.scenario_name}' not found.")
        scenario_data = json.loads(path.read_text())
    elif req.scenario is not None:
        scenario_data = req.scenario
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'scenario_name' or 'scenario' in the request body."
        )

    n = min(req.episodes, req.max_episodes)
    wins: dict[str, int] = {"blue": 0, "red": 0, "none": 0}
    total_rounds = 0
    tactic_totals: dict[str, int] = {}
    last: dict = {}

    try:
        for _ in range(n):
            last = _run_episode(
                scenario_data,
                silent=req.silent,
                strategy=req.strategy,
                model_path=req.model_path,
                model_type=req.model_type,
                trained_team=req.trained_team,
            )
            wins[last["winner"] or "none"] += 1
            total_rounds += last["rounds"]
            for tactic, count in last.get("tactic_counts", {}).items():
                tactic_totals[tactic] = tactic_totals.get(tactic, 0) + count
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return SimulateResponse(
        episodes_run=n,
        wins=wins,
        win_rate=wins["blue"] / n if n else 0.0,
        avg_rounds=total_rounds / n if n else 0.0,
        sample_outcome=last.get("outcome", ""),
        creatures=last.get("creatures", []),
        log=last.get("log", ""),
        tactic_distribution=tactic_totals,
    )


@app.get("/models", summary="List available trained models")
def list_models():
    """Returns model files in docs/models/ with inferred types."""
    models_dir = ROOT / "docs" / "models"
    if not models_dir.exists():
        return {"models": []}
    models = []
    for f in sorted(models_dir.iterdir()):
        if f.suffix in (".pt", ".pth"):
            model_type = "dqn"
        elif f.suffix == ".npy":
            model_type = "rl"  # user can override to "evo" in the UI
        else:
            continue
        models.append({
            "name": f.name,
            "path": f"docs/models/{f.name}",
            "type": model_type,
        })
    return {"models": models}


@app.get("/monsters", summary="List known monster types")
def list_monsters():
    """Returns all monster types registered in MONSTER_REGISTRY."""
    return {"monsters": sorted(MONSTER_REGISTRY.keys())}


@app.get("/monsters/{name}", summary="Get a monster's full stat block")
def get_monster(name: str):
    key = name.upper()
    if key not in MONSTER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Monster '{name}' not found.")
    return MONSTER_REGISTRY[key]


# ── Character-builder helpers ─────────────────────────────────────────────────

@app.get("/classes", summary="List all available classes")
def list_classes():
    """
    Returns a summary of every class JSON found in data/classes/.
    Includes hit die, saving throws, and available subclasses.
    """
    classes_dir = ROOT / "data" / "classes"
    results = []
    for path in sorted(classes_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        results.append({
            "name":           data["class_name"],
            "hit_die":        data["hit_die"],
            "saving_throws":  data.get("saving_throws", []),
            "armor_profs":    data.get("armor_proficiencies", []),
            "weapon_profs":   data.get("weapon_proficiencies", []),
            "subclasses":     list(data.get("subclasses", {}).keys()),
            "features_by_level": {
                lvl: [f["name"] for f in feats]
                for lvl, feats in data.get("features_by_level", {}).items()
            },
        })
    return {"classes": results}


@app.get("/classes/{name}", summary="Get full class data")
def get_class(name: str):
    """Returns the complete JSON for one class (features, subclasses, spellcasting)."""
    path = ROOT / "data" / "classes" / f"{name.lower()}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Class '{name}' not found.")
    with open(path) as f:
        return json.load(f)


@app.get("/items", summary="List all available items")
def list_items():
    """
    Returns items.json grouped by type: weapons, armor, trinkets.
    Each weapon entry includes damage_die, ability, attack_type, and properties.
    """
    items_path = ROOT / "data" / "items.json"
    with open(items_path) as f:
        raw = json.load(f)

    weapons, armor, trinkets = [], [], []
    for key, item in raw.items():
        if key == "comment":
            continue
        t = item.get("type", "")
        if t == "weapon":
            weapons.append({
                "name":        item["name"],
                "damage_die":  item.get("damage_die"),
                "damage_type": item.get("damageType"),
                "ability":     item.get("ability"),
                "attack_type": item.get("attack_type"),
                "range":       f"{item.get('normal_range',5)}/{item.get('long_range',5)}",
                "properties":  item.get("properties", []),
                "attack_bonus": item.get("attack_bonus", 0),
                "damage_bonus": item.get("damage_bonus", 0),
            })
        elif t == "armor":
            weapons_or_armor = armor
            armor.append({
                "name":       item["name"],
                "base_ac":    item.get("base_ac"),
                "armor_type": item.get("armor_type"),
                "magic_bonus": item.get("magic_bonus", 0),
            })
        elif t == "trinket":
            trinkets.append({
                "name":    item["name"],
                "feature": item.get("feature"),
                "description": item.get("description", ""),
            })

    return {"weapons": weapons, "armor": armor, "trinkets": trinkets}


@app.get("/features", summary="List available feats and features")
def list_features():
    """
    Returns the names of all registered Feature subclasses.
    These can be added to a character via the 'features' array in a scenario.
    """
    from data.features.base import Feature
    # Filter to standalone feats (exclude pure class features that need class levels)
    _CLASS_ONLY = {
        "Rage", "Reckless Attack", "Danger Sense", "Extra Attack", "Extra Attack II",
        "Extra Attack III", "Fast Movement", "Feral Instinct", "Brutal Critical",
        "Brutal Critical II", "Brutal Critical III", "Relentless Rage",
        "Persistent Rage", "Primal Champion", "Frenzy", "Mindless Rage",
        "Retaliation", "Bear Totem Spirit", "Lay on Hands", "Divine Smite",
        "Aura of Protection", "Aura of Courage", "Improved Divine Smite",
        "Sacred Weapon", "Vow of Enmity", "Soul of Vengeance",
        "Sneak Attack", "Cunning Action", "Uncanny Dodge", "Evasion",
        "Slippery Mind", "Elusive", "Stroke of Luck", "Assassinate", "Death Strike",
        "Eldritch Blast", "Pact Magic", "Agonizing Blast", "Repelling Blast", "Hex",
        "Dark One's Blessing", "Fiendish Resilience", "Second Wind", "Action Surge",
        "Action Surge II", "Indomitable", "Indomitable II", "Indomitable III",
        "Improved Critical", "Superior Critical", "Survivor",
        "Favored Foe", "Roving", "Feral Senses", "Foe Slayer",
        "Dread Ambusher", "Iron Mind", "Stalker's Flurry", "Shadowy Dodge",
        "Nature's Veil", "Land's Stride",
    }
    all_names = sorted(Feature.REGISTRY.keys())
    standalone = [n for n in all_names if n not in _CLASS_ONLY
                  and not n.startswith("ASI")]
    return {
        "all_features":        all_names,
        "standalone_feats":    standalone,
    }


# ── Scenario management ───────────────────────────────────────────────────────

class SaveScenarioRequest(BaseModel):
    scenario:  dict[str, Any]
    filename:  str                   # e.g. "gornak_vs_goblins.json"
    overwrite: bool = False


class SaveScenarioResponse(BaseModel):
    saved:    bool
    filename: str
    path:     str


@app.post("/scenarios", response_model=SaveScenarioResponse, summary="Save a scenario to disk")
def save_scenario(req: SaveScenarioRequest):
    """
    Save a scenario dict as a JSON file in scenarios/.
    The saved file can then be referenced by name in /simulate requests.

    Set overwrite=true to replace an existing file.
    """
    if not req.filename.endswith(".json"):
        req.filename += ".json"

    # Basic validation
    sc = req.scenario
    if "players" not in sc or "monsters" not in sc:
        raise HTTPException(
            status_code=422,
            detail="Scenario must contain 'players' and 'monsters' keys."
        )

    out_path = ROOT / "scenarios" / req.filename
    if out_path.exists() and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"'{req.filename}' already exists. Set overwrite=true to replace it."
        )

    out_path.write_text(json.dumps(sc, indent=2))
    return SaveScenarioResponse(
        saved=True,
        filename=req.filename,
        path=str(out_path),
    )


@app.delete("/scenarios/{filename}", summary="Delete a scenario file")
def delete_scenario(filename: str):
    """Permanently removes a scenario file from scenarios/."""
    path = ROOT / "scenarios" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"'{filename}' not found.")
    path.unlink()
    return {"deleted": True, "filename": filename}


# ── Character validation ──────────────────────────────────────────────────────

class ValidateCharacterRequest(BaseModel):
    player: dict[str, Any]


@app.post("/validate-character", summary="Validate a player definition without running combat")
def validate_character(req: ValidateCharacterRequest):
    """
    Dry-run a player definition through the loader to catch errors
    (missing items, unknown class/subclass, unrecognised features, etc.)
    before embedding it in a full scenario.

    Returns warnings and the computed HP/AC if valid.
    """
    import io, contextlib

    player = req.player
    required = ["name", "classes", "stats", "items", "equipped"]
    missing = [k for k in required if k not in player]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Player definition missing required keys: {missing}"
        )

    # Build a minimal test scenario
    test_scenario = {
        "map": {"width": 10, "height": 10, "walls": [], "difficult_terrain": []},
        "positions": {player["name"]: [2, 2], "monsters": [[7, 7]]},
        "players": [player],
        "monsters": [{"type": "GOBLIN", "count": 1}],
    }

    buf = io.StringIO()
    warnings = []
    try:
        with contextlib.redirect_stdout(buf):
            event   = EventBus()
            factory = CreatureFactory()
            loader  = ScenarioLoader(factory, event)
            players, _ = loader.load(test_scenario)
            pc = players[0]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load character: {exc}")

    log = buf.getvalue()
    for line in log.splitlines():
        if "couldn't find" in line.lower() or "not found" in line.lower():
            warnings.append(line.strip())

    return {
        "valid":    True,
        "warnings": warnings,
        "hp":       pc.max_hp,
        "ac":       pc.ac,
        "features": [f.name for f in pc.features],
        "log":      log,
    }