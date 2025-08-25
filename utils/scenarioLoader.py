from core.player2 import PlayerCharacter
from data.features.features import Feature
from data.monsters.monsters import *
from utils.load_item import load_item_json
from pdb import set_trace as S
class ScenarioLoader:
    def __init__(self, factory, event_manager):
        self.factory = factory
        self.event = event_manager

    def load(self, scenario_data):
        players = []
        monsters = []

        # Load player characters
        for pdata in scenario_data.get("players", []):
            pc = PlayerCharacter(
                pdata["name"],
                pdata["classes"],
                pdata["subclasses"],
                pdata["stats"],
                self.event,
                pdata.get("choices", [])
            )
            # Load and equip items
            for item_name in pdata.get("items", []):
                item = load_item_json(item_name)
                pc.add_item(item)
            for eq_name in pdata.get("equipped", []):
                pc.equip_item(eq_name)

            # Extra features (like feats not tied to class/subclass)
            for fname in pdata.get("features", []):
                if fname in Feature.REGISTRY:
                    pc.features.append(Feature.REGISTRY[fname]())

            players.append(pc)

        # Load monsters
        for mdata in scenario_data.get("monsters", []):
            for _ in range(mdata.get("count", 1)):
                monsters.append(self.factory.create(MONSTER_REGISTRY[mdata["type"]], self.event))

        return players, monsters
