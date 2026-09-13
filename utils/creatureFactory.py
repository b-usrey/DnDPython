from collections import defaultdict
from core.creature import Creature
from data.features.base import Feature
# Importing the module registers every monster ability in Feature.REGISTRY.
from data.features.monster_features import MonsterRiders, MonsterAction


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

        self._apply_monster_template(creature, template)

        self.registry[creature.ID] = creature
        return creature

    # ------------------------------------------------------------------
    # Monster stat-block fields beyond HP / AC / attacks. Every one is
    # optional, so older templates and homebrew entries still load. See the
    # schema in data/monsters/monsters.py.
    # ------------------------------------------------------------------

    def _apply_monster_template(self, creature, template):
        creature._template     = template
        creature.creature_type = template.get("type")
        creature.cr            = template.get("cr")
        creature.speed         = template.get("speed", creature.speed)
        if template.get("flying"):
            creature.ignore_difficult_terrain = True

        creature.resistances.update(template.get("damage_resistances", []))
        creature.immunities.update(template.get("damage_immunities", []))
        creature.vulnerabilities.update(template.get("damage_vulnerabilities", []))
        if template.get("nonmagical_physical"):
            creature.nonmagical_physical = template["nonmagical_physical"]
        creature.condition_immunities.update(template.get("condition_immunities", []))

        for trait in template.get("traits", []):
            if isinstance(trait, str):
                self._attach(creature, trait, {})
            else:
                self._attach(creature, trait.get("name"), trait)

        actions = template.get("actions", [])
        all_attacks = list(template.get("attacks", [])) + [
            a.get("attack") or {} for a in actions]
        if any(a.get("on_hit") for a in all_attacks):
            self._attach_instance(creature, MonsterRiders(), {})
        for action in actions:
            self._attach_instance(creature, MonsterAction(), action)

        if template.get("spellcasting"):
            self._attach(creature, "Monster Spellcasting", template["spellcasting"])
        if template.get("legendary_resistance"):
            self._attach(creature, "Legendary Resistance",
                         {"uses": template["legendary_resistance"]})
        if template.get("legendary_actions"):
            self._attach(creature, "Legendary Actions", template["legendary_actions"])

    @staticmethod
    def _attach_instance(creature, feature, params):
        creature.features.append(feature)
        feature.attach(creature, creature.event_manager)
        if hasattr(feature, "configure"):
            feature.configure(params)
        return feature

    def _attach(self, creature, name, params):
        cls = Feature.REGISTRY.get(name) if name else None
        if cls is None:
            print(f"[warn] Monster ability '{name}' not found in registry")
            return None
        return self._attach_instance(creature, cls(), params)

    def get_by_id(self, creature_id):
        return self.registry.get(creature_id, None)

    def get_by_name(self, name):
        return [c for c in self.registry.values() if c.name == name]

    def remove(self, creature):
        if creature.ID in self.registry:
            del self.registry[creature.ID]
