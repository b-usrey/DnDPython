import random
from data.features.base import Feature
from core.saving_throw import CommonSaves


class HellishRebuke(Feature):
    """
    Reaction: when the owner takes damage from a creature that hit them,
    the attacker must make a DEX save (DC 11) or take 2d10 fire damage
    (half on success).
    """
    name = "Hellish Rebuke"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    SAVE_DC = 11

    def on_attack_resolved(self, data):
        target   = data.get("target")
        attacker = data.get("attack") and data["attack"].attacker
        attack   = data.get("attack")

        if target is not self.owner:
            return
        if not attack or not attack.result.get("hit", False):
            return
        if not self.owner.actions.use_reaction():
            return

        damage = sum(random.randint(1, 10) for _ in range(2))
        real_attacker = data.get("attacker")

        print(
            f"  {self.owner.name} uses Hellish Rebuke on "
            f"{real_attacker.name}! ({damage} fire damage, DEX save DC {self.SAVE_DC})"
        )

        CommonSaves.dex_half(
            caster      = self.owner,
            target      = real_attacker,
            dc          = self.SAVE_DC,
            damage      = damage,
            damage_type = "fire",
        )