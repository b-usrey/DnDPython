from data.features.base import Feature
from core.attack import WeaponAttack

class Sharpshooter(Feature):
    name = "Sharpshooter"
    EVENT_MAP = {"attack": "on_attack","damage":"on_damage"}
    def on_attack(self, data):
        attack = data['attack']
        if isinstance(attack, WeaponAttack) and attack.range and data['attacker'] == self.owner:
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
            attack.tags.add("sharpshooter")