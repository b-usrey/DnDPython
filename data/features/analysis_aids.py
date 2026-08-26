"""
data/features/analysis_aids.py

Not real 5e feats or class features -- small hooks that exist purely so the
webapp's build-comparison tools (e.g. the Builder's "Damage vs. Defense"
chart) can model a tactical situation without inventing a whole new scenario
mechanic for it. Attach by name via a player's "feats"/"features" list, same
as any other Feature, but keep these out of any UI that lists real feat
choices.
"""
from data.features.base import Feature


class ForceAdvantage(Feature):
    """
    Grants advantage on every attack roll the owner makes. Stands in for
    "attacking under favorable conditions" (flanking, Faerie Fire, an
    unseen attacker, etc.) without picking one specific source, since a
    build-comparison tool only cares about the resulting damage curve, not
    which of those caused it.
    """
    name = "Advantage (Test)"
    EVENT_MAP = {"attack": "on_attack"}

    def on_attack(self, data):
        if data.get("attacker") is not self.owner:
            return
        attack = data.get("attack")
        if attack is not None:
            attack.advantage = True
