from data.features.base import Feature
from core.attack import WeaponAttack


class Sharpshooter(Feature):
    """
    Feat. Before making a ranged weapon attack you can opt to take
    -5 to hit in exchange for +10 damage on a hit.

    Both the penalty and bonus are declared together in Phase 1 ("attack")
    since they are a package deal decided before the roll.

    The AI uses it when the target's HP is above SHARPSHOOTER_HP_THRESHOLD
    (default 15) — i.e. the +10 damage is a meaningful fraction of their
    remaining health, making the miss risk worthwhile.
    """
    name = "Sharpshooter"
    SHARPSHOOTER_HP_THRESHOLD = 15

    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        attack   = data.get("attack")
        attacker = data.get("attacker")
        target   = data.get("target")

        if attacker is not self.owner:
            return
        if not isinstance(attack, WeaponAttack) or not attack.range:
            return

        if getattr(target, "hp", 0) > self.SHARPSHOOTER_HP_THRESHOLD:
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
            attack.tags.add("sharpshooter")