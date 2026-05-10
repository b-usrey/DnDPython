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
    episodes: int = 1          # how many fights to run
    max_episodes: int = 100    # hard cap — ignore if user sends more
    silent: bool = True


class CreatureSummary(BaseModel):
    name: str
    team: str
    hp: int
    max_hp: int
    alive: bool


class SimulateResponse(BaseModel):
    outcome: str
    winner: str | None
    rounds: int
    timed_out: bool
    creatures: list[CreatureSummary]
    log: str

# ── Helper ────────────────────────────────────────────────────────────────────

def _run_simulation(scenario_data: dict, silent: bool = True) -> SimulateResponse:
    """
    Core simulation runner — extracted from main.py so the API can call it
    without touching argparse or the file system beyond loading the scenario.
    """
    
    captured = io.StringIO()
    ctx = contextlib.redirect_stdout(captured) if silent else contextlib.nullcontext()

    with ctx:
        event   = EventBus()
        
        factory = CreatureFactory()
        loader  = ScenarioLoader(factory, event)
        players, monsters = loader.load(scenario_data)

        # Attach monster attack templates (mirrors main.py logic)
        import random as _random
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
        outcome = cm.run()

    log = captured.getvalue()

    # ── Determine winner from outcome string ──────────────────────────────
    outcome_lower = outcome.lower()
    if "blue" in outcome_lower:
        winner = "blue"
    elif "red" in outcome_lower:
        winner = "red"
    else:
        winner = None

    # ── Snapshot every creature's final state ─────────────────────────────
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

    return SimulateResponse(
        outcome=outcome,
        winner=winner,
        rounds=cm.initiative.round,
        timed_out=cm.timed_out,
        creatures=summaries,
        log=log,
    )


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

    try:
        return _run_simulation(scenario_data, silent=req.silent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/monsters", summary="List known monster types")
def list_monsters():
    """Returns all monster types registered in MONSTER_REGISTRY."""
    return {"monsters": sorted(MONSTER_REGISTRY.keys())}