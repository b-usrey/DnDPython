from data.features.base import Feature
from core.attack import WeaponAttack

class Archery(Feature):
    """
    +2 to attack rolls made with ranged weapons.

    "attack" fires on the shared event bus for every attack in the whole
    combat, not just this owner's -- without the attacker check below,
    the +2 (and the "archery" tag) was silently applying to every attack
    by everyone, allies and enemies alike, any time an archer was in the
    fight at all.
    """
    name = "Archery"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, context):
        if context.get('attacker') is not self.owner:
            return
        attack = context['attack']
        if isinstance(attack, WeaponAttack) and attack.range:
            attack.to_hit_mod += 2
            attack.tags.add("archery")