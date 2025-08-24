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

from pdb import set_trace as S

def is_side_fighting(side):
    return True if True in [creature.is_alive() for creature in side] else False

def main():
    event = EventManager()
    # Load Ranger class from JSON
    factory = CreatureFactory()
    brendiirStats = {"Str":10,"Dex":20,"Con":14,"Int":9,"Wis":16,"Cha":8}
    blueTeam = []
    redTeam = []
    longbow = load_item_json("longbow")
    studded_leather_p1 = load_item_json("studded_leather+1")
    
    Brendiir = PlayerCharacter("Brendiir",[("Ranger",8)],{"Ranger":"Gloomstalker"},brendiirStats,event)
    blueTeam.append(Brendiir)
    Brendiir.add_item(longbow)
    Brendiir.add_item(studded_leather_p1)
    Brendiir.equip_item("+1 studded leather")
    Brendiir.equip_item("Longbow")
    Brendiir.features.append(Sharpshooter("Sharpshooter"))
    goblin = factory.create(GOBLIN,event)
    Brendiir.perform_attack(goblin)

if __name__ == "__main__":
    main()
