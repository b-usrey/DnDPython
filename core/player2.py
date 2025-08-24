import os
FOLDER_PATH= os.sep.join(os.path.abspath(__file__).split(os.sep)[:-1])
from pdb import set_trace as S
import math
from core.creature import Creature
import json
FLAG_IS_OMNIPOTENT = True
class PlayerCharacter(Creature):
    def __init__(self, name, classes,subclasses,stats,event,feats=[],team="blue"):
        """
        name: Character name (string)
        class_levels: list of tuples -> [(className, level), (className, level), ...]
        sublcasses: dict {className:subclassName,...}
        """
        self.attacks = []
        self.hp = 0
        self.update_items = False
        self.feats = feats
        self.features = []
        self.total_level = sum([cls[1] for cls in classes])
        self.prof_mod = (self.total_level-1)//4+2
        super().__init__(name, 0, 0,stats,event,proficiency=self.prof_mod)
        for idx,cls in enumerate(classes):
            subclass=None
            if cls[0] in subclasses:
                subclass = subclasses[cls[0]]
            class_data = self.get_class_features(cls[0],cls[1],os.path.join(FOLDER_PATH,"..","data","classes"),subclass=subclass)
            self.hp += (class_data['hit_die']/2+1+self.statblock.mods['Con'])*cls[1]+class_data['hit_die']/2-1 if idx == 0 else 0
        self.team=team
        self.spells = {}
    def get_class_features(self, class_name,level,data_folder,subclass=None):
        """
        class_name: Name of class you want to add, should be coming from character creation
        """
        file_path = os.path.join(data_folder,f"{class_name.lower()}.json")
        with open(file_path) as f:
            class_data = json.load(f)
        if subclass:
            subclass_data = None
            if subclass.replace(" ","").lower() in class_data['subclasses']:
                subclass_data = class_data['subclasses'][subclass.replace(" ","").lower()]
            else:
                print(f"Couldn't find {subclass} in {class_name} data")
        for lvl in range(level):
            lvl += 1
            if str(lvl) in class_data['features_by_level']:
                for feat in class_data['features_by_level'][str(lvl)]:
                    pass #self.features.append(feat['name'])
            if subclass_data and str(lvl) in subclass_data['features_by_level']:
                for sub_feat in subclass_data['features_by_level'][str(lvl)]:
                    pass #self.features.append(sub_feat['name'])
        return class_data

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