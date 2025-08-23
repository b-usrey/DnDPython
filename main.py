# -*- coding: utf-8 -*-
"""
Created on Tue Aug 19 19:02:08 2025

@author: Bryce
"""
from utils.loader import load_class_json
from utils.load_item import load_item_json
from core.player import PlayerCharacter
from core.events import EventManager
from core.creature import Creature
from data.monsters.monsters import *
from utils.creatureFactory import CreatureFactory

from pdb import set_trace as S

def is_side_fighting(side):
    return True if True in [creature.is_alive() for creature in side] else False

def main():
    event = EventManager()
    # Load Ranger class from JSON
    factory = CreatureFactory()
    blueTeam = []
    redTeam = []
    ranger_class = load_class_json("ranger")
    longbow = load_item_json("longbow")
    studded_leather_p1 = load_item_json("studded_leather+1")
    brendiirStats = {"Str":10,"Dex":20,"Con":14,"Int":9,"Wis":16,"Cha":8}
    Brendiir = PlayerCharacter("Brendiir", [(ranger_class,8)],brendiirStats,event)
    blueTeam.append(Brendiir)
    Brendiir.add_item(longbow)
    Brendiir.add_item(studded_leather_p1)
    Brendiir.equip_item("+1 studded leather")
    Brendiir.equip_item("Longbow")
    S()    
    goblin1 = factory.create(GOBLIN)
    redTeam.append(goblin1)
    S()

if __name__ == "__main__":
    main()
