import random
from data.features.base import Feature


class DreadAmbusher(Feature):
    """
    Gloom Stalker lv3. On the first turn of combat:
      - +10ft movement (once only)
      - One extra attack granted into the pool
      - That extra attack deals +1d8 damage on hit

    Uses a _last_granted_round guard so multiple TurnStarted broadcasts
    in round 1 (e.g. from initiative setup) don't stack the bonus.
    """
    name = "Dread Ambusher"
    EVENT_MAP = {
        "TurnStarted": "on_turn_started",
        "attack":      "on_attack",
        "damage":      "on_damage",
    }

    def __init__(self):
        super().__init__()
        self._last_granted_round = -1   # round we last gave the bonus
        self._bonus_active       = False # True while bonus attack is in pool

    def on_turn_started(self, ctx):
        creature  = ctx.get("creature")
        round_num = ctx.get("round", 1)

        # Only trigger for our owner, only on round 1, only once per round
        if creature is not self.owner:
            return
        if round_num != 1:
            return
        if self._last_granted_round == round_num:
            return   # already granted this round — don't double-stack

        self._last_granted_round = round_num
        self._bonus_active       = True

        # +10ft speed (once)
        self.owner.speed += 10
        print(f"  {self.owner.name}: Dread Ambusher — +10ft speed this turn")

        # Grant the bonus attack into the pool
        self.owner.actions.grant_temp_extra_attack()
        print(f"  {self.owner.name}: Dread Ambusher — extra attack this turn")

    def on_attack(self, data):
        if not self._bonus_active:
            return
        attacker = data.get("attacker")
        if attacker is not self.owner:
            return
        # Tag the attack that uses the last extra_attack charge
        # (remaining == 0 means this is the charge just consumed)
        if self.owner.actions.remaining_extra_attacks == 0:
            attack = data.get("attack")
            if attack:
                attack.tags.add("dread_ambusher_bonus")
            self._bonus_active = False   # consumed

    def on_damage(self, data):
        attack = data.get("attack")
        if not attack:
            return
        if "dread_ambusher_bonus" in attack.tags and attack.result.get("hit"):
            print(f"  {self.owner.name}: Dread Ambusher +1d8 damage!")
            attack.extra_dice.append((1, 8))


class FavoredFoe(Feature):
    name = "Favored Foe"
    EVENT_MAP = {
        "attack_resolved": "on_attack_resolved",
        "TurnStarted":     "on_turn_started",
    }

    def on_attack(self, data):
        if data["attacker"] is not self.owner:
            return
        if not self.owner.concentration or self.owner.concentration == "Favored Foe":
            attack = data["attack"]
            attack.tags.add("favored_foe")
            self.owner.concentration = "Favored Foe"

    def on_damage(self, data):
        if data["attacker"] is not self.owner:
            return
        if "favored_foe" not in data["attack"].tags:
            return
        ranger_level = next(
            (lvl for cls, lvl in self.owner.classes if cls == "Ranger"), 1
        )
        extra = "1d4" if ranger_level <= 5 else "1d6" if ranger_level <= 13 else "1d8"
        print(f"  Favored Foe adding {extra}")


class ExtraAttack(Feature):
    """
    Grants one additional attack when the Attack action is taken.
    Sets extra_attacks = 1 on the creature's ActionTracker permanently.
    """
    name = "Extra Attack"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.extra_attacks           = 1
        owner.actions.remaining_extra_attacks = 1
        print(f"  {owner.name} gains Extra Attack")
