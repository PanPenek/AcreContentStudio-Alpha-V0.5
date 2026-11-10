"""Write engine/kit_catalog.json (name, desc, params, size of every abs_kit prop) for the Script Writer prompt.

blender --background --python engine/blender/dump_kit_catalog.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import abs_kit as K  # noqa: E402

out = os.path.join(os.path.dirname(HERE), "kit_catalog.json")
cat = K.catalog()
json.dump({"kits": cat, "aliases": sorted(K.ALIASES)}, open(out, "w", encoding="utf-8"), indent=1)
print("KIT_CATALOG", out, len(cat))
