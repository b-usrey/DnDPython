import random

class InitiativeManager:
    def __init__(self, creatures, eventManager):
        """
        creatures: list of Creature objects
        eventManager: shared EventManager instance
        """
        self.creatures = creatures
        self.eventManager = eventManager
        self.initiative_order = []
        self.current_index = 0
        self.round = 1

    def roll_initiative(self):
        """
        Rolls initiative for all creatures and sorts them.
        """
        self.initiative_order = []
        for c in self.creatures:
            roll = c.roll_initiative()
            self.initiative_order.append((roll, c))
        # Sort descending by roll
        self.initiative_order.sort(key=lambda x: x[0], reverse=True)
        self.current_index = 0
        context = {"order":self.initiative_order}

        # Broadcast initiative order
        self.eventManager.broadcast("InitiativeRolled", context)

    def current_creature(self):
        return self.initiative_order[self.current_index][1]

    def start_combat(self):
        self.round = 1
        self.eventManager.broadcast("CombatStarted", {"round": self.round})
        self.start_turn()

    def start_turn(self):
        creature = self.current_creature()
        creature.actions.reset()
        self.eventManager.broadcast("TurnStarted", {"round": self.round, "creature": creature})
        return creature

    def end_turn(self):
        creature = self.current_creature()
        self.eventManager.broadcast("TurnEnded", {"round": self.round, "creature": creature})

        self.current_index += 1
        if self.current_index >= len(self.initiative_order):
            # End of round
            self.current_index = 0
            self.round += 1
            self.eventManager.broadcast("RoundStarted", {"round": self.round})

        return self.start_turn()
