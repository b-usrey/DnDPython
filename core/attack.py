from abc import ABC, abstractmethod
import random
from pdb import set_trace as S

class Attack(ABC):
    def __init__(self, attacker, target, base_dice, damage_type="slashing"):
        self.attacker = attacker
        self.target = target
        self.base_dice = base_dice   # (num, sides)
        self.damage_type = damage_type

        # context-like modifiers
        self.to_hit_mod = 0
        self.damage_mod = 0
        self.extra_dice = []
        self.advantage = False
        self.critical = False
        self.result = {}

    @abstractmethod
    def roll_to_hit(self):
        pass

    @abstractmethod
    def roll_damage(self):
        pass

class WeaponAttack(Attack):
    def roll_to_hit(self):
        d20 = random.randint(1, 20)
        # check advantage (roll twice, take higher)
        if self.advantage:
            d20 = max(random.randint(1, 20), d20)

        total = d20 + self.to_hit_mod
        self.critical = (d20 == 20)

        self.result["hit_roll"] = d20
        self.result["attack_total"] = total
        self.result["hit"] = total >= self.target.ac

        return self.result["hit"]

    def roll_damage(self):
        if not self.result.get("hit", False):
            self.result["damage"] = 0
            return 0

        num, sides = self.base_dice
        damage = sum(random.randint(1, sides) for _ in range(num))

        if self.critical:
            damage *= 2  # simple crit rule

        for num, sides in self.extra_dice:
            damage += sum(random.randint(1, sides) for _ in range(num))

        damage += self.damage_mod

        self.result["damage"] = damage
        return damage



