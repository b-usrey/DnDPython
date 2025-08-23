import random

class Attack:
    def __init__(self, name, damage_dice, attack_bonus=0, attack_type="melee", effects=None):
        """
        damage_dice: list of (num_dice, die_size, damage_type) tuples, e.g. [(1, 8, "slashing"), (2, 6, "fire")]
        effects: list of functions or callables that apply additional effects on hit (e.g. sneak attack)
        """
        self.name = name
        self.damage_dice = damage_dice
        self.attack_bonus = attack_bonus
        self.attack_type = attack_type
        self.effects = effects if effects else []

    def roll_to_hit(self, attacker, advantage=False, disadvantage=False):
        """Handles rolling to hit with modifiers."""
        roll1 = random.randint(1, 20)
        roll2 = random.randint(1, 20)

        if advantage and disadvantage:
            d20 = roll1
        elif advantage:
            d20 = max(roll1, roll2)
        elif disadvantage:
            d20 = min(roll1, roll2)
        else:
            d20 = roll1

        # proficiency + stat bonus + weapon bonus + attack bonus
        total = d20 + attacker.get_attack_mod(self.attack_type) + self.attack_bonus
        eventData = {
            "attacker":attacker,
            "roll":d20,
            "total":total
        }
        attacker.event_manager.broadcast("attack-declared",eventData)
        return d20, total

    def roll_damage(self, attacker, target, crit=False):
        """Handles rolling damage (with crit doubling dice)."""
        damage_results = []
        for num, die, dmg_type in self.damage_dice:
            rolls = [random.randint(1, die) for _ in range(num * (2 if crit else 1))]
            dmg_total = sum(rolls) + attacker.get_damage_mod(self.attack_type)
            damage_results.append((dmg_total, dmg_type))
        return damage_results

    def perform(self, attacker, target, critRange=20, advantage=False, disadvantage=False):
        """Perform the full attack sequence."""
        d20, total_attack = self.roll_to_hit(attacker, target, advantage, disadvantage)
        crit = (d20 >= critRange)

        if total_attack >= target.ac or crit:
            damage_chunks = self.roll_damage(attacker, target, crit)
            total_damage = 0

            for dmg, dmg_type in damage_chunks:
                reduced = target.apply_damage(dmg, dmg_type)  # handle resistances
                total_damage += reduced

            print(f"{attacker.name} hits {target.name} with {self.name} for {total_damage} damage! (roll: {d20}+mods)")
            
            # Apply extra effects
            for effect in self.effects:
                effect(attacker, target)

            return total_damage
        else:
            print(f"{attacker.name} misses {target.name} with {self.name}. (roll: {d20}+mods)")
            return 0

