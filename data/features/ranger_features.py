from data.features.base import Feature
from pdb import set_trace as S
class DreadAmbusher(Feature):
    name = "Dread Ambusher"
    EVENT_MAP = {"turn_start": "on_turn_start", "attack": "on_attack", "damage": "on_damage"}

    def __init__(self):
        super().__init__()
        self.first_turn_active = True
        self.extra_attack_used = False

    def on_turn_start(self, ctx):
        creature, turn = ctx["creature"], ctx["turn_number"]
        if turn == 1:
            print(f"{creature.name} gains +10 movement from Dread Ambusher!")
            creature.speed += 10
            self.first_turn_active, self.extra_attack_used = True, False
        else:
            self.first_turn_active = False

    def on_attack(self, attack):
        attack = attack['attack']
        if self.first_turn_active and not self.extra_attack_used:
            attack.tags.add("dread_ambusher_bonus")
            self.extra_attack_used = True

    def on_damage(self, attack):
        if "dread_ambusher_bonus" in getattr(attack, "tags", []):
            if attack.result.get("hit", False):
                print("Dread Ambusher adds +1d8 damage!")
                attack.extra_damage_die.append((1, 8))
class FavoredFoe(Feature):
    name = "Favored Foe"
    EVENT_MAP = {
        "attack": "on_attack",
        "damage": "on_damage",
    }
    def on_attack(self, data):
        if data["attacker"] == self.owner and (not self.owner.concentration or self.owner.concentration=="Favored Foe"): 
            attack = data['attack']
            attack.tags.add("favored_foe")
            self.owner.concentration = "Favored Foe"
            #print(f"{self.owner} applies Favored Foe! Bonus is now {data['bonus']}")
    def on_damage(self,data):
        if data["attacker"] == self.owner and 'favored_foe' in data['attack'].tags:
            rangerLevel = [cls[1] for cls in self.owner.classes if cls[0] == "Ranger"][0]
            extraDamage = "1d4"
            if rangerLevel >5:
                extraDamage = "1d6"
            if rangerLevel > 13:
                extraDamage = "1d8"
            print("Favored foe is applying ",extraDamage)
        
