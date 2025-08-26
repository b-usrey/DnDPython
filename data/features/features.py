from core.attack import WeaponAttack
from pdb import set_trace as S
class Feature:
    """Base class for all character features with auto-registry."""
    REGISTRY = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically register subclasses when defined."""
        super().__init_subclass__(**kwargs)
        # Register by class name (e.g. "Sharpshooter") 
        # and by the 'name' attribute if it exists
        if hasattr(cls, "name"):
            Feature.REGISTRY[cls.name] = cls
        Feature.REGISTRY[cls.__name__] = cls

    def __init__(self, name=None):
        self.name = name or self.__class__.__name__

    # Hooks
    def on_attack(self, attack):
        """Called when attack roll happens."""
        pass

    def on_damage(self, attack):
        """Called when damage is calculated."""
        pass

    def on_turn_start(self, context=None):
        """Called at the start of the character's turn."""
        pass

class Sharpshooter(Feature):
    name = "Sharpshooter"

    def __init__(self):
        super().__init__(Sharpshooter.name)

    def on_attack(self, attack):
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10
class Archery(Feature):
    name = "Archery"
    def __init__(self):
        super().__init__(Archery.name)
    def on_attack(self,attack):
        if isinstance(attack,WeaponAttack):
            attack.to_hit_mod += 2

class DreadAmbusher(Feature):
    name = "Dread Ambusher"
    def __init__(self):
        super().__init__(DreadAmbusher.name)
        self.first_turn_active = True
        self.extra_attack_used = False

    def on_turn_start(self, context):
        # context could include { "creature": Creature, "turn_number": int }
        creature = context.get("creature")
        turn_number = context.get("turn_number")

        if turn_number == 1:  # First turn only
            print(f"{creature.name} gains +10 movement from Dread Ambusher!")
            creature.speed += 10
            self.first_turn_active = True
            self.extra_attack_used = False
        else:
            self.first_turn_active = False

    def on_attack(self, attack):
        """
        Triggered whenever the creature makes an attack.
        Attack object could carry metadata like 'is_bonus_attack'.
        """
        if not isinstance(attack, WeaponAttack):
            return

        if self.first_turn_active and not self.extra_attack_used:
            # Flag this attack as the Dread Ambusher bonus attack
            #attack.tags.add("dread_ambusher_bonus")
            self.extra_attack_used = True

    def on_damage(self, attack):
        """
        Add 1d8 damage if the flagged bonus attack hits.
        """
        if "dread_ambusher_bonus" in getattr(attack, "tags", []):
            if attack.result.get("hit", False):
                print("Dread Ambusher adds +1d8 damage!")
                attack.extra_damage_die.append((1, 8))     
class FavoredFoe(Feature):
    name = "Favored Foe"

    def __init__(self, diceType="d6"):
        super().__init__(FavoredFoe.name)
        self.diceType = diceType
        self.used_this_turn = False
        self.marked_target = None

    def mark_target(self, target):
        self.marked_target = target

    def on_damage(self, attack):
        if (
            attack.target == self.marked_target
            and not self.used_this_turn
            and attack.result.get("hit", False)
        ):
            # Append tuple: (num dice, die size)
            attack.extra_damage_die.append((1, 6))
            self.used_this_turn = True

    def on_turn_start(self, context=None):
        self.used_this_turn = False

class BracersOfArchery(Feature):
    name = "Bracers Of Archery"
    def __init__(self):
        super().__init__(BracersOfArchery.name)
    def on_damage(self,attack):
        S()
