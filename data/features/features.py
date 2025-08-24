from core.attack import WeaponAttack

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


# --------------------
# Example Features
# --------------------

class Sharpshooter(Feature):
    name = "Sharpshooter"

    def __init__(self):
        super().__init__(Sharpshooter.name)

    def on_attack(self, attack):
        if isinstance(attack, WeaponAttack):
            attack.to_hit_mod -= 5
            attack.damage_mod += 10


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

