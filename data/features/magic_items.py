from data.features.base import Feature
class BracersOfArchery(Feature):
    name = "Bracers Of Archery"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def on_attack_resolved(self, data):
        if data["attacker"] == self.owner and data.get("weapon") == "ranged":
            data["damage"] += 2
            print(f"{self.owner.name}'s Bracers add +2 damage!")