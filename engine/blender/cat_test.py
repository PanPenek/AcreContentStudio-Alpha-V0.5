"""Contact sheet of cat behaviours: blender --background --python cat_test.py -- <out_prefix> action[@t] ..."""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abs_cat as CAT  # noqa: E402
import abs_common as C  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, acts = os.path.abspath(argv[0]), argv[1:]
bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("W")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.8, 0.78, 0.85, 1)
C.add_prim("plane", "floor", size=4, mat=C.toon_mat("fl", color=(0.85, 0.75, 0.62)))
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
sun.data.energy = 3
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 40
C.look_at(cam, (0.45, -0.95, 0.42), (0, 0, 0.14))
sc.render.resolution_x, sc.render.resolution_y = 400, 400
rig = CAT.build_cat("Cat", "orange")
for i, a in enumerate(acts):
    name, _, tt = a.partition("@")
    p = CAT.cat_params(name, float(tt or 0.7))
    p["yaw"] = -30
    CAT.apply_params(rig, p)
    sc.render.filepath = f"{OUT}.{i:02d}.png"
    bpy.ops.render.render(write_still=True)
print("DONE")
