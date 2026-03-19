import os
import json
from core.item import Item

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load_json(relative_path):
    full_path = os.path.join(_BASE, relative_path)
    with open(full_path, "r") as f:
        return json.load(f)

def load_item_json(item_name):
    ITEM_DATA = _load_json(os.path.join("data", "items.json"))
    ENCHANTMENTS = _load_json(os.path.join("data", "enchantments.json"))
    base_name = item_name
    enchant_key = None
    if "+" in item_name:
        base_name, bonus = item_name.split("+", 1)
        base_name = base_name.strip()
        enchant_key = "+" + bonus.strip()
    if base_name not in ITEM_DATA:
        print(f"'{item_name}' not found in data/items.json")
        return None
    data = dict(ITEM_DATA[base_name])
    if enchant_key:
        data["name"] = base_name + enchant_key
        if enchant_key not in ENCHANTMENTS:
            raise ValueError(f"Unknown enchantment: {enchant_key}")
        for k, v in ENCHANTMENTS[enchant_key].items():
            data[k] = data.get(k, 0) + v
    return Item(**data)