from data.features.base import Feature
class BracersOfArchery(Feature):
    name = "Bracers Of Archery"
    EVENT_MAP = {"attack_resolved": "on_attack_resolved"}

    def on_attack_resolved(self, data):
        if data["attacker"] == self.owner and data.get("weapon") == "ranged":
            data["damage"] += 2
            print(f"{self.owner.name}'s Bracers add +2 damage!")

class RingOfProtection(Feature):
    name = "Ring of Protection"
    EVENT_MAP = {"saving_throw": "on_saving_throw"}

    def attach(self, owner, bus):
        super().attach(owner, bus)
        owner.apply_misc_ac(+1)
        print(f"  {owner.name} attuned Ring of Protection (+1 AC)")

    def on_saving_throw(self, ctx):
        if ctx.get("target") is self.owner:
            ctx["bonus"] = ctx.get("bonus", 0) + 1

    def detach(self):
        self.owner.apply_misc_ac(-1)
        super().detach()
class CloakOfProtction(Feature):
    name = "Cloak of Protection"
    EVENT_MAPT = {"saving_throw":"on_saving_throw"}

    def attach(self,owner,bus):
        super().attach(owner, bus)
        owner.apply_misc_ac(+1)
    def on_saving_throw(self,ctx):
        if ctx.get("target") is self.owner:
            ctx["bonus"] = ctx.get("bonus",0)+1
    def detach(self):
        self.owner.apply_misc_ac(-1)
        super().detach()