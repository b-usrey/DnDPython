class CreatureObserver:
    def __init__(self, creature):
        self.creature = creature

    def notify(self, event_type, data):
        """React to events relevant to this creature."""
        if event_type == "attack_declared":
            self.on_attack_declared(data)
        elif event_type == "attack_hits":
            self.on_attack_hits(data)

    def on_attack_declared(self, data):
        # Example: creature becomes aware it’s being targeted
        if data["target"] == self.creature:
            print(f"{self.creature.name} notices {data['attacker'].name} is attacking them.")

    def on_attack_hits(self, data):
        # Example: creature might want to react (e.g. Shield spell)
        if data["target"] == self.creature:
            print(f"{self.creature.name} has an opportunity to react before damage is applied.")
