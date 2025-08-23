# -*- coding: utf-8 -*-
"""
Created on Tue Aug 19 19:06:08 2025

@author: Bryce
"""

import json
import os

def load_class_json(class_name):
    path = os.path.join("data", "classes", f"{class_name.lower()}.json")
    with open(path, "r") as f:
        return json.load(f)
