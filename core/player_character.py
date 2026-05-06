import os
FOLDER_PATH= os.sep.join(os.path.abspath(__file__).split(os.sep)[:-1])

import math
from core.creature import Creature
from data.features.base import Feature
import json
FLAG_IS_OMNIPOTENT = True
class PlayerCharacter(Creature):
    def __init__(self, name, classes,subclasses,stats,event,choices,feats=[],team="blue"):
        """
        name: Character name (string)
        class_levels: list of tuples -> [(className, level), (className, level), ...]
        sublcasses: dict {className:subclassName,...}
        stats: dict of stats
        event: EventManager for broadcasting and receiving messages
        choices: choies for character levels [("Ranger",2,"Fighting Style","Archery")]
        """
        self.attacks = []
        self.feats = []
        self.choices = choices
        self.hp = 0
        self.update_items = False
        self.total_level = sum([cls[1] for cls in classes])
        self.prof_mod = (self.total_level-1)//4+2
        self.classes = classes
        super().__init__(name, 0, 0, stats, event_manager=event, proficiency=self.prof_mod)
        for feat in feats:
            self.feats.append(feat)
            self._add_feature_by_name(feat)
        for idx,cls in enumerate(classes):
            subclass=None
            if cls[0] in subclasses:
                subclass = subclasses[cls[0]]
            class_data = self.get_class_features(cls[0],cls[1],os.path.join(FOLDER_PATH,"..","data","classes"),sub_class=subclass)
            self.hp += (class_data['hit_die']/2+1+self.statblock.mods['Con'])*cls[1]+class_data['hit_die']/2-1 if idx == 0 else 0
            # Wire saving throw proficiencies from class data into statblock
            for save_ability in class_data.get("saving_throws", []):
                from core.saving_throw import normalise_ability
                try:
                    key = normalise_ability(save_ability)
                    self.statblock.save_profs[key] = 1
                except ValueError:
                    pass
        self.team=team
        self.spells = {}
    
    def get_class_features(self, class_name,level,data_folder,sub_class=None):
        """
        class_name: Name of class you want to add, should be coming from character creation
        """
        file_path = os.path.join(data_folder,f"{class_name.lower()}.json")
        with open(file_path) as f:
            class_data = json.load(f)
        if sub_class:
            subclass_data = None
            if sub_class.replace(" ","").lower() in class_data['subclasses']:
                subclass_data = class_data['subclasses'][sub_class.replace(" ","").lower()]
            else:
                print(f"Couldn't find {sub_class} in {class_name} data")
        for lvl in range(level):
            lvl += 1
            if str(lvl) in class_data['features_by_level']:
                for feat in class_data['features_by_level'][str(lvl)]:
                    featName = feat['name']
                    if "options" in feat:
                        for opt in feat['options']:
                            if [class_name,lvl,feat['name'],opt] in self.choices:
                                featName = opt
                    self._add_feature_by_name(featName)
            if subclass_data and str(lvl) in subclass_data['features_by_level']:
                choiceFound = False
                for sub_feat in subclass_data['features_by_level'][str(lvl)]:
                    featName = sub_feat['name']
                    if "options" in feat:
                        for opt in feat['options']:
                            if [sub_class,lvl,sub_feat['name'],opt] in self.choices:
                                featName = opt
                                choiceFound = True
                    self._add_feature_by_name(featName)
        return class_data

    def add_item(self,item):
        self.inventory.append(item)
    # ------------------------------------------------------------------
    # AC calculation
    # ------------------------------------------------------------------
    #
    def setup_ac(self) -> None:
        """
        Called once at combat setup (by ScenarioLoader after equipping).
        Reads equipped body armour and shield; stores their AC contributions
        in _armour_ac and _shield_ac. Does not touch _misc_ac so bonuses
        from features that attached before this call (Ring of Protection, etc.)
        are preserved. compute_ac/apply_misc_ac/apply_shield are inherited
        from Creature.
        """
        self.dex_ac_cap = 2 if "medium armor master" not in self.feats else 3

        # Reset armour and shield — keep existing _misc_ac
        self._armour_ac = 10 + self.statblock.mods["Dex"]  # unarmoured baseline
        self._shield_ac = 0

        best_armour = None

        for item in self.equipped_items:
            if item.item_type != "armor":
                continue

            magic      = getattr(item, "magic_bonus", 0) + getattr(item, "ac_bonus", 0)
            armor_type = getattr(item, "armor_type", "")

            if armor_type == "shield":
                self._shield_ac = getattr(item, "base_ac", 2) + magic
                continue

            if armor_type == "light":
                dex_mod = self.statblock.mods["Dex"]
            elif armor_type == "medium":
                dex_mod = min(self.dex_ac_cap, self.statblock.mods["Dex"])
            else:
                dex_mod = 0   # heavy armour

            candidate = getattr(item, "base_ac", 10) + dex_mod + magic
            if candidate > self._armour_ac:
                self._armour_ac = candidate
                best_armour     = item

        self.compute_ac()
        if best_armour:
            print(f"  {self.name}: {best_armour.name} -> AC {self.ac}")

    def get_attack(self,target=None):
        targetAC = 10
        for attackOption in self.attacks:
            if target and FLAG_IS_OMNIPOTENT:
                targetAC = target.ac