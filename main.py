# -*- coding: utf-8 -*-
"""
Created on Tue Aug 19 19:02:08 2025

@author: Bryce
"""
import os
global FOLDER_PATH 
FOLDER_PATH= os.sep.join(os.path.abspath(__file__).split(os.sep)[:-1])
from utils.loader import load_class_json
from utils.load_item import load_item_json
from core.player2 import PlayerCharacter
from core.events import EventManager
from data.monsters.monsters import *
from data.features.features import *
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader
import json
from pdb import set_trace as S

def is_side_fighting(side):
    return True if True in [creature.is_alive() for creature in side] else False
def load_json(filename):
    """Utility to load scenario JSON from file."""
    with open(os.path.join("scenarios", filename), "r") as f:
        return json.load(f)
def main():
    event = EventManager()
    factory = CreatureFactory()
    # Load scenario (could come from a .json file)
    scenario_data = load_json("brendiir_vs_goblins.json")
    loader = ScenarioLoader(factory, event)
    players, monsters = loader.load(scenario_data)
    # Example combat start
    brendiir = players[0]
    goblin = monsters[0]

    brendiir.perform_attack(goblin, item=brendiir.get_item("longbow"))
if __name__ == "__main__":
    main()
