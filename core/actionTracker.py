class ActionTracker:
    def __init__(self, extra_attacks=0, legendary_actions=0):
        self.max_actions = 1
        self.max_bonus_actions = 1
        self.max_reactions = 1
        self.extra_attacks = extra_attacks
        self.legendary_actions = legendary_actions
        self.reset()

    def reset(self):
        self.actions = self.max_actions
        self.bonus_actions = self.max_bonus_actions
        self.reactions = self.max_reactions
        self.remaining_extra_attacks = self.extra_attacks
        self.remaining_legendary = self.legendary_actions

    def use_action(self):
        if self.actions > 0:
            self.actions -= 1
            return True
        return False

    def use_bonus_action(self):
        if self.bonus_actions > 0:
            self.bonus_actions -= 1
            return True
        return False

    def use_reaction(self):
        if self.reactions > 0:
            self.reactions -= 1
            return True
        return False

    def use_extra_attack(self):
        if self.remaining_extra_attacks > 0:
            self.remaining_extra_attacks -= 1
            return True
        return False

    def use_legendary_action(self):
        if self.remaining_legendary > 0:
            self.remaining_legendary -= 1
            return True
        return False

