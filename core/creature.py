# -*- coding: utf-8 -*-
from core.actionTracker import ActionTracker
from core.statBlock import StatBlock
from core.creature_observer import CreatureObserver
import random
import itertools

class Creature:
    _id_counter = itertools.count(1)
    def __init__(self, name, hp, ac, stats, eventManager,attacks=[],proficiency=2):
        self.ID = next(Creature._id_counter)
        self.name = name
        self.hp = hp
        self.ac = ac
        self.statblock = StatBlock(stats, proficiency)
        self.observer = CreatureObserver(self)
        self.event_manager = eventManager
        self.event_manager.register(eventManager)
        self.attacks = attacks if attacks else []   # list of Attack objects
        self.actions = ActionTracker()
        self.team = "red"
        self.inventory = []
        self.equiped_items = []
        self.equiped_slots = {"armor":False,"hand1":False,"hand2":False,"Ring":[],"Boots":False,"Cloak":False}
        self.initiative_mod = 0
        self.initiative_advantage = False
        self.initiative_roll = None
    
    def add_item(self,item):
        self.inventory.append(item)
    def equip_item(self,item_name):
        item = next((i for i in self.inventory if i.name.lower() == item_name.lower()),None)
        if not item:
            print(f"{self.name} doesn't have {item_name}")
            return
        if item.item_type == "weapon" or item.item_type == "shield":
            #Check for has properties to hand shields using the same equiping logic
            if hasattr(item,"properties") and "two-handed" in item.properties:
                if not self.equiped_slots["hand1"] and not self.equiped_slots["hand2"]:
                    self.equiped_slots["hand1"] = True
                    self.equiped_slots["hand2"] = True
                    self.equiped_items.append(item)
                else:
                    print(f"Failed to equip {item.name} because you don't have two free hands")
            else:
                if not self.equiped_slots["hand1"] or not self.equiped_slots["hand2"]:
                    if not self.equpied_slots["hand1"]:
                        self.equpied_slots["hand1"] = True
                    else:
                        self.equiped_slots["hand2"] = True
                    self.equiped_items.append(item)
                else:
                    print(f"Failed to equip {item.name} because you don't have a free hand")
        if item.item_type == "armor":
            if not self.equiped_slots["armor"]:
                self.equiped_slots["armor"] = True
                self.equiped_items.append(item)
            else:
                print(f"Failed to equip {item.name} because you are already wearing armor")
        #TODO Recalculate values (attackMod,saveThrow,AC,HP)
    def roll_initiative(self):
        roll1 = random.randint(1, 20) + self.statblock.mod("Dex") + self.initiative_mod
        if self.initiative_advantage:
            roll2 = random.randint(1, 20) + self.statblock.mod("Dex") + self.initiative_mod
            self.initiative_roll = max(roll1, roll2)
        else:
            self.initiative_roll = roll1
        return self.initiative_roll

    def start_turn(self):
        self.actions.reset()

    def is_alive(self):
        return self.hp > 0
