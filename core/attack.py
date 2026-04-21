from abc import ABC, abstractmethod
import random

VERBOSE = True


class Attack(ABC):
    def __init__(self, attacker, target, base_dice, item=None, range=False):
        self.attacker   = attacker
        self.target     = target
        self.base_dice  = (int(base_dice.split("d")[0]), int(base_dice.split("d")[1]))
        self.to_hit_mod = 0
        self.damage_mod = 0
        self.range      = range
        self.tags       = set()
        if item and item.item_type == "weapon":
            self.base_dice  = (int(item.damage_die.split("d")[0]), int(item.damage_die.split("d")[1]))
            self.to_hit_mod = attacker.statblock.mods[item.ability] + item.attack_bonus + attacker.proficiency
            self.damage_mod = attacker.statblock.mods[item.ability] + item.damage_bonus
            if item.attack_type == "range":
                self.range = True
        self.extra_dice = []
        self.advantage  = False
        self.critical   = False
        self.result     = {}

    @abstractmethod
    def roll_to_hit(self): pass

    @abstractmethod
    def roll_damage(self): pass

    @abstractmethod
    def declare_attack(self): pass


class WeaponAttack(Attack):
    """
    Five-phase attack pipeline, each mapped to a D&D 5e timing phrase:

    Phase 1  "attack"        — "When you make an attack roll"
                               Modify to_hit_mod, add tags, set advantage.
                               e.g. Archery +2, Sharpshooter -5/+10
             roll_to_hit()

    Phase 2  "hit"           — "When you hit"
                               Hit is confirmed. Add extra_dice, apply
                               per-hit bonuses BEFORE damage is rolled.
                               e.g. DreadAmbusher +1d8, FavoredFoe bonus,
                                    Sneak Attack, Hunter's Mark

    Phase 3  "damage"        — "When you deal damage"
                               Last-chance damage modifications.
                               creature._on_damage_event is subscribed here
                               and calls roll_damage() + take_damage().

    Phase 4  "damage_dealt"  — "When you take damage"
                               Target has taken damage; reactions that
                               respond to being hit fire here.
                               e.g. Hellish Rebuke, Absorb Elements

    Phase 5  "attack_resolved" — Full resolution complete.
                               Cleanup, logging, post-attack effects.
                               e.g. Shield of Faith expires, BracersOfArchery
    """

    def declare_attack(self):
        attack_data = {
            "event_type": "attack",
            "attack":     self,
            "attacker":   self.attacker,
            "target":     self.target,
        }

        # Phase 1 — announce attack (features may modify to_hit_mod, add tags, etc.)
        self.attacker.event_manager.broadcast("attack", attack_data)
        self.roll_to_hit()
        attack_data["results"] = self.result

        if self.result["hit"]:
            print(f"{self.attacker.name} hit {self.target.name}  "
                  f"(roll {self.result['hit_roll']} + mod = {self.result['attack_total']} vs AC {self.target.ac})")
            # Phase 2 — damage modifiers (features may add extra_dice, etc.)
            self.attacker.event_manager.broadcast("damage", attack_data)
            # Phase 3 — roll and apply damage (target._on_damage_event fires here)
            self.roll_damage()
        else:
            print(f"{self.attacker.name} missed {self.target.name}  "
                  f"(roll {self.result['hit_roll']} + mod = {self.result['attack_total']} vs AC {self.target.ac})")

        # Phase 4 — attack fully resolved, reactions fire here.
        self.attacker.event_manager.broadcast("attack_resolved", attack_data)

    def roll_to_hit(self):
        d20 = random.randint(1, 20)
        if self.advantage:
            d20 = max(random.randint(1, 20), d20)
        total          = d20 + self.to_hit_mod
        self.critical  = (d20 == 20)
        self.result["hit_roll"]      = d20
        self.result["attack_total"]  = total
        self.result["hit"]           = total >= self.target.ac
        return self.result

    def roll_damage(self):
        if not self.result.get("hit", False):
            self.result["damage"] = 0
            return 0
        num, sides = self.base_dice
        damage = sum(random.randint(1, sides) for _ in range(num))
        if self.critical:
            damage *= 2
        for num, sides in self.extra_dice:
            damage += sum(random.randint(1, sides) for _ in range(num))
        damage += self.damage_mod
        self.result["damage"] = damage
        return damage
