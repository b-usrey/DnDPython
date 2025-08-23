import os
import json
from core.item import Item
def load_item_json(item_name):
    path = os.path.join("data", "items", f"{item_name.lower()}.json")
    with open(path, "r") as f:
        data = json.load(f)
    return Item(**data)
