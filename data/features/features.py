from core.attack import WeaponAttack
from pdb import set_trace as S

class Feature:
    """Base class for all character features."""
    def __init__(self, name):
        self.name = name

    def on_attack(self, context):
        """Called when attack roll happens."""
        pass

    def on_damage(self, context):
        """Called when damage is calculated."""
        pass

    def on_turn_start(self, context):
        """Called at the start of the character's turn."""
        pass

class Sharpshooter(Feature):
    def on_attack(self, attack):
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
