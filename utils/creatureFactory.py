from core.creature import Creature
from core.attack import Attack
class CreatureFactory:
    def __init__(self):
        # Keep track of all spawned creatures
        self.registry = {}

    def create(self, template):
        creature = Creature(
            name=template["name"],
            hp=template["hp"],
            ac=template["ac"],
            stats=template["stats"],
            proficiency=template.get("proficiency", 2)
        )
        # Add attacks
        for atk in template.get("attacks", []):
            creature.attacks.append(
                Attack(atk["name"], atk["attack_bonus"], atk["damage_die"], atk.get("damage_mod", 0))
            )

        # Register creature by unique ID
        self.registry[creature.ID] = creature
        return creature

    def get_by_id(self, creature_id):
        return self.registry.get(creature_id, None)

    def get_by_name(self, name):
        # Returns list of creatures matching that name
        return [c for c in self.registry.values() if c.name == name]

    def remove(self, creature):
        # Optional: remove creature when it dies
        if creature.id in self.registry:
            del self.registry[creature.id]
