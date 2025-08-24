# -*- coding: utf-8 -*-
from core.actionTracker import ActionTracker
from core.statBlock import StatBlock
from core.creature_observer import CreatureObserver
from core.attack import WeaponAttack
import random
import itertools

from pdb import set_trace as S

class Creature:
    _id_counter = itertools.count(1)
    def __init__(self, name, hp, ac, stats, eventManager,proficiency=2):
        self.ID = next(Creature._id_counter)
        self.name = name
        self.hp = hp
        self.ac = ac
        self.statblock = StatBlock(stats, proficiency)
        self.observer = CreatureObserver(self)
        self.event_manager = eventManager
        self.event_manager.register(eventManager)
        self.actions = ActionTracker()
        self.team = "red"
        self.inventory = []
        self.equipped_items = []
        self.equipped_slots = {"armor":None,"hand1":None,"hand2":None,"Ring":[],"Boots":None,"Cloak":None}
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
                if not self.equipped_slots["hand1"] and not self.equipped_slots["hand2"]:
                    self.equipped_slots["hand1"] = item.name
                    self.equipped_slots["hand2"] = item.name
                    self.equipped_items.append(item)
                else:
                    print(f"Failed to equip {item.name} because you don't have two free hands")
            else:
                if not self.equipped_slots["hand1"] or not self.equipped_slots["hand2"]:
                    if not self.equipped_slots["hand1"]:
                        self.equipped_slots["hand1"] = item.name
                    else:
                        self.equipped_slots["hand2"] = item.name
                    self.equipped_items.append(item)
                else:
                    print(f"Failed to equip {item.name} because you don't have a free hand")
            self.attack_options()
        if item.item_type == "armor":
            if not self.equipped_slots["armor"]:
                self.equipped_slots["armor"] = item.name
                self.equipped_items.append(item)
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
    def attack_options(self):
        for item in self.equipped_items:
            if item.item_type == "weapon":
                pass #TODO Logic should go here for add attack option when weapons are equipped
    def start_turn(self):
        self.actions.reset()
    def is_alive(self):
        return self.hp > 0 
    def perform_attack(self,target):
        attack = WeaponAttack(self,target,8)
        for f in self.features:
            f.on_attack(attack)
        attack.roll_to_hit()
        print(attack.result)
