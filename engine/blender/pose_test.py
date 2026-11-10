"""Render a pose/expression contact sheet for a built character (tests the pose library).
blender --background --python pose_test.py -- <character_dir> <out.png> pose:face pose:face ...
"""
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import abs_common as C  # noqa: E402
import abs_poses as PZ  # noqa: E402
import abs_retarget as RT  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
CHAR, OUTP, items = os.path.abspath(argv[0]), os.path.abspath(argv[1]), [a for a in argv[2:] if not a.startswith("--")]
bpy.ops.wm.open_mainfile(filepath=os.path.join(CHAR, "character.blend"))
sc = bpy.context.scene
arm = [o for o in sc.objects if o.type == "ARMATURE"][0]
face = next((o for o in sc.objects if o.type == "MESH" and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 20), None)
META = json.load(open(os.path.join(CHAR, "character.json"))) if os.path.exists(os.path.join(CHAR, "character.json")) else {}
FIDX = None
PZ.use_pose_set(META.get("pose_set", ""))
if face is None:  # texture-swap faces (projected characters)
    for o in sc.objects:
        for m in (o.data.materials if o.type == "MESH" else []):
            if m and m.node_tree and "FaceIdx" in m.node_tree.nodes:
                FIDX = m.node_tree.nodes["FaceIdx"].outputs[0]
sc.render.engine = "BLENDER_EEVEE"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("W")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.72, 0.8, 1)
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
sun.data.energy = 3
cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 40
C.look_at(cam, *(((0.1, -1.9, 1.2), (0, 0, 1.12)) if "--close" in argv else ((0.1, -3.0, 1.0), (0, 0, 0.92))))
sc.render.resolution_x, sc.render.resolution_y = 360, 560
tmp = []
for i, it in enumerate(items):
    pose, _, fc = it.partition(":")
    spec = PZ.POSES[pose](0.3)
    if META.get("ik") and "--fk" not in argv:
        spec = RT.retarget(spec, META["ik"])
    C.apply_pose(arm, spec)
    if FIDX is not None:
        tex = META.get("face_map", {}).get(fc or "neutral", fc or "neutral")
        FIDX.default_value = float(META["faces"].index(tex)) if tex in META.get("faces", []) else 0.0
    else:
        for k in face.data.shape_keys.key_blocks[1:]:
            k.value = 0
        for k, v in PZ.FACES.get(fc or "neutral", {}).items():
            key = C.shape_key(face, k)
            if key:
                key.value = v
    p = OUTP + f".{i:02d}.png"
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    tmp.append(p)
print("FRAMES", ";".join(tmp))
