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
from core.events import EventBus
from data.monsters.monsters import *
from core.InitiativeManager import InitiativeManager
from data.features.features import *
from utils.creatureFactory import CreatureFactory
from utils.scenarioLoader import ScenarioLoader
from utils.genericListener import Listener
import json
from pdb import set_trace as S

def is_side_fighting(side):
    return True if True in [creature.is_alive() for creature in side] else False
def load_json(filename):
    """Utility to load scenario JSON from file."""
    with open(os.path.join("scenarios", filename), "r") as f:
        return json.load(f)
def main(args):
    event = EventBus()
    factory = CreatureFactory()
    _ = Listener(event)

    
    # Load scenario (could come from a .json file)
    scenario_data = load_json(args.json)
    loader = ScenarioLoader(factory, event)
    players, monsters = loader.load(scenario_data)
    initiative = InitiativeManager(players+monsters, event)
    initiative.roll_initiative()
    initiative.start_combat()
    attack = players[0].perform_attack(monsters[0],item='Longbow+1')
    print(attack.tags,attack.to_hit_mod)

    #brendiir.perform_attack(goblin, item=brendiir.get_item("Longbow+1"))
if __name__ == "__main__":
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--json",help="Path to scenario json you want to load")
    args = parser.parse_args()
    main(args)
