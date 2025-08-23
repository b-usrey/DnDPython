# -*- coding: utf-8 -*-
"""
Created on Tue Aug 19 19:05:41 2025

@author: Bryce
"""
from pdb import set_trace as S
import math
from core.creature import Creature
FLAG_IS_OMNIPOTENT = True
class PlayerCharacter(Creature):
    def __init__(self, name, class_levels,stats,event,feats=[],team="blue"):
        """
        class_levels: list of tuples -> [(class_data, level), (class_data, level), ...]
        """
        self.attacks = []
        self.hp = 0
        self.update_items = False
        self.feats = feats
        self.class_levels = class_levels
        self.total_level=sum([lvl for _,lvl in class_levels])
        self.primary_class = class_levels[0][0]
        self.class_name = self.primary_class['name']
        self.prof_mod = (self.total_level-1)//4+2
        for save in self.primary_class['savingThrow']:
            setattr(self,save+"_saveProf",self.prof_mod)
        super().__init__(name, 0, self.primary_class["base_ac"],stats,event,proficiency=self.prof_mod)
        self.team=team
        self.calculate_hp()
        self.features = []
        self.spells = {}
        for cls, lvl in class_levels:
            self.features.extend(cls["features"])
            for spell_level, spell_list in cls["spells"].items():
                if spell_level not in self.spells:
                    self.spells[spell_level] = []
                self.spells[spell_level].extend(spell_list)
    def calculate_hp(self):
        toughMod = 2 if "tough" in self.feats else 0
        for i, (cls, lvl) in enumerate(self.class_levels):
            if i == 0:
                self.hp += cls["hit_die"] + (lvl-1)*math.ceil(cls['hit_die']/2)+lvl*self.statblock.mods['Con'] + toughMod*lvl #Assumption only breaks when you get a wizard with a -4 con Mod
            else:
                self.hp += (lvl)*math.ceil(cls['hit_die']/2)+lvl*self.statblocks.mods['Con'] + toughMod*lvl

    def add_item(self,item):
        self.inventory.append(item)
    def get_best_ac(self):
        armors=[item for item in self.inventory if item.item_type == "armor"]
        self.dex_ac_cap = 2 if "medium armor master" not in self.feats else 3
        newArmor = None
        shieldMod = 0
        for armor in armors:
            acMod = 0
            if armor.armor_type == "shield":
                shieldMod = armor.base_ac+armor.magic_bonus
            if armor.armor_type == "light":
                acMod = self.statblock.mods['Dex']
            if armor.armor_type == "medium":
                acMod = min(self.dex_ac_cap,self.statblock.mods['Dex'])    
            ac = armor.base_ac+acMod+armor.magic_bonus
            if ac > self.ac:
                newArmor = armor
                self.ac = ac
        self.ac += shieldMod
        if newArmor:
            print(f"{self.name} is now using {newArmor.name} armor")
    def get_attack(self,target=None):
        targetAC = 10
        for attackOption in self.attacks:
            if target and FLAG_IS_OMNIPOTENT:
                targetAC = target.ac
                S()