from collections import defaultdict
from core.creature import Creature


class CreatureFactory:
    def __init__(self):
        self.registry = {}
        # Per-species counter so Goblin -> Goblin#1, Goblin#2, etc.
        self._species_counters = defaultdict(int)

    def create(self, template, observer):
        base_name = template["name"]
        self._species_counters[base_name] += 1
        unique_name = f"{base_name}#{self._species_counters[base_name]}"

        creature = Creature(
            name=unique_name,
            hp=template["hp"],
            ac=template["ac"],
            stats=template["stats"],
            proficiency=template.get("proficiency", 2),
            event_manager=observer,
        )

        # Multiattack: how many attacks this monster makes per Attack action
        # (e.g. a dragon's "makes three attacks"). Reuses the same
        # extra-attack mechanism PCs get from the Extra Attack feature --
        # CombatManager._do_attack_action()'s `while use_extra_attack()`
        # loop already handles firing the rest, unchanged. Defaults to 1
        # (no multiattack) for any template that doesn't specify it.
        multiattack = template.get("multiattack", 1)
        creature.actions.extra_attacks = max(0, multiattack - 1)
        creature.actions.remaining_extra_attacks = creature.actions.extra_attacks

        # Wire saving throw proficiencies
        from core.saving_throw import normalise_ability
        for save_ability in template.get("save_proficiencies", []):
            try:
                key = normalise_ability(save_ability)
                creature.statblock.save_profs[key] = 1
            except ValueError:
                pass

        if "features" in template:
            for feat in template["features"]:
                creature._add_feature_by_name(feat)

        self.registry[creature.ID] = creature
        return creature

    def get_by_id(self, creature_id):
        return self.registry.get(creature_id, None)

    def get_by_name(self, name):
        return [c for c in self.registry.values() if c.name == name]

    def remove(self, creature):
        if creature.ID in self.registry:
            del self.registry[creature.ID]
