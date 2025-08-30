# -*- coding: utf-8 -*-
from core.actionTracker import ActionTracker
from core.statBlock import StatBlock
from core.creature_observer import CreatureObserver
from core.attack import WeaponAttack
from core.item import Item
from data.features.features import Feature
import random
import itertools

from pdb import set_trace as S

class Creature:
    _id_counter = itertools.count(1)
    def __init__(self, name, hp, ac, stats, eventManager,proficiency=2):
        '''
        name: Name of character, doesn't have to be unique
        hp: HP of creature
        ac: AC of creature, could change later based on equipment
        eventManager: observer used to broadcast and receive messages
        '''
        self.ID = next(Creature._id_counter)
        self.name = name
        self.hp = hp
        self.ac = ac
        self.statblock = StatBlock(stats, proficiency)
        self.proficiency = proficiency
        self.observer = CreatureObserver(self)
        self.event_manager = eventManager
        self.event_manager.subscribe("*",self.observer)
        self.actions = ActionTracker()
        self.team = "red"
        self.inventory = []
        self.equipped_items = []
        self.equipped_slots = {"armor":None,"hand1":None,"hand2":None,"Ring":[],"Boots":None,"Cloak":None,"Bracers":None,}
        self.initiative_mod = 0
        self.initiative_advantage = False
        self.initiative_roll = None
    def get_item(self,itemName):
        for item in self.inventory:
            if item.name.lower() == itemName.lower():
                return item
    def notify(self,event_type,data):
        """Called whenever EventManager broadcasts an event"""
        if event_type == "attack_rolled":
            if data['attacker'].ID != self.ID:
                print(f"{self.name} sees a total roll of {data['data']['attack_total']}")
            if data['target'].ID == self.ID:
                print("Run away")
        elif event_type == "TurnStarted" and data["creature"] == self:
            print(f"{self.name} begins their turn in round {data['round']}.")
        elif event_type == "TurnEnded" and data["creature"] == self:
            print(f"{self.name} ends their turn.")
        elif event_type == "RoundStarted":
            print(f"{self.name} notices round {data['round']} has started.")
    def add_item(self,item):
        self.inventory.append(item)
    def _add_feature_by_name(self, name):
        """Helper to add a feature from the registry by name."""
        if name in Feature.REGISTRY:
            if name == "sharpshooter":
                S()
            feature_class = Feature.REGISTRY[name]
            feature = feature_class()                     # create once
            self.features.append(feature)                 # store it
            feature.attach(self, self.event_manager)      # attach to creature + bus
        else:
            print(f"⚠ Feature {name} not found in registry, storing raw name")
            self.features.append(name)  # fallback to string
 
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
        if item.item_type == "trinket":
            if not self.equipped_slots[item.item_slot]:
                self.equipped_items.append(item)
                self.equipped_slots[item.item_slot] = item.name
        for item in self.equipped_items:
            if hasattr(item,"feature"):
                self.features.append(self._add_feature_by_name(item.name))
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
    def _get_item_by_name(self,itemName):
        for item in self.equipped_items:
            if item.name == itemName:
                return item
        print(f"Couldn't find {itemName} in equipped items")
        return None
    def perform_attack(self,target,item=None):
        if not isinstance(item,Item):
            item = self._get_item_by_name(item)
        attack = WeaponAttack(self,target,"1d8",item=item)
        attack.roll_to_hit()
        attackData={"event_type":"attack",
                    "attack":attack,
                    "attacker":self,
                    "target":target,
                    "data":attack.result}
        self.event_manager.broadcast("attack",attackData)
        print(attack.result)
        if attack.result['hit']:
            attack.roll_damage()
            self.event_manager.broadcast("damage",attackData)
        return attack
    def observe_attack(self, data):
        """Called whenever *any* creature attacks"""
        attacker = data["attacker"]
        target = data["target"]

        # Don't report if I'm the one attacking
        if attacker is not self:
            print(f"{self.name} sees {attacker.name} attack {target.name}!")
