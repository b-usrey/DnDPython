from data.features.base import Feature
from core.attack import WeaponAttack

class Archery(Feature):
    name = "Archery"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, context):
        attack = context['attack']
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod += 2
            attack.tags.add("archery")