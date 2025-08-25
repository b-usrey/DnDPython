import os
import json
from core.item import Item

from pdb import set_trace as S
def load_json(file):
    with open(file,"r") as f:
        return json.load(f)
def load_item_json(item_name):
    ITEM_DATA = load_json("data\\items.json")
    ENCHANTMENTS = load_json("data\\items\enchantments.json")
    base_name = item_name
    enchantKey = None
    if "+" in item_name:
        base_name,bonus = item_name.split("+",1)
        base_name = base_name.strip()
        enchantKey = "+"+bonus.strip()
    if base_name in ITEM_DATA:
        data = ITEM_DATA[base_name]
    else:
        print(f"{item_name} not in data/items.json, go add it there")
    if enchantKey:
        data['name'] = base_name+enchantKey
        if enchantKey not in ENCHANTMENTS:
            raise ValueError(f"Unknown Enchantment: {enchantKey}")
        for k,v in ENCHANTMENTS[enchantKey].items():
            data[k] = data.get(k,0)+v            
    return Item(**data)
