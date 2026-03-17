import random
class CombatManager:
    def __init__(self, Initiative):
        """
        creatures: list of Creature instances
        factory: optional CreatureFactory (for lookups/registry)
        """
        self.initiative = Initiative
        #self.creatures = creatures[:]  # active creatures (will be pruned as they die)
        #self.round = 0
        #self.initiative_order = []
    