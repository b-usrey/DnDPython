"""
data/features/fighter_features.py

Fighter class features. Add to data/classes/fighter.json features list.
"""
from data.features.base import Feature


class ActionSurge(Feature):
    """
    Fighter lv2. Once per short rest (once per combat for now),
    take one additional action on your turn.

    Implementation: sets max_action_surges = 1 on ActionTracker.
    CombatManager checks can_surge and calls use_action_surge() which
    grants an extra action and resets the extra attack pool.
    The AI uses it automatically when it still has a target and no actions.
    """
    name = "Action Surge"

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.actions.max_action_surges  = 1
        owner.actions.remaining_surges   = 1
        print(f"  {owner.name} gains Action Surge")


class SecondWind(Feature):
    """
    Fighter lv1. Bonus action: regain 1d10 + fighter level HP once per rest.
    Placeholder — triggers automatically when HP drops below 50% on turn start.
    """
    name = "Second Wind"
    EVENT_MAP = {"TurnStarted": "on_turn_started"}

    def __init__(self):
        super().__init__()
        self._used = False

    def on_turn_started(self, ctx):
        creature = ctx.get("creature")
        if creature is not self.owner:
            return
        if self._used:
            return
        hp_frac = creature.hp / max(creature.max_hp, 1)
        if hp_frac < 0.5 and creature.actions.use_bonus_action():
            import random
            # Estimate fighter level from classes list
            fighter_level = next(
                (lvl for cls, lvl in getattr(creature, "classes", [])
                 if cls == "Fighter"), 1
            )
            healed = random.randint(1, 10) + fighter_level
            creature.heal(healed)
            self._used = True
            print(f"  {creature.name} uses Second Wind — heals {healed} HP "
                  f"({creature.hp}/{creature.max_hp})")