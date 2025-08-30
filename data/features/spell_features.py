from data.features.base import Feature

class HellishRebuke(Feature):
    name = "Hellish Rebuke"
    EVENT_MAP = {"damage":"on_damage"}
    def on_damage(self,data):
        if data['target'] == self.owner and self.owner.actions.reactions:
            self.owner.actions.use_reaction()
            print(f"{self.owner.name} Uses Hellish Rebuke on {data['attacker'].name}")
        #if data['target'] == self.owner and self.owner.actions